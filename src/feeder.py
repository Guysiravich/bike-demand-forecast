"""The simulated world: a clock and a weather feed.

The data is from 2011-2012, so the service runs against a simulated clock. Each tick
advances the clock by one hour and publishes that hour's weather reading from the dataset —
unless the feed has been frozen, which is the planned failure. A frozen feed keeps
re-delivering the last reading: same values, same observation time, a fresh delivery time.
Nothing about it looks wrong from the inside.

Store layout (through the adapter, so the same code runs locally and in the cloud):
  clock.json                {"sim_time": ...}
  control/feed_mode.json    {"mode": "normal" | "frozen"}   ← flip this to break the feed
  weather/latest.json       {"observed_at", "delivered_at", "values": {...}}
"""
from __future__ import annotations

import json

import pandas as pd

from cloudlayer.base import CloudAdapter
from src.data import RANGES, WEATHER

MODES = ("normal", "frozen")


def validate_reading(values: dict) -> list[str]:
    """The weather part of the data contract, applied to a live reading."""
    problems = []
    for column in WEATHER:
        if column not in values:
            problems.append(f"missing {column}")
            continue
        try:
            value = float(values[column])
        except (TypeError, ValueError):
            problems.append(f"{column} is not a number: {values[column]!r}")
            continue
        low, high = RANGES[column]
        if not low <= value <= high:
            problems.append(f"{column}={value} outside [{low}, {high}]")
    extra = set(values) - set(WEATHER)
    if extra:
        problems.append(f"unexpected fields {sorted(extra)}")
    return problems


def set_mode(adapter: CloudAdapter, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"feed mode must be one of {MODES}, got {mode!r}")
    adapter.write_json("control/feed_mode.json", {"mode": mode})


def read_mode(adapter: CloudAdapter) -> str:
    """The feed mode from the control document. Anything that is not a known mode — a
    missing key, a typo, a number, a document that is not JSON at all — is read as
    "normal" and said so in the log, rather than crashing the feeder or freezing it."""
    try:
        control = adapter.read_json("control/feed_mode.json")
    except ValueError as exc:   # not JSON
        print(json.dumps({"event": "bad_control", "error": type(exc).__name__}), flush=True)
        return "normal"
    mode = control.get("mode") if isinstance(control, dict) else None
    if control is not None and mode not in MODES:
        print(json.dumps({"event": "bad_control", "mode": repr(mode)[:40]}), flush=True)
        return "normal"
    return mode or "normal"


def tick(adapter: CloudAdapter, world: pd.DataFrame, start: pd.Timestamp | None = None) -> dict:
    """Advance the clock one hour and deliver the feed. `world` is the hourly-indexed data.

    `start` initialises the clock on the first tick; later ticks ignore it.
    """
    clock = adapter.read_json("clock.json")
    if clock is None:
        if start is None:
            raise RuntimeError("clock not initialised: pass start= on the first tick")
        sim_time = pd.Timestamp(start)
    else:
        sim_time = pd.Timestamp(clock["sim_time"]) + pd.Timedelta(hours=1)
    adapter.write_json("clock.json", {"sim_time": sim_time.isoformat()})

    mode = read_mode(adapter)
    latest = adapter.read_json("weather/latest.json")

    if mode == "frozen" and latest is not None:
        latest["delivered_at"] = sim_time.isoformat()      # still arriving, never changing
        adapter.write_json("weather/latest.json", latest)
        return {"sim_time": sim_time, "mode": mode, "published": False}

    if sim_time in world.index and world.loc[sim_time, WEATHER].notna().all():
        values = {c: float(world.loc[sim_time, c]) for c in WEATHER}
        adapter.write_json("weather/latest.json", {
            "observed_at": sim_time.isoformat(),
            "delivered_at": sim_time.isoformat(),
            "values": values,
        })
        return {"sim_time": sim_time, "mode": mode, "published": True}
    # The source has no row for this hour: no reading is published, and its age grows.
    return {"sim_time": sim_time, "mode": mode, "published": False}


def main() -> int:
    """python -m src.feeder                 one tick: advance the clock, deliver the feed
       python -m src.feeder --mode frozen   flip the feed (the planned failure) — make freeze
       python -m src.feeder --mode normal   and back — make unfreeze

    The scheduled feeder job runs the first form; the demo runs the other two by hand.
    """
    import argparse

    from cloudlayer.factory import get_adapter
    from src import config, data

    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=MODES, default=None)
    ap.add_argument("--start", default="2012-10-08T00:00",
                    help="first simulated hour, inside the test period; used once")
    args = ap.parse_args()

    cfg = config.load()
    adapter = get_adapter(cfg)
    if args.mode:
        set_mode(adapter, args.mode)
        print(json.dumps({"event": "feed_mode", "mode": args.mode}), flush=True)
        return 0
    if not cfg.raw_path.exists():
        adapter.download(adapter.object_uri("data/raw/hour.csv"), str(cfg.raw_path))
    world = data.hourly(data.load_raw(cfg.raw_path))
    fed = tick(adapter, world, start=pd.Timestamp(args.start))
    print(json.dumps({"event": "tick", **fed}, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
