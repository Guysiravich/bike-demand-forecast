"""Azure adapter. Carried over from the course labs (Labs 1-4, Guysiravich/public_teaching_mlaiops),
with the serving methods re-pointed from an online Container App to a scheduled Container Apps Job.

  upload / download        Blob Storage through DefaultAzureCredential (Lab 1)
  push_image               docker push to ACR, returns registry/repo@sha256:... (Lab 1)
  submit_training / wait   Azure ML command job on TRAINING_TARGET (Lab 2)
  register_model           the self-hosted MLflow registry (base class; Lab 2)
  deploy                   a Container Apps Job on a cron schedule — batch inference (Lab 3)
  invoke                   start one execution of that job now (Lab 3)
  emit_metric              Azure Monitor custom metric on METRICS_RESOURCE_ID (Lab 4)
  schedule                 Azure ML job schedule — scheduled retraining (Lab 4/5)
  teardown                 delete by tag, never by resource group (Lab 3/5)

Why a Container Apps Job and not an Azure ML schedule for the hourly run: the drift job in
Lab 4 ran on the scale-to-zero DS2_v2 cluster at about 10 node-minutes a run, ~1.2 THB. Hourly
that is ~860 THB a month, over the whole term's budget. A Container Apps Job at 0.5 vCPU for a
minute an hour stays inside the monthly free grant. Training stays on Azure ML (Lab 2).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cloudlayer.base import CloudAdapter

# This adapter uses the https form of BLOB_URI:
#   https://<account>.blob.core.windows.net/<container>/<path>
_BLOB_HOST_SUFFIX = ".blob.core.windows.net"
_DIGEST = re.compile(r"digest:\s*(sha256:[0-9a-f]{64})")
_POLL_SECONDS = 30
# The Azure CLI can take over 10 s (the SDK default) to refresh a token from WSL.
_CLI_TIMEOUT_SECONDS = 60
_TRAINING_TARGET = re.compile(
    r"^/subscriptions/(?P<sub>[^/]+)/resourceGroups/(?P<rg>[^/]+)"
    r"/providers/Microsoft\.MachineLearningServices/workspaces/(?P<ws>[^/]+)"
    r"/computes/(?P<compute>[^/]+)$",
    re.IGNORECASE,
)


def _parse_blob_uri(uri: str) -> tuple[str, str, str]:
    """Split a blob URI into (account, container, path). Path may be empty."""
    parsed = urlparse(uri)
    if parsed.scheme != "https" or not parsed.netloc.endswith(_BLOB_HOST_SUFFIX):
        raise ValueError(
            f"Expected https://<account>{_BLOB_HOST_SUFFIX}/<container>/<path>, got {uri!r}"
        )
    account = parsed.netloc[: -len(_BLOB_HOST_SUFFIX)]
    container, _, path = parsed.path.lstrip("/").partition("/")
    if not account or not container:
        raise ValueError(f"Blob URI {uri!r} is missing the account or the container")
    return account, container, path.strip("/")


def _blob_url(account: str, container: str, path: str) -> str:
    return f"https://{account}{_BLOB_HOST_SUFFIX}/{container}/{path}"


def _job_uri(uri: str) -> str:
    """BLOB_URI form -> the form Azure ML jobs accept. Azure ML treats https:// as public,
    read-only storage and rejects it as an output (NotSupportedAssetOutputUri, Lab 2)."""
    account, container, path = _parse_blob_uri(uri)
    return f"wasbs://{container}@{account}{_BLOB_HOST_SUFFIX}/{path}"


_SECRET_ARG = re.compile(r"^([\w-]*(password|secret|key|token)[\w-]*=).+$", re.IGNORECASE)


def _redact(cmd: list[str]) -> str:
    """The command as text for an error message, with secret values masked. A failed
    `az containerapp job create` once printed the tracking server's password here (found on
    first deploy); in CD that text lands in a public Actions log."""
    return " ".join(_mask(part) for part in cmd)


def _mask(part: str) -> str:
    match = _SECRET_ARG.match(part)
    return f"{match.group(1)}<redacted>" if match else part


def _query(cmd: list[str]) -> str:
    """Run a CLI query and return STDOUT only. The containerapp extension prints a WARNING on
    stderr; an emptiness test on stdout+stderr sees a non-empty string (Lab 3)."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"`{_redact(cmd)}` failed ({result.returncode}):\n{result.stderr}")
    return result.stdout.strip()


