"""The bad-model response: registering refuses missing lineage, and a rollback moves the
`champion` alias — the one thing the hourly job reads — back to the previous version.

Uses a throwaway SQLite MLflow store, so it needs no server and no trained model.
"""
from __future__ import annotations

import dataclasses

import mlflow
import mlflow.sklearn
import numpy as np
import pytest
from sklearn.dummy import DummyRegressor

from src import registry

LINEAGE = {"git_commit": "abc1234", "data_fingerprint": "e03de4ee", "data_version": "md5",
           "seed": "1", "training_job_id": "local", "image_digest": "local"}


def metrics(mae: float) -> dict[str, float]:
    return {"val_model_mae": mae, "test_model_mae": mae, "mae_alert_threshold": 1.5 * mae}


@pytest.fixture
def mlcfg(cfg, tmp_path):
    uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("test")
    return dataclasses.replace(cfg, mlflow_tracking_uri=uri, model_name="bike-test",
                               model_version="")


def logged_run(constant: float) -> str:
    model = DummyRegressor(strategy="constant", constant=constant).fit([[0]], [constant])
    with mlflow.start_run() as run:
        mlflow.sklearn.log_model(model, name="model")
    return run.info.run_id


def test_register_refuses_missing_lineage(mlcfg):
    run_id = logged_run(1.0)
    with pytest.raises(ValueError, match="lineage"):
        registry.register(mlcfg, run_id, {**LINEAGE, "git_commit": "unknown"}, metrics(1.0))


def test_rollback_serves_the_previous_version(mlcfg):
    v1 = registry.register(mlcfg, logged_run(1.0), LINEAGE, metrics(10.0))
    v2 = registry.register(mlcfg, logged_run(2.0), LINEAGE, metrics(20.0))
    registry.promote(mlcfg, v2)
    model, threshold = registry.load_serving_model(mlcfg)
    assert model.predict(np.zeros((1, 1)))[0] == 2.0
    assert threshold == pytest.approx(30.0)

    assert registry.previous_version(mlcfg) == v1
    assert registry.promote(mlcfg, registry.previous_version(mlcfg)) == v2
    model, threshold = registry.load_serving_model(mlcfg)
    assert model.predict(np.zeros((1, 1)))[0] == 1.0       # the job now serves v1
    assert threshold == pytest.approx(15.0)                # with v1's own alert threshold


def test_no_rollback_below_the_first_version(mlcfg):
    v1 = registry.register(mlcfg, logged_run(1.0), LINEAGE, metrics(10.0))
    registry.promote(mlcfg, v1)
    with pytest.raises(ValueError, match="nothing to roll back"):
        registry.previous_version(mlcfg)
