"""Smoke test after a deploy: start one run of the job and wait for it to report success.

    python scripts/smoke.py bike-forecast

"A deploy that is not smoke-tested is a deploy you have not verified" (course Lab 4 CD). The
job writes state/last_run.json at the end of every run; this waits for a new run id there and
fails unless the run produced a forecast. Provider-neutral: storage and invoke are the adapter's.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter
from src import config

TIMEOUT_S = 420        # the job's own limit is 300 s, plus a cold start


def main() -> int:
    job = sys.argv[1] if len(sys.argv) > 1 else "bike-forecast"
    adapter = get_adapter(config.load())
    before = (adapter.read_json("state/last_run.json") or {}).get("run_id")
    print("started", adapter.invoke(job, {}))
    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        last = adapter.read_json("state/last_run.json") or {}
        if last.get("run_id") and last["run_id"] != before:
            print(last)
            if last["outcome"] == "failed":
                print("SMOKE FAIL  the run failed:", last.get("error"))
                return 1
            print(f"SMOKE PASS  run {last['run_id']}: {last['outcome']}, "
                  f"model version {last.get('model_version')}")
            return 0
        time.sleep(10)
    print(f"SMOKE FAIL  no run reported within {TIMEOUT_S} s")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
