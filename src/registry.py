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
