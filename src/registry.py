"""Registering a model with its lineage, and loading the version the job should serve.

Lineage goes on the registered VERSION, not only the run: at 02:00 the question is which
code and which data produced what is serving now, and the version is where that starts.
"""
from __future__ import annotations

from typing import Any

from src.config import Config

LINEAGE_FIELDS = ["git_commit", "data_fingerprint", "data_version", "mlflow_run_id",
                  "training_job_id", "image_digest", "seed", "metric_val_mae", "metric_test_mae",
                  "mae_alert_threshold"]


def register(cfg: Config, run_id: str, lineage: dict[str, str], metrics: dict[str, float]) -> str:
    import mlflow

    tags = {**lineage, "mlflow_run_id": run_id,
            "metric_val_mae": f"{metrics['val_model_mae']:.3f}",
            "metric_test_mae": f"{metrics['test_model_mae']:.3f}",
            "mae_alert_threshold": f"{metrics['mae_alert_threshold']:.3f}"}
    missing = [f for f in LINEAGE_FIELDS if not tags.get(f) or tags[f] == "unknown"]
    if missing:
        raise ValueError(f"refusing to register without lineage: {missing}")

    mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    version = mlflow.register_model(f"runs:/{run_id}/model", cfg.model_name).version
    client = mlflow.MlflowClient()
    for key in LINEAGE_FIELDS:
        client.set_model_version_tag(cfg.model_name, version, key, tags[key])
    return str(version)


def promote(cfg: Config, version: str) -> str | None:
    """Point `champion` at a version. Returns the version it pointed at before, if any.

    This is the bad-model rollback: the next hourly run loads whatever `champion` names.
    """
    import mlflow

    mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    client = mlflow.MlflowClient()
    client.get_model_version(cfg.model_name, version)          # fails loudly if it is not there
    try:
        previous = client.get_model_version_by_alias(cfg.model_name, "champion").version
    except mlflow.exceptions.MlflowException:
        previous = None
    client.set_registered_model_alias(cfg.model_name, "champion", version)
    return str(previous) if previous else None


def previous_version(cfg: Config) -> str:
    """The highest registered version below the current champion: what a rollback serves."""
    import mlflow

    mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    client = mlflow.MlflowClient()
    current = int(client.get_model_version_by_alias(cfg.model_name, "champion").version)
    older = [int(v.version) for v in client.search_model_versions(f"name='{cfg.model_name}'")
             if int(v.version) < current]
    if not older:
        raise ValueError(f"version {current} is the oldest; there is nothing to roll back to")
    return str(max(older))


def main() -> int:
    """python -m src.registry promote VERSION | rollback | show"""
    import argparse

    from src import config

    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["promote", "rollback", "show"])
    ap.add_argument("version", nargs="?")
    args = ap.parse_args()
    cfg = config.load()

    if args.action == "show":
        import mlflow

        mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
        client = mlflow.MlflowClient()
        # search results do not carry aliases on every backend; ask the model itself.
        aliases_of: dict[str, list[str]] = {}
        for alias, ver in client.get_registered_model(cfg.model_name).aliases.items():
            aliases_of.setdefault(str(ver), []).append(alias)
        for v in sorted(client.search_model_versions(f"name='{cfg.model_name}'"),
                        key=lambda v: int(v.version)):
            aliases = ",".join(aliases_of.get(str(v.version), []))
            print(f"v{v.version:<4} {aliases:<10} val_mae={v.tags.get('metric_val_mae', '?'):<8}"
                  f" commit={v.tags.get('git_commit', '?')[:8]}")
        return 0
    if args.action == "promote" and not args.version:
        ap.error("promote needs a VERSION")
    target = args.version if args.action == "promote" else previous_version(cfg)
    before = promote(cfg, target)
    print(f"{cfg.model_name}: champion {before or '(none)'} -> {target}")
    return 0


def load_serving_model(cfg: Config) -> tuple[Any, float | None]:
    """The model the job serves and the accuracy-alert threshold stored with it.

    MODEL_VERSION picks a version; when it is empty the alias `champion` is used, so a
    rollback is one command: point the alias at the previous version.
    """
    import mlflow
    import mlflow.sklearn

    mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    client = mlflow.MlflowClient()
    if cfg.model_version:
        version = client.get_model_version(cfg.model_name, cfg.model_version)
    else:
        version = client.get_model_version_by_alias(cfg.model_name, "champion")
    model = mlflow.sklearn.load_model(f"models:/{cfg.model_name}/{version.version}")
    threshold = version.tags.get("mae_alert_threshold")
    return model, float(threshold) if threshold else None


if __name__ == "__main__":
    raise SystemExit(main())
