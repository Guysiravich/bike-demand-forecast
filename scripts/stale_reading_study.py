"""How long may the model forecast from a stale weather reading? reports/stale-reading-study.md

    make stale-study

The drill found the original response — "same hour last week" as soon as the feed went stale —
was about twice as wrong as doing nothing. This measures the two side by side as the reading
ages: the feed freezes at 06:00 on every third day of the test period, for 48 hours, and each
1-hour-ahead forecast is scored against the rentals that happened. STALE_MODEL_MAX_AGE_MIN is
set from the result.

Caveat stated in the report: every freeze starts at 06:00, so the age of the reading and the
time of day move together; a row is "hours 10-12 after a 06:00 freeze", i.e. the evening peak.
"""
from __future__ import annotations

import dataclasses
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from cloudlayer.local import LocalAdapter
from src import config, data, registry
from src.simulation import simulate

BUCKETS = ((1, 3), (4, 6), (7, 9), (10, 12), (13, 18), (19, 24), (25, 36), (37, 48))


def main() -> int:
    base = config.load(strict=False)
    raw = data.load_raw(base.raw_path)
    world, holidays = data.hourly(raw), data.holidays(raw)
    model, _, version = registry.load_serving_model(base)
    starts = pd.date_range("2012-10-01", "2012-12-20", freq="3D") + pd.Timedelta(hours=6)
    modes = {
        "stale model": {"weather_max_age_min": 10**6, "stale_model_max_age_min": 10**6},
        "baseline": {"stale_model_max_age_min": base.weather_max_age_min},
    }
    by_age: dict[str, dict[int, list[float]]] = {m: defaultdict(list) for m in modes}
    store = config.REPO_ROOT / ".local-store" / "stale-study"
    for start in starts:
        for label, overrides in modes.items():
            shutil.rmtree(store, ignore_errors=True)
            cfg = dataclasses.replace(base, blob_uri=str(store), **overrides)
            results = simulate(LocalAdapter(cfg), cfg, world, model, holidays, start, 50, 1)
            for r in results[2:]:
                error = r["signals"]["abs_error_1h"]
                if error is not None:
                    # scored at tick t: the forecast issued at t-1, from the tick-0 reading
                    by_age[label][r["tick"] - 1].append(error)

    lines = ["# Stale reading study", "",
             f"Model version {version}; {len(starts)} freezes at 06:00, every third day of the "
             "test period, 48 hours each. Mean 1-hour-ahead error, rentals per hour.", "",
             "| Age of the reading (h) | Model on the stale reading | Same hour last week | n |",
             "|---|---|---|---|"]
    for lo, hi in BUCKETS:
        stale = [e for a in range(lo, hi + 1) for e in by_age["stale model"][a]]
        last_week = [e for a in range(lo, hi + 1) for e in by_age["baseline"][a]]
        lines.append(f"| {lo}-{hi} | {sum(stale) / len(stale):.1f} | "
                     f"{sum(last_week) / len(last_week):.1f} | {len(stale)} |")
    lines += ["", "Every freeze starts at 06:00, so age and time of day move together: hours "
              "10-12 are the evening peak, 13-24 the night."]
    out = base.reports_dir / "stale-reading-study.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
