"""Run the feeder and the hourly job together against the simulated clock.

This is the demo, and it is also what the CI test drives: freeze the feed at one tick, and
the alert must fire within `feed_repeat_alert` ticks, with every forecast after that marked
degraded. If the detection ever stops working, the test — and the build — fail.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from cloudlayer.base import CloudAdapter
from src import feeder, forecast
from src.config import Config


def simulate(adapter: CloudAdapter, cfg: Config, world: pd.DataFrame, model: Any,
             holiday_dates: set[pd.Timestamp], start: pd.Timestamp, ticks: int,
             freeze_at: int | None = None, unfreeze_at: int | None = None,
             mae_threshold: float | None = None) -> list[dict]:
    """`world` is the hourly-indexed dataset. Tick numbers count from 0."""
    feeder.set_mode(adapter, "normal")
    results = []
    for tick in range(ticks):
        if freeze_at is not None and tick == freeze_at:
            feeder.set_mode(adapter, "frozen")
        if unfreeze_at is not None and tick == unfreeze_at:
            feeder.set_mode(adapter, "normal")
        fed = feeder.tick(adapter, world, start=start)
        now = pd.Timestamp(fed["sim_time"])
        history = world["cnt"][world.index <= now]
        result = forecast.run_once(adapter, cfg, model, history, holiday_dates, mae_threshold)
        results.append({"tick": tick, "sim_time": now, "feed": fed["mode"], **result})
    return results


def table(results: list[dict]) -> str:
    lines = [f"{'tick':>4}  {'sim time':<16}  {'feed':<6}  {'age min':>7}  {'repeat':>6}  "
             f"{'status':<8}  {'mae 1h':>7}  alerts"]
    for r in results:
        s = r["signals"]
        age = "none" if s["weather_age_min"] == float("inf") else f"{s['weather_age_min']:.0f}"
        mae = "" if s["rolling_mae_1h"] is None else f"{s['rolling_mae_1h']:.1f}"
        lines.append(f"{r['tick']:>4}  {r['sim_time']:%Y-%m-%d %H:%M}  {r['feed']:<6}  {age:>7}  "
                     f"{s['weather_repeat_count']:>6}  {r['status']:<8}  {mae:>7}  "
                     f"{'; '.join(r['alerts'])}")
    return "\n".join(lines)
