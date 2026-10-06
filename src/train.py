"""Train the demand model, compare it with the baseline it must beat, and track the run.

    python -m src.train                 # train, evaluate, log to MLflow
    python -m src.train --register      # ... and register a version with its lineage

Model accuracy carries no marks in this project (project brief); the model is deliberately
plain. What matters is that the run is reproducible and traceable: fixed seed, time-ordered
split, data fingerprint and commit logged, lineage copied onto the registered version.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from src import config, data
from src.features import FEATURES, training_frame

HYPERPARAMETERS = {"loss": "poisson", "max_iter": 300, "learning_rate": 0.05,
                   "max_leaf_nodes": 31, "min_samples_leaf": 40}

# skops will only rebuild the types named here (see Lab 3: an untrusted type in a registered
# model made the serving container refuse to load it). Filled from the first training run's
# report of what the model contains; every entry is a scikit-learn internal we built ourselves.
#   TreePredictor  the fitted trees. skops flags it because a crafted file can hold
#                  out-of-range node indices; ours come from our own fit, never a download.
TRUSTED_TYPES: list[str] = [
    "sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor",
]


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True, cwd=config.REPO_ROOT).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return os.environ.get("GIT_COMMIT", "unknown")


def dvc_md5(dvc_file: Path) -> str:
    if not dvc_file.exists():
        return "unversioned"
    for line in dvc_file.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("- md5:") or line.strip().startswith("md5:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def scores(truth: pd.Series, predicted: np.ndarray) -> dict[str, float]:
    return {"mae": float(mean_absolute_error(truth, predicted)),
            "rmse": float(np.sqrt(mean_squared_error(truth, predicted)))}


def baseline_predictions(frame: pd.DataFrame) -> np.ndarray:
    """Same hour last week, else same hour yesterday — src/baseline.py, vectorised."""
    return frame["cnt_lag168"].fillna(frame["cnt_lag24"]).fillna(frame["cnt_now"]).to_numpy()


def evaluate(frame: pd.DataFrame, predicted: np.ndarray, label: str) -> dict[str, float]:
    out = {}
    for name, value in scores(frame["cnt"], predicted).items():
        out[f"{label}_{name}"] = value
    for h in (1, 6, 24):
        mask = (frame["horizon"] == h).to_numpy()
        out[f"{label}_mae_h{h}"] = float(mean_absolute_error(frame["cnt"][mask], predicted[mask]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--experiment", default="bike-demand")
    args = ap.parse_args()

    cfg = config.load()
    raw = data.load_raw(cfg.raw_path)
    problems = data.validate(raw)
    if problems:
        raise SystemExit("data contract failed:\n  " + "\n  ".join(problems))

    frame = training_frame(raw, range(1, cfg.forecast_horizon_h + 1))
    train, val, test = data.split_by_time(frame)
    model = HistGradientBoostingRegressor(random_state=cfg.seed, **HYPERPARAMETERS)
    model.fit(train[FEATURES], train["cnt"])

    metrics: dict[str, float] = {}
    for split_name, split in (("val", val), ("test", test)):
        metrics |= evaluate(split, np.clip(model.predict(split[FEATURES]), 0, None),
                            f"{split_name}_model")
        metrics |= evaluate(split, baseline_predictions(split), f"{split_name}_baseline")
    # The accuracy alert fires when the live 1-hour error runs well above what validation
    # promised. 1.5x is a starting point, to be revisited against the simulation's own noise.
    metrics["mae_alert_threshold"] = 1.5 * metrics["val_model_mae_h1"]

    lineage = {
        "git_commit": git_commit(),
        "data_fingerprint": data.fingerprint(cfg.raw_path),
        "data_version": dvc_md5(cfg.raw_path.with_suffix(".csv.dvc")),
        "seed": str(cfg.seed),
        "training_job_id": os.environ.get("TRAINING_JOB_ID", "local"),
        "image_digest": os.environ.get("IMAGE_DIGEST", "local"),
    }

    import mlflow
    import mlflow.sklearn

    mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    mlflow.set_experiment(args.experiment)
    with mlflow.start_run() as run:
        mlflow.log_params({**HYPERPARAMETERS, "features": ",".join(FEATURES),
                           "rows_train": len(train), "rows_val": len(val), "rows_test": len(test)})
        mlflow.log_metrics(metrics)
        mlflow.set_tags(lineage)
        mlflow.sklearn.log_model(model, name="model", skops_trusted_types=TRUSTED_TYPES or None)
        run_id = run.info.run_id

    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    report = {"run_id": run_id, "metrics": metrics, "lineage": lineage}
    report_path = cfg.reports_dir / "train_metrics.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if args.register:
        from src import registry
        version = registry.register(cfg, run_id, lineage, metrics)
        print(f"registered {cfg.model_name} version {version}")
        # The first version has nothing to compete with, so it serves. After that a new
        # version serves only when someone runs `make promote VERSION=...`.
        if version == "1":
            registry.promote(cfg, version)
            print(f"{cfg.model_name}: champion -> {version} (first version)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
