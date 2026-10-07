"""Scheduled retraining (course Lab 5, Task 3): the whole pipeline, weekly, as an Azure ML job.

    make retrain-schedule            # create it: Sunday 02:00 UTC (pipeline/pipeline.yaml)
    make retrain-once                # one run now, same job as the schedule
    make retrain-unschedule          # delete it (make teardown LAB=capstone does this too)

The job runs scripts/run_pipeline.py in the training image: ingest, the data contract tests
(abort on failure), train, the gate, and register to `staging` only if the gate passes. It
never promotes to production: that stays a person's decision (README, "Promotion").

The tracking server must be running when the schedule fires; the job registers to it. While
the VM is deallocated between sessions, delete the schedule rather than let it fail weekly.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter
from src import config

NAME = "bike-retrain"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="local training image tag (carries pipeline/ and tests/)")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--once", action="store_true", help="submit one run now instead")
    args = ap.parse_args()

    cfg = config.load()
    adapter = get_adapter(cfg)
    if args.delete:
        print("deleted schedule", adapter.schedule(NAME, "", {}, ""))
        return 0
    if not args.image:
        ap.error("--image is required unless --delete")

    cron = yaml.safe_load((config.REPO_ROOT / "pipeline" / "pipeline.yaml").read_text())["schedule"]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True, cwd=config.REPO_ROOT).stdout.strip()
    image_ref = adapter.push_image(args.image)
    job = {
        "module": "scripts.run_pipeline",
        "display_name": "weekly retraining pipeline",
        "experiment": "bike-demand",
        "env": {"CLOUD_PROVIDER": "local",   # the steps read /app/data; the registry is MLflow
                "MLFLOW_TRACKING_URI": cfg.mlflow_tracking_uri,
                "MODEL_REGISTRY_NAME": cfg.model_registry_name,
                "GIT_COMMIT": commit},
    }
    # Same limitation the course's Lab 2 states: the tracking server's credentials are in the
    # job definition, readable by anyone with access to the workspace.
    for key in ("MLFLOW_TRACKING_USERNAME", "MLFLOW_TRACKING_PASSWORD"):
        if os.environ.get(key):
            job["env"][key] = os.environ[key]
    if args.once:
        job_id = adapter.submit_training(image_ref, job)
        print("submitted", job_id)
        print(adapter.wait_training(job_id))
        return 0
    print("schedule", adapter.schedule(NAME, image_ref, job, cron), "cron", cron, "UTC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
