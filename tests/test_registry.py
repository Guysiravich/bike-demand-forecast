"""The bad-model response: registration refuses missing lineage, and a rollback moves the
alias — the one thing the hourly job reads — back to the previous version.

Uses a throwaway SQLite MLflow store, so it needs no server and no trained model.
"""
from __future__ import annotations

import dataclasses
import uuid

import mlflow
import mlflow.sklearn
import numpy as np
import pytest
from sklearn.dummy import DummyRegressor

from cloudlayer.local import LocalAdapter
from src import registry

LINEAGE = {"git_commit": "abc1234", "data_version": "d50bd5a6", "data_fingerprint": "e03de4ee",
           "training_job_id": "local", "image_digest": "local"}


@pytest.fixture(scope="module")
def tracking_uri(tmp_path_factory):
    # One store for the module: creating and migrating an MLflow database takes ~40 s.
    uri = f"sqlite:///{(tmp_path_factory.mktemp('mlflow') / 'mlflow.db').as_posix()}"
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("test")
    return uri


@pytest.fixture
def mlcfg(cfg, tracking_uri):
    # A model name per test, so versions and aliases never leak between tests.
    mlflow.set_tracking_uri(tracking_uri)
    return dataclasses.replace(cfg, mlflow_tracking_uri=tracking_uri,
                               model_registry_name=f"bike-test-{uuid.uuid4().hex[:8]}",
                               model_version="", model_alias="production")


def logged_run(constant: float, tags: dict | None = None) -> str:
    model = DummyRegressor(strategy="constant", constant=constant).fit([[0]], [constant])
    with mlflow.start_run() as run:
        mlflow.log_param("seed", 1)
        mlflow.log_metrics({"val_mae": 10 * constant, "test_mae": 11 * constant,
                            "mae_alert_threshold": 15 * constant})
        mlflow.set_tags(LINEAGE if tags is None else tags)
        mlflow.sklearn.log_model(model, name="model")
    return f"runs:/{run.info.run_id}/model"


def test_lineage_lands_on_the_version(mlcfg):
    name = mlcfg.model_registry_name
    version = LocalAdapter(mlcfg).register_model(logged_run(1.0), name)
    tags = registry._client(mlcfg).get_model_version(name, version).tags
    assert {*registry.LINEAGE_FIELDS} <= set(tags)
    assert tags["metric_val"] == "10.0" and tags["git_commit"] == "abc1234"


def test_register_refuses_missing_lineage(mlcfg):
    uri = logged_run(1.0, {**LINEAGE, "git_commit": "unknown"})
    with pytest.raises(ValueError, match="lineage"):
        registry.register_run(mlcfg, uri, mlcfg.model_registry_name)


def test_rollback_serves_the_previous_version(mlcfg):
    v1 = registry.register_run(mlcfg, logged_run(1.0), mlcfg.model_registry_name)
    v2 = registry.register_run(mlcfg, logged_run(2.0), mlcfg.model_registry_name)
    registry.promote(mlcfg, v2)
    model, threshold, version = registry.load_serving_model(mlcfg)
    assert (version, model.predict(np.zeros((1, 1)))[0]) == (v2, 2.0)
    assert threshold == pytest.approx(30.0)

    assert registry.previous_version(mlcfg) == v1
    assert registry.promote(mlcfg, registry.previous_version(mlcfg)) == v2
    model, threshold, version = registry.load_serving_model(mlcfg)
    assert (version, model.predict(np.zeros((1, 1)))[0]) == (v1, 1.0)   # the job serves v1
    assert threshold == pytest.approx(15.0)                             # with v1's threshold


def test_staging_and_production_move_independently(mlcfg):
    v1 = registry.register_run(mlcfg, logged_run(1.0), mlcfg.model_registry_name)
    v2 = registry.register_run(mlcfg, logged_run(2.0), mlcfg.model_registry_name)
    registry.promote(mlcfg, v1, "production")
    registry.promote(mlcfg, v2, "staging")
    assert registry.load_serving_model(mlcfg)[2] == v1


def test_no_rollback_below_the_first_version(mlcfg):
    v1 = registry.register_run(mlcfg, logged_run(1.0), mlcfg.model_registry_name)
    registry.promote(mlcfg, v1)
    with pytest.raises(ValueError, match="nothing to roll back"):
        registry.previous_version(mlcfg)
