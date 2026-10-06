"""The model registry: registering with lineage, promoting by alias, and loading what serves.

    python -m src.registry show
    python -m src.registry promote VERSION [--alias production]
    python -m src.registry rollback [--alias production]

The registry is MLflow on every provider (portability reference §5), so this module is
Layer 1. Lineage goes on the registered VERSION, not only the run (Lab 2): at 02:00 the
question is which code and which data produced what is serving now, and the version is
where that question starts.

Promotion is a separate, deliberate step, with MLflow aliases in place of stages:
`staging` is what CD and the pipeline deploy for checking; `production` is what the hourly
job serves. Rollback is pointing an alias back at the previous version.
"""
from __future__ import annotations

from typing import Any

from src.config import Config

# The course's eight lineage fields (Lab 2, Task 4), plus the accuracy-alert threshold the
# hourly job reads from the version it serves.
LINEAGE_FIELDS = ("git_commit", "data_version", "mlflow_run_id", "training_job_id",
                  "image_digest", "seed", "metric_val", "metric_test")
EXTRA_FIELDS = ("mae_alert_threshold", "data_fingerprint")


def _client(cfg: Config):
    import mlflow

    mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    return mlflow.MlflowClient()


def register_run(cfg: Config, model_uri: str, name: str) -> str:
    """Register runs:/<run_id>/model and copy its lineage onto the version.

    Every field is read from the run itself. If one is missing, nothing is registered: a
    version without lineage cannot answer "which code, which data, which parameters".
    """
    import mlflow

    if not model_uri.startswith("runs:/"):
        raise ValueError(f"expected runs:/<run_id>/model, got {model_uri!r}")
    run_id = model_uri[len("runs:/"):].split("/", 1)[0]
    client = _client(cfg)
    run = client.get_run(run_id)
    tags, params, metrics = run.data.tags, run.data.params, run.data.metrics

    lineage = {
        "git_commit": tags.get("git_commit"),
        "data_version": tags.get("data_version"),
        "mlflow_run_id": run_id,
        "training_job_id": tags.get("training_job_id"),
        "image_digest": tags.get("image_digest"),
        "seed": params.get("seed"),
        "metric_val": metrics.get("val_mae"),
        "metric_test": metrics.get("test_mae"),
        "mae_alert_threshold": metrics.get("mae_alert_threshold"),
        "data_fingerprint": tags.get("data_fingerprint"),
    }
    missing = sorted(k for k, v in lineage.items() if v in (None, "", "unknown", "unversioned"))
    if missing:
        raise ValueError(f"run {run_id} lacks lineage fields {missing}; not registering")

    version = mlflow.register_model(model_uri, name).version
    for key, value in lineage.items():
        client.set_model_version_tag(name, version, key, str(value))
    return str(version)


def promote(cfg: Config, version: str, alias: str | None = None) -> str | None:
    """Point `alias` at `version`. Returns the version it pointed at before, if any."""
    import mlflow

    alias = alias or cfg.model_alias
    client = _client(cfg)
    client.get_model_version(cfg.model_registry_name, version)  # fails loudly if absent
    try:
        previous = client.get_model_version_by_alias(cfg.model_registry_name, alias).version
    except mlflow.exceptions.MlflowException:
        previous = None
    client.set_registered_model_alias(cfg.model_registry_name, alias, version)
    return str(previous) if previous else None


def previous_version(cfg: Config, alias: str | None = None) -> str:
    """The highest registered version below the one `alias` names: what a rollback serves."""
    alias = alias or cfg.model_alias
    client = _client(cfg)
    current = int(client.get_model_version_by_alias(cfg.model_registry_name, alias).version)
    older = [int(v.version)
             for v in client.search_model_versions(f"name='{cfg.model_registry_name}'")
             if int(v.version) < current]
    if not older:
        raise ValueError(f"version {current} is the oldest; there is nothing to roll back to")
    return str(max(older))


def serving_version(cfg: Config) -> Any:
    """The registered version the job serves: MODEL_VERSION if pinned, else the alias."""
    client = _client(cfg)
    if cfg.model_version:
        return client.get_model_version(cfg.model_registry_name, cfg.model_version)
    return client.get_model_version_by_alias(cfg.model_registry_name, cfg.model_alias)


def load_serving_model(cfg: Config) -> tuple[Any, float | None, str]:
    """(model, accuracy-alert threshold stored with it, version number).

    Loaded from the registry by version — never from a local file — so what serves is
    always something with lineage (Lab 2, Task 5).
    """
    import mlflow.sklearn

    version = serving_version(cfg)
    model = mlflow.sklearn.load_model(f"models:/{cfg.model_registry_name}/{version.version}")
    threshold = version.tags.get("mae_alert_threshold")
    return model, float(threshold) if threshold else None, str(version.version)


def show(cfg: Config) -> list[str]:
    client = _client(cfg)
    name = cfg.model_registry_name
    # Search results do not carry aliases on every backend; ask the registered model itself.
    aliases_of: dict[str, list[str]] = {}
    for alias, ver in client.get_registered_model(name).aliases.items():
        aliases_of.setdefault(str(ver), []).append(alias)
    lines = []
    for v in sorted(client.search_model_versions(f"name='{name}'"), key=lambda v: int(v.version)):
        aliases = ",".join(sorted(aliases_of.get(str(v.version), [])))
        lines.append(f"v{v.version:<4} {aliases:<20} val_mae={v.tags.get('metric_val', '?')[:7]:<8}"
                     f" commit={v.tags.get('git_commit', '?')[:8]}"
                     f" data={v.tags.get('data_version', '?')[:8]}")
    return lines


def main() -> int:
    import argparse

    from src import config

    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["promote", "rollback", "show"])
    ap.add_argument("version", nargs="?")
    ap.add_argument("--alias", default=None, help="default MODEL_ALIAS (production)")
    args = ap.parse_args()
    cfg = config.load()
    alias = args.alias or cfg.model_alias

    if args.action == "show":
        print("\n".join(show(cfg)))
        return 0
    if args.action == "promote" and not args.version:
        ap.error("promote needs a VERSION")
    target = args.version if args.action == "promote" else previous_version(cfg, alias)
    before = promote(cfg, target, alias)
    print(f"{cfg.model_registry_name}@{alias}: {before or '(none)'} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
