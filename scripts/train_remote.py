"""Run training as a managed job on TRAINING_TARGET (course Lab 2, Task 1).

    python scripts/train_remote.py --image bike-train:<tag> [-- --max-leaf-nodes 63]

Uploads the dataset to BLOB_URI/data, pushes the image by digest, submits the job through the
adapter and waits for it. Provider-neutral: every cloud call goes through the adapter.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter
from src import config


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                          cwd=config.REPO_ROOT).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="local image tag built by `make image`")
    ap.add_argument("--module", default="src.train")
    ap.add_argument("--experiment", default="bike-demand")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="submit with uncommitted changes (lineage will not match the commit)")
    ap.add_argument("rest", nargs=argparse.REMAINDER, help="arguments after -- go to the module")
    args = ap.parse_args()

    cfg = config.load()
    if not cfg.training_target:
        print("TRAINING_TARGET is empty in cloud.env")
        return 1
    if git("status", "--porcelain") and not args.allow_dirty:
        print("Working tree has uncommitted changes; the job's git_commit would not describe "
              "the code it ran. Commit first, or pass --allow-dirty.")
        return 1

    adapter = get_adapter(cfg)
    print("uploading dataset to BLOB_URI/data ...")
    for rel in ("data/raw/hour.csv", "data/raw/hour.csv.dvc"):
        print("  ", adapter.upload(str(config.REPO_ROOT / rel), rel))
    print("pushing image ...")
    image_ref = adapter.push_image(args.image)
    print("  ", image_ref)

    module_args = args.rest[1:] if args.rest[:1] == ["--"] else args.rest
    job_args = {
        "module": args.module,
        "arguments": [*module_args, "--metrics-out", "{output}/metrics.json"],
        "experiment": args.experiment,
        "env": {"CLOUD_PROVIDER": "local",       # the job reads /app/data; no storage calls
                "MLFLOW_TRACKING_URI": cfg.mlflow_tracking_uri,
                "MODEL_REGISTRY_NAME": cfg.model_registry_name,
                "GIT_COMMIT": git("rev-parse", "HEAD")},
    }
    # The tracking server's password reaches the job at submission time, from the local
    # cloud.env; never in Git or an image layer (course Lab 2 limitation, stated there too).
    for key in ("MLFLOW_TRACKING_USERNAME", "MLFLOW_TRACKING_PASSWORD"):
        if os.environ.get(key):
            job_args["env"][key] = os.environ[key]

    job_id = adapter.submit_training(image_ref, job_args)
    print("submitted:", job_id)
    result = adapter.wait_training(job_id)
    print(result)
    return 0 if result["status"] == "Completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
