"""Deploy the batch service: push the job image, create or update the two scheduled jobs.

    make deploy ALIAS=production            # what the hourly job serves
    make run-now JOB=bike-forecast          # one execution now (the demo's "next tick")

Two jobs from one image (course Lab 3, adapted to batch serving):
  bike-feeder    advances the simulated clock and delivers the weather reading
  bike-forecast  scores the next 24 hours with the version the alias names

The forecast job resolves the alias at the start of every run, so promotion and rollback
take effect on the next tick without a redeploy. Provider-neutral: every call is the adapter's.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter
from src import config

JOBS = {"bike-feeder": "src.feeder", "bike-forecast": "src.forecast"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="local job image tag to push (default: JOB_IMAGE as set)")
    ap.add_argument("--alias", default=None, help="registry alias the forecast job serves")
    ap.add_argument("--instance", default="0.5/1.0Gi", help="<cpu>/<memory> per execution")
    ap.add_argument("--run-now", metavar="JOB", help="start one execution of JOB and exit")
    args = ap.parse_args()

    cfg = config.load()
    adapter = get_adapter(cfg)
    if args.run_now:
        print(adapter.invoke(args.run_now, {}))
        return 0

    # The ledger of actual rentals is the simulated world; the jobs read it from storage.
    print("uploading data ...")
    print("  ", adapter.upload(str(cfg.raw_path), "data/raw/hour.csv"))
    if args.image:
        print("pushing job image ...")
        os.environ["JOB_IMAGE"] = adapter.push_image(args.image)
        print("  ", os.environ["JOB_IMAGE"])
    alias = args.alias or cfg.model_alias
    for name, module in JOBS.items():
        os.environ["JOB_MODULE"] = module
        model_ref = f"models:/{cfg.model_registry_name}@{alias}" if module == "src.forecast" else ""
        print(f"deploying {name} ({module}) ...")
        print("  ", adapter.deploy(model_ref, name, args.instance))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
