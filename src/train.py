"""Training entry point.

Run locally:      python -m src.train --max-leaf-nodes 31
Run in Docker:    make reproduce
Run managed:      make train-remote

Every run logs: all hyperparameters, the seed, validation AND test metrics separately, the
data fingerprint and DVC version, and the Git commit (Lab 1, Task 5). A metric that cannot be
traced to code and data is not evidence of anything. Registration is a separate step,
`make register RUN_ID=<id>` (Lab 2, Task 4).

Model accuracy carries no marks in this project (project brief); the model is deliberately
plain. It is reported against the baseline it falls back to, "same hour last week".
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

from src import config, data, seeds
from src.features import FEATURES, training_frame

# skops will only rebuild the types named here (course Lab 3: an untrusted type in a
# registered model made the serving container refuse to load it). Filled from the first
# training run's report of what the model contains.
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
        # Inside a container the image has no .git (.dockerignore); a managed job's
        # submitter passes the commit it built from.
        return os.environ.get("GIT_COMMIT", "unknown")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bike demand — reproducible training")
    p.add_argument("--learning-rate", type=float, default=0.05)
    p.add_argument("--max-iter", type=int, default=300)
    p.add_argument("--max-leaf-nodes", type=int, default=31)
    p.add_argument("--min-samples-leaf", type=int, default=40)
    p.add_argument("--seed", type=int, default=seeds.DEFAULT_SEED)
    p.add_argument("--experiment", default="bike-demand")
    p.add_argument("--run-name", default=None)
    p.add_argument("--metrics-out", type=Path, default=None,
                   help="Write final metrics as JSON. Used by `make verify` and `make register`.")
    return p.parse_args()


def scores(truth: pd.Series, predicted: np.ndarray) -> dict[str, float]:
    return {"mae": float(mean_absolute_error(truth, predicted)),
            "rmse": float(np.sqrt(mean_squared_error(truth, predicted)))}


def baseline_predictions(frame: pd.DataFrame) -> np.ndarray:
    """Same hour last week, else same hour yesterday — src/baseline.py, vectorised."""
    return frame["cnt_lag168"].fillna(frame["cnt_lag24"]).fillna(frame["cnt_now"]).to_numpy()


def evaluate(frame: pd.DataFrame, predicted: np.ndarray, prefix: str) -> dict[str, float]:
    out = {f"{prefix}_{name}": value for name, value in scores(frame["cnt"], predicted).items()}
    for h in (1, 6, 24):
        mask = (frame["horizon"] == h).to_numpy()
        out[f"{prefix}_mae_h{h}"] = float(mean_absolute_error(frame["cnt"][mask], predicted[mask]))
    return out


def main() -> None:
    args = parse_args()
    cfg = config.load(strict=False)
    seed = seeds.set_all(args.seed)

    raw = data.load_raw(cfg.raw_path)
    problems = data.validate(raw)
    if problems:
        raise SystemExit("data contract failed:\n  " + "\n  ".join(problems))

    frame = training_frame(raw, range(1, cfg.forecast_horizon_h + 1))
    train, val, test = data.split_by_time(frame)
    params = {"loss": "poisson", "learning_rate": args.learning_rate, "max_iter": args.max_iter,
              "max_leaf_nodes": args.max_leaf_nodes, "min_samples_leaf": args.min_samples_leaf}
    model = HistGradientBoostingRegressor(random_state=seed, **params)
    model.fit(train[FEATURES], train["cnt"])

    metrics: dict[str, float] = {}
    for name, split in (("val", val), ("test", test)):
        metrics |= evaluate(split, np.clip(model.predict(split[FEATURES]), 0, None), name)
        metrics |= evaluate(split, baseline_predictions(split), f"{name}_baseline")
    # The accuracy alert fires when the live 1-hour error runs well above what validation
    # promised. 1.5x is a starting point; reports/failure-drill.md checks it against the
    # simulation's own noise.
    metrics["mae_alert_threshold"] = 1.5 * metrics["val_mae_h1"]

    lineage = {
        "git_commit": git_commit(),
        "data_fingerprint": data.fingerprint(cfg.raw_path),
        "data_version": data.dvc_hash(cfg.raw_path.with_suffix(".csv.dvc")),
        "training_job_id": os.environ.get("TRAINING_JOB_ID", "local"),
        "image_digest": os.environ.get("IMAGE_DIGEST", "local"),
    }

    import mlflow
    import mlflow.sklearn

    mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    mlflow.set_experiment(args.experiment)
    with mlflow.start_run(run_name=args.run_name) as run:
        mlflow.log_params({**params, "seed": seed, "features": ",".join(FEATURES),
                           "rows_train": len(train), "rows_val": len(val), "rows_test": len(test)})
        mlflow.log_metrics(metrics)
        mlflow.set_tags(lineage)
        mlflow.sklearn.log_model(model, name="model", skops_trusted_types=TRUSTED_TYPES)
        run_id = run.info.run_id

    result = {"run_id": run_id, **metrics}
    print(json.dumps({"run_id": run_id, "seed": seed, "val_mae": round(metrics["val_mae"], 4),
                      "test_mae": round(metrics["test_mae"], 4),
                      "test_baseline_mae": round(metrics["test_baseline_mae"], 4),
                      **lineage}, indent=2))
    if args.metrics_out:
        args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_out.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
