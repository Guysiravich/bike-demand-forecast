"""Run the service against the simulated clock, locally, and print what it saw.

    python scripts/simulate.py --ticks 12                      # a normal half day
    python scripts/simulate.py --ticks 12 --freeze-at 3        # the planned failure
    python scripts/simulate.py --ticks 12 --freeze-at 3 --unfreeze-at 8

Uses the registered model (MODEL_VERSION or the `champion` alias) and a fresh local store,
so each run starts clean. Nothing here touches a cloud account.
"""
from __future__ import annotations

import argparse
import dataclasses
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from cloudlayer.local import LocalAdapter
from src import config, data, registry
from src.simulation import simulate, table


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2012-10-08T00:00",
                    help="first simulated hour, inside the test period")
    ap.add_argument("--ticks", type=int, default=12)
    ap.add_argument("--freeze-at", type=int, default=None)
    ap.add_argument("--unfreeze-at", type=int, default=None)
    ap.add_argument("--store", type=Path, default=config.REPO_ROOT / ".local-store" / "sim")
    args = ap.parse_args()

    shutil.rmtree(args.store, ignore_errors=True)
    cfg = dataclasses.replace(config.load(), provider="local", store_uri=str(args.store))
    adapter = LocalAdapter(cfg)
    raw = data.load_raw(cfg.raw_path)
    model, threshold = registry.load_serving_model(cfg)
    results = simulate(adapter, cfg, data.hourly(raw), model, data.holidays(raw),
                       pd.Timestamp(args.start), args.ticks, args.freeze_at, args.unfreeze_at,
                       threshold)
    print(table(results))
    first_alert = next((r for r in results if r["alerts"]), None)
    if args.freeze_at is not None:
        if first_alert:
            print(f"\nfrozen at tick {args.freeze_at}; first alert at tick {first_alert['tick']} "
                  f"({first_alert['tick'] - args.freeze_at} ticks later)")
        else:
            print(f"\nfrozen at tick {args.freeze_at}; NO ALERT FIRED")
            return 1
    print(f"store: {args.store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
