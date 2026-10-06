"""How often does REAL weather repeat for N hours in a row? Why the repeat count only charts.

    python scripts/feed_false_alarms.py

The repeat rule compares weather values only, so that it also catches a feed that freezes the
values but keeps stamping a fresh time. Real weather can repeat by chance — the source rounds
its readings — and every such run would page someone for nothing. This counts those runs over
the whole dataset, so the threshold is a measured choice rather than a guess.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, data


def main() -> int:
    cfg = config.load()
    raw = data.load_raw(cfg.raw_path)
    series = data.hourly(raw)[data.WEATHER]
    identical = (series == series.shift(1)).all(axis=1) & series.notna().all(axis=1)
    run = 0
    runs: list[int] = []
    for same in identical:
        if same:
            run += 1
        elif run:
            runs.append(run + 1)      # a run of k "same as before" means k+1 equal readings
            run = 0
    hours = len(series)
    lines = ["# How often real weather repeats", "",
             f"Hours in the data: {hours:,} (2011-01-01 to 2012-12-31, gaps included).", "",
             "| Consecutive identical readings | Occurrences | Alerts per year at this threshold |",
             "|---|---|---|"]
    for n in range(2, 7):
        count = sum(1 for r in runs if r >= n)
        lines.append(f"| {n} or more | {count} | {count / 2:.1f} |")
    lines += ["", "Decision: the repeat count is charted, not paged. At 3 repeats it would page "
              "about 50 times a year on a healthy feed, and the age rule caught the frozen feed "
              "at the same tick with no false alarms."]
    text = "\n".join(lines) + "\n"
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    (cfg.reports_dir / "feed-false-alarms.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
