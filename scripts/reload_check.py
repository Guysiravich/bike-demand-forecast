"""Prove the registered model reloads by version, from the registry (course Lab 2, Task 5).

    python scripts/reload_check.py --version 3

Models that cannot be reloaded six months later are the commonest form of dead work; the
cause is nearly always a serialization assumption. This one met it in practice: skops
refused HistGradientBoosting's trees until the type was trusted at log time (src/train.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mlflow
import mlflow.sklearn
import numpy as np

from src import config, data
from src.features import FEATURES, training_frame


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--rows", type=int, default=5)
    args = ap.parse_args()

    cfg = config.load(strict=False)
    mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    uri = f"models:/{cfg.model_registry_name}/{args.version}"
    print(f"loading {uri}")
    model = mlflow.sklearn.load_model(uri)

    _, _, test = data.split_by_time(training_frame(data.load_raw(cfg.raw_path)))
    sample = test[test["horizon"] == 1].head(args.rows)
    predicted = np.clip(model.predict(sample[FEATURES]), 0, None)
    for (_, row), p in zip(sample.iterrows(), predicted, strict=True):
        print(f"  {row['target_time']:%Y-%m-%d %H:%M}  forecast {p:6.1f}  actual {row['cnt']:6.0f}")
    print("\nPASS  model reloaded from the registry and scored rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
