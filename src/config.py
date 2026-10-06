"""Configuration. The ONLY module in src/ allowed to know about the environment.

Course rule (portability reference, Layer 2): nothing under src/ may contain a bucket name, a
provider hostname, or an absolute path from a developer machine. Everything arrives through
here, which reads cloud.env. Variables already exported win, so CI and the cloud job can
override the file. `make portability-audit` enforces the rule.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / "cloud.env"

# The eight capability slots every lab depends on. scripts/cloud_check.py resolves each.
CAPABILITY_SLOTS = (
    "CLOUD_PROVIDER",
    "PROJECT_ID",
    "REGION",
    "BLOB_URI",
    "CONTAINER_REGISTRY",
    "MLFLOW_TRACKING_URI",
    "MODEL_REGISTRY_NAME",
    "IDENTITY_REF",
)

# Every resource this project creates carries lab=capstone, so `make teardown LAB=capstone`
# deletes the project and never a lab's storage or registry.
RESOURCE_LAB = "capstone"


def _load_env_file(path: Path = ENV_FILE) -> None:
    """Minimal .env loader. An already-exported variable wins, so CI can override cloud.env."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.split(" #", 1)[0].strip())


_load_env_file()


@dataclass(frozen=True)
class Config:
    provider: str
    project_id: str
    region: str
    blob_uri: str
    container_registry: str
    mlflow_tracking_uri: str
    model_registry_name: str
    identity_ref: str
    training_target: str = ""
    # Which registered version the hourly job serves: MODEL_VERSION pins one, otherwise the
    # version the alias MODEL_ALIAS points at. Rollback is moving the alias.
    model_version: str = ""
    model_alias: str = "production"
    # Service levels from the proposal. Changing these changes what the alerts mean.
    weather_max_age_min: int = 60
    # How long the model may keep forecasting from the last good reading before the job falls
    # back to "same hour last week". 48 h is as far as the drill measured, and the model on a
    # stale reading beat the baseline at every age up to it but the evening peak
    # (reports/stale-reading-study.md).
    stale_model_max_age_min: int = 2880
    job_max_duration_s: int = 300
    forecast_horizon_h: int = 24
    data_dir: Path = field(default=REPO_ROOT / "data")
    reports_dir: Path = field(default=REPO_ROOT / "reports")

    @property
    def raw_path(self) -> Path:
        return self.data_dir / "raw" / "hour.csv"

    def tags(self, lab: str = RESOURCE_LAB) -> dict[str, str]:
        """Every cloud resource carries these. `make teardown` finds resources by tag."""
        return {"course": "itcs355", "student": self.project_id, "lab": str(lab)}


def load(strict: bool = True) -> Config:
    """Read the environment. With strict=True, a cloud provider with an empty capability
    slot is refused here, not discovered halfway through a deploy. The local provider
    needs none of them: everything falls back to files under the repository."""
    get = os.environ.get
    provider = get("CLOUD_PROVIDER") or "local"
    missing = [s for s in CAPABILITY_SLOTS if not get(s)]
    if strict and provider != "local" and missing:
        raise RuntimeError(
            "Missing capability slots: " + ", ".join(missing)
            + "\nCopy cloud.env.example to cloud.env, fill it in, then run `make cloud-check`."
        )
    return Config(
        provider=provider,
        project_id=get("PROJECT_ID") or "itcs355-local",
        region=get("REGION") or "local",
        blob_uri=get("BLOB_URI") or str(REPO_ROOT / ".local-store"),
        container_registry=get("CONTAINER_REGISTRY") or "",
        mlflow_tracking_uri=get("MLFLOW_TRACKING_URI") or f"sqlite:///{REPO_ROOT / 'mlflow.db'}",
        model_registry_name=get("MODEL_REGISTRY_NAME") or "bike-demand",
        identity_ref=get("IDENTITY_REF") or "",
        training_target=get("TRAINING_TARGET") or "",
        model_version=get("MODEL_VERSION") or "",
        model_alias=get("MODEL_ALIAS") or "production",
        weather_max_age_min=int(get("WEATHER_MAX_AGE_MIN") or 60),
        stale_model_max_age_min=int(get("STALE_MODEL_MAX_AGE_MIN") or 2880),
        job_max_duration_s=int(get("JOB_MAX_DURATION_S") or 300),
    )