def _run(cmd: list[str]) -> str:
    """Run a CLI command; raise with its output if it fails. Returns stdout and stderr
    together, because `docker push` prints the digest on stderr."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"`{_redact(cmd)}` failed ({result.returncode}):\n{result.stdout}{result.stderr}"
        )
    return result.stdout + result.stderr


def _parse_training_target(target: str) -> tuple[str, str, str, str]:
    """TRAINING_TARGET is the compute's resource ID; split it into its four names."""
    m = _TRAINING_TARGET.match((target or "").strip())
    if not m:
        raise ValueError(
            "TRAINING_TARGET must be an Azure ML compute resource ID: /subscriptions/<id>/"
            "resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<ws>/"
            f"computes/<name>; got {target!r}"
        )
    return m["sub"], m["rg"], m["ws"], m["compute"]


def _parse_instance(instance: str) -> tuple[str, str]:
    """"0.5/1.0Gi" -> ("0.5", "1.0Gi"): the Container Apps unit of size."""
    cpu, _, memory = instance.partition("/")
    if not cpu or not memory:
        raise ValueError(f"Expected <cpu>/<memory>, for example 0.5/1.0Gi, got {instance!r}")
    return cpu, memory


class AzureAdapter(CloudAdapter):
    # --- Lab 1 ---------------------------------------------------------------------------
    def _blob_service(self, account: str) -> Any:
        # Imported here so selecting the adapter does not require the SDK to be installed.
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        return BlobServiceClient(
            account_url=f"https://{account}{_BLOB_HOST_SUFFIX}",
            credential=DefaultAzureCredential(process_timeout=_CLI_TIMEOUT_SECONDS),
        )

    def upload(self, local_path: str, key: str) -> str:
        account, container, prefix = _parse_blob_uri(self.cfg.blob_uri)
        blob_name = "/".join(part for part in (prefix, key.strip("/")) if part)
        blob = self._blob_service(account).get_blob_client(container=container, blob=blob_name)
        with open(local_path, "rb") as fh:
            blob.upload_blob(fh, overwrite=True)
        return _blob_url(account, container, blob_name)

    def download(self, uri: str, local_path: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        account, container, blob_name = _parse_blob_uri(uri)
        if not blob_name:
            raise ValueError(f"Blob URI {uri!r} names a container, not an object")
        blob = self._blob_service(account).get_blob_client(container=container, blob=blob_name)
        try:
            payload = blob.download_blob().readall()
        except ResourceNotFoundError:
            # The base class reads "no such document" as None: the first tick has no clock.
            raise FileNotFoundError(uri) from None
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)

    def push_image(self, local_tag: str) -> str:
        registry = self.cfg.container_registry.strip("/")  # <name>.azurecr.io/<namespace>
        login_server = registry.split("/", 1)[0]
        registry_name = login_server.split(".", 1)[0]

        name, sep, tag = local_tag.rpartition(":")
        if not sep or "/" in tag:  # no tag given
            name, tag = local_tag, "latest"
        remote_repo = f"{registry}/{name.rsplit('/', 1)[-1]}"
        remote_tag = f"{remote_repo}:{tag}"

        _run(["az", "acr", "login", "--name", registry_name])
        _run(["docker", "tag", local_tag, remote_tag])
        output = _run(["docker", "push", remote_tag])

        match = _DIGEST.search(output)
        if not match:
            raise RuntimeError(f"`docker push` reported no digest for {remote_tag}:\n{output}")
        return f"{remote_repo}@{match.group(1)}"

    # --- Lab 2 ---------------------------------------------------------------------------
    def _ml_client(self) -> tuple[Any, str]:
        from azure.ai.ml import MLClient
        from azure.identity import DefaultAzureCredential

        subscription, resource_group, workspace, compute = _parse_training_target(
            self.cfg.training_target
        )
        client = MLClient(DefaultAzureCredential(process_timeout=_CLI_TIMEOUT_SECONDS),
                          subscription, resource_group, workspace)
        return client, compute

    def submit_training(self, image_uri: str, args: dict[str, Any]) -> str:
        """Run a module from the training image as an Azure ML command job.

        args (all optional):
          module      python module to run inside the image (default "src.train")
          arguments   list of CLI arguments; the token {output} becomes the job's output folder
          data_uri    blob folder mounted read-only and copied to /app/data (default BLOB_URI/data)
          output_uri  blob folder the job writes to (default BLOB_URI/jobs/<job>)
          env         extra environment variables (non-secret)
          experiment  experiment name shown in Azure ML (default "bike-demand")
        """
        client, job = self._command_job(image_uri, args)
        return client.jobs.create_or_update(job).name

    def _command_job(self, image_uri: str, args: dict[str, Any]) -> tuple[Any, Any]:
        """Build (not submit) the command job submit_training describes. schedule() wraps the
        same job in a trigger, so a scheduled run is exactly a submitted one."""
        import shlex
        import uuid

        from azure.ai.ml import Input, Output, command
        from azure.ai.ml.constants import AssetTypes, InputOutputModes
        from azure.ai.ml.entities import Environment

        client, compute = self._ml_client()
        job_name = f"bike-{uuid.uuid4().hex[:12]}"
        blob_root = self.cfg.blob_uri.rstrip("/")
        data_uri = args.get("data_uri", f"{blob_root}/data")
        output_uri = args.get("output_uri", f"{blob_root}/jobs/{job_name}")

        module = args.get("module", "src.train")
        arguments = " ".join(
            shlex.quote(str(a)).replace("{output}", "${{outputs.output}}")
            for a in args.get("arguments", [])
        )
        cmd = (
            "mkdir -p /app/data && cp -r ${{inputs.data}}/. /app/data/ && "
            f"cd /app && python -m {module} {arguments}"
        ).strip()

        env = {
            "TRAINING_JOB_ID": job_name,
            "IMAGE_DIGEST": image_uri.split("@", 1)[1] if "@" in image_uri else image_uri,
            **{k: str(v) for k, v in args.get("env", {}).items()},
        }
        # Azure ML overwrites MLFLOW_TRACKING_URI in every job with its own azureml:// store
        # (Lab 2). Pass our server under another name and restore it inside the job.
        if "MLFLOW_TRACKING_URI" in env:
            env["BIKE_MLFLOW_TRACKING_URI"] = env.pop("MLFLOW_TRACKING_URI")
            cmd = (
                'export MLFLOW_TRACKING_URI="$BIKE_MLFLOW_TRACKING_URI" && '
                "unset MLFLOW_RUN_ID MLFLOW_EXPERIMENT_ID MLFLOW_EXPERIMENT_NAME "
                "MLFLOW_TRACKING_TOKEN && " + cmd
            )
        job = command(
            name=job_name,
            display_name=args.get("display_name", module),
            experiment_name=args.get("experiment", "bike-demand"),
            command=cmd,
            environment=Environment(image=image_uri),
            compute=compute,
            inputs={"data": Input(type=AssetTypes.URI_FOLDER, path=_job_uri(data_uri),
                                  mode=InputOutputModes.RO_MOUNT)},
            outputs={"output": Output(type=AssetTypes.URI_FOLDER, path=_job_uri(output_uri),
                                      mode=InputOutputModes.RW_MOUNT)},
            environment_variables=env,
            tags=self.cfg.tags(),
        )
        return client, job

    def wait_training(self, job_id: str) -> dict[str, Any]:
        """Poll the job until it reaches a terminal state. Returns its final status."""
        import time

        client, _ = self._ml_client()
        terminal = {"Completed", "Failed", "Canceled", "NotResponding"}
        last = None
        while True:
            job = client.jobs.get(job_id)
            if job.status != last:
                print(f"  {job_id}: {job.status}", flush=True)
                last = job.status
            if job.status in terminal:
                return {"job_id": job_id, "status": job.status,
                        "studio_url": getattr(job, "studio_url", None)}
            time.sleep(_POLL_SECONDS)

    # --- Lab 3: batch inference as a scheduled Container Apps Job -------------------------
    def _group(self) -> str:
        """The resource group, read from the identity's resource id (IDENTITY_REF)."""
        match = re.search(r"/resourceGroups/([^/]+)/", self.cfg.identity_ref, re.IGNORECASE)
        if not match:
            raise ValueError("IDENTITY_REF must be the user-assigned identity's resource id")
        return match.group(1)

    def _ensure_environment(self, group: str, environment: str) -> None:
        existing = _query(["az", "containerapp", "env", "list", "-g", group,
                           "--query", f"[?name=='{environment}'].name", "-o", "tsv"])
        if existing:
            return
        # Job stdout goes to Log Analytics when a workspace is given: the structured log lines
        # are how a crash is explained within a minute during the demo.
        workspace = os.environ.get("JOB_LOG_WORKSPACE", "")
        if workspace:
            # get-shared-keys takes no --ids (found on first deploy): name the group and workspace.
            ws_group = workspace.split("/resourceGroups/", 1)[1].split("/", 1)[0]
            ws_name = workspace.rstrip("/").rsplit("/", 1)[1]
            customer_id = _query(["az", "monitor", "log-analytics", "workspace", "show",
                                  "-g", ws_group, "-n", ws_name,
                                  "--query", "customerId", "-o", "tsv"])
            key = _query(["az", "monitor", "log-analytics", "workspace", "get-shared-keys",
                          "-g", ws_group, "-n", ws_name,
                          "--query", "primarySharedKey", "-o", "tsv"])
            logs = ["--logs-destination", "log-analytics",
                    "--logs-workspace-id", customer_id, "--logs-workspace-key", key]
        else:
            logs = ["--logs-destination", "none"]
        # WorkloadProfiles, not the default express mode: express refuses Job resources
        # (ExpressEnvironmentResourceNotSupported, first deploy) as it refused Lab 3's canary.
        # Jobs still run on the consumption profile and its free grant.
        _run(["az", "containerapp", "env", "create", "-g", group, "-n", environment,
              "-l", self.cfg.region, "--environment-mode", "WorkloadProfiles", *logs,
              "--tags", *[f"{k}={v}" for k, v in self.cfg.tags().items()], "-o", "none"])

    def deploy(self, model_ref: str, endpoint: str, instance: str) -> str:
        """Create or update the scheduled job `endpoint`. Returns its resource id.

        model_ref  models:/<name>@<alias> or models:/<name>/<version> — what the forecast job
                   serves; "" for the feeder, which has no model
        endpoint   the Container Apps Job name
        instance   "<cpu>/<memory>", e.g. "0.5/1.0Gi"

        From the environment (set by scripts/deploy.py): JOB_IMAGE (digest-pinned), JOB_MODULE
        (src.forecast or src.feeder), FORECAST_CRON, JOB_ENVIRONMENT. The registry is read with
        the user-assigned identity, never a password; the tracking server's credentials are
        Container Apps secrets, referenced with secretref:, never plain values.
        """
        cpu, memory = _parse_instance(instance)
        group = self._group()
        identity = self.cfg.identity_ref
        image = os.environ["JOB_IMAGE"]
        module = os.environ["JOB_MODULE"]
        environment = os.environ.get("JOB_ENVIRONMENT", "bike-env")
        cron = os.environ.get("FORECAST_CRON", "0 * * * *")
        registry = self.cfg.container_registry.split("/")[0]
        self._ensure_environment(group, environment)

        env = {
            "CLOUD_PROVIDER": "azure",
            "PROJECT_ID": self.cfg.project_id,
            "REGION": self.cfg.region,
            "BLOB_URI": self.cfg.blob_uri,
            "CONTAINER_REGISTRY": self.cfg.container_registry,
            "MLFLOW_TRACKING_URI": self.cfg.mlflow_tracking_uri,
            "MODEL_REGISTRY_NAME": self.cfg.model_registry_name,
            "IDENTITY_REF": identity,
            "METRICS_RESOURCE_ID": os.environ.get("METRICS_RESOURCE_ID", ""),
            # DefaultAzureCredential inside the job picks the user-assigned identity by id.
            "AZURE_CLIENT_ID": _query(["az", "identity", "show", "--ids", identity,
                                       "--query", "clientId", "-o", "tsv"]),
            "WEATHER_MAX_AGE_MIN": str(self.cfg.weather_max_age_min),
            "STALE_MODEL_MAX_AGE_MIN": str(self.cfg.stale_model_max_age_min),
            "JOB_MAX_DURATION_S": str(self.cfg.job_max_duration_s),
        }
        if model_ref:
            alias = re.fullmatch(r"models:/[^/@]+@(\w+)", model_ref)
            version = re.fullmatch(r"models:/[^/@]+/(\w+)", model_ref)
            if alias:
                env["MODEL_ALIAS"] = alias.group(1)
            elif version:
                env["MODEL_VERSION"] = version.group(1)
            else:
                raise ValueError(
                    f"Expected models:/<name>@<alias> or /<version>, got {model_ref!r}")
        env_args = [f"{k}={v}" for k, v in env.items()] + [
            "MLFLOW_TRACKING_USERNAME=secretref:mlflow-username",
            "MLFLOW_TRACKING_PASSWORD=secretref:mlflow-password",
        ]
        secrets = [f"mlflow-username={os.environ['MLFLOW_TRACKING_USERNAME']}",
                   f"mlflow-password={os.environ['MLFLOW_TRACKING_PASSWORD']}"]
        common = ["-g", group, "-n", endpoint, "--image", image, "--cpu", cpu, "--memory", memory,
                  "--cron-expression", cron, "-o", "none"]

        exists = _query(["az", "containerapp", "job", "list", "-g", group,
                         "--query", f"[?name=='{endpoint}'].name", "-o", "tsv"])
        if exists:
            _run(["az", "containerapp", "job", "secret", "set", "-g", group, "-n", endpoint,
                  "--secrets", *secrets, "-o", "none"])
            _run(["az", "containerapp", "job", "update", *common,
                  "--replace-env-vars", *env_args])
        else:
            _run(["az", "containerapp", "job", "create", *common,
                  "--environment", environment, "--trigger-type", "Schedule",
                  # A run that outlives the SLO is killed, not left to overlap the next tick.
                  "--replica-timeout", str(self.cfg.job_max_duration_s),
                  "--replica-retry-limit", "0", "--parallelism", "1",
                  "--replica-completion-count", "1",
                  "--mi-user-assigned", identity,
                  "--registry-server", registry, "--registry-identity", identity,
                  "--secrets", *secrets, "--env-vars", *env_args,
                  # The image's ENTRYPOINT is `python -m`; the module is its argument. Passing
                  # "-m" here makes the CLI read it as its own option (found on first deploy).
                  "--args", module,
                  "--tags", *[f"{k}={v}" for k, v in self.cfg.tags().items()]])
        return _query(["az", "containerapp", "job", "show", "-g", group, "-n", endpoint,
                       "--query", "id", "-o", "tsv"])

    def invoke(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Start one execution of job `endpoint` now. The payload is unused: the job reads its
        inputs from storage. Returns the execution's name, for `az containerapp job execution`."""
        import json

        out = _query(["az", "containerapp", "job", "start", "-g", self._group(), "-n", endpoint,
                      "-o", "json"])
        return {"execution": json.loads(out).get("name", ""), "job": endpoint}

    # --- Lab 4 ---------------------------------------------------------------------------
    def _token(self, scope: str) -> str:
        from azure.identity import DefaultAzureCredential

        # CLI login on a laptop, the federated identity in GitHub Actions, the job's managed
        # identity in Container Apps. No key anywhere.
        credential = DefaultAzureCredential(process_timeout=_CLI_TIMEOUT_SECONDS)
        return credential.get_token(scope).token

    def emit_metric(self, name: str, value: float, unit: str = "None") -> None:
        """One data point to Azure Monitor custom metrics, on the resource METRICS_RESOURCE_ID
        (the forecast job), namespace bike. A metric alert on that resource sends the email.
        The job's identity needs Monitoring Metrics Publisher on that resource."""
        import datetime
        import json
        import urllib.request

        resource = os.environ["METRICS_RESOURCE_ID"]
        point = {
            "time": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": {"baseData": {
                "metric": name.replace(".", "_"),
                "namespace": "bike",
                "series": [{"min": value, "max": value, "sum": value, "count": 1}],
            }},
        }
        request = urllib.request.Request(
            f"https://{self.cfg.region}.monitoring.azure.com{resource}/metrics",
            data=json.dumps(point).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._token('https://monitoring.azure.com/.default')}"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status >= 300:
                raise RuntimeError(f"emit_metric {name}: HTTP {response.status}")

    def schedule(self, name: str, image_uri: str, args: dict[str, Any], cron: str) -> str:
        """An Azure ML job schedule around the same command job submit_training sends —
        scheduled retraining. Azure ML schedules are workspace objects without resource tags,
        so `make teardown` deletes them by name (scripts/teardown.py)."""
        from azure.ai.ml.entities import CronTrigger, JobSchedule

        client, job = self._command_job(image_uri, args)
        if not cron:
            try:
                client.schedules.begin_disable(name).result()
            except Exception as exc:  # already disabled, or never created
                print(f"  disable {name}: {exc.__class__.__name__}")
            try:
                client.schedules.begin_delete(name).result()
            except Exception as exc:
                if "NotFound" not in str(exc) and "not found" not in str(exc).lower():
                    raise
            return name
        created = client.schedules.begin_create_or_update(
            JobSchedule(name=name, trigger=CronTrigger(expression=cron, time_zone="UTC"),
                        create_job=job, tags=self.cfg.tags())
        ).result()
        return created.name

    # --- Lab 5 ---------------------------------------------------------------------------
    def teardown(self, tags: dict[str, str], dry_run: bool = False) -> list[str]:
        """Delete every resource carrying ALL of these tags. Returns what was deleted.

        Scoped by tag, never by resource group: the group also holds the labs' storage,
        registry and tracking server. A missing "lab" tag is refused rather than widened,
        because the widening is what deletes Lab 1 (course Lab 3 notes).
        """
        if "lab" not in tags or "course" not in tags:
            raise ValueError(f"teardown needs the course and lab tags; got {tags}")
        query = " && ".join(f"tags.{k} == '{v}'" for k, v in tags.items())
        ids = _query(["az", "resource", "list", "--query", f"[?{query}].id", "-o", "tsv"]).split()
        if dry_run:
            return ids
        for resource_id in ids:
            _run(["az", "resource", "delete", "--ids", resource_id, "--verbose"])
        return ids
