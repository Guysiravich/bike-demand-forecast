"""The hourly job: forecast the next 24 hours of rentals, or fall back and say so.

    python -m src.forecast            # one run, at the simulated clock's current time

One run:
  1. read the clock and the latest weather reading
  2. measure the reading: valid? how old? identical to the last run's?
  3. if the weather can be trusted, score the model; if not, use the same hour last week
     and mark every row `degraded` — rolling the model back would not help, the model is
     not what is wrong
  4. score the previous run's 1-hour-ahead forecast against what was actually rented
  5. write forecasts/latest.json, emit the signals as metrics, evaluate the alert rules
"""
from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd

from cloudlayer.base import CloudAdapter
from src import baseline, monitor
from src.config import Config
from src.features import FEATURES, inference_frame
from src.feeder import validate_reading

ROLLING_WINDOW = 6          # runs in the rolling 1-hour-ahead error


def _values_fingerprint(weather: dict | None) -> str | None:
    # Values only, not the timestamp: the proposal's first signal is "the weather values stop
    # changing", which also catches a feed that freezes the values but keeps stamping them
    # with a fresh time. The price is that real weather can repeat by chance; how often it
    # does over two years is measured in reports/feed-false-alarms.md.
    return json.dumps(weather.get("values"), sort_keys=True) if weather else None


def _repeat_count(state: dict | None, weather: dict | None) -> int:
    """How many consecutive runs have now received exactly these weather values."""
    fingerprint = _values_fingerprint(weather)
    if fingerprint is None:
        return (state or {}).get("repeat_count", 0) + 1
    if state and state.get("fingerprint") == fingerprint:
        return state.get("repeat_count", 1) + 1
    return 1


def run_once(adapter: CloudAdapter, cfg: Config, model: Any, history: pd.Series,
             holiday_dates: set[pd.Timestamp], mae_threshold: float | None = None) -> dict:
    started = time.perf_counter()
    clock = adapter.read_json("clock.json")
    if clock is None:
        raise RuntimeError("no simulated clock yet: run the feeder first")
    now = pd.Timestamp(clock["sim_time"])

    # --- 1-2. the weather reading and what we know about it --------------------------------
    weather = adapter.read_json("weather/latest.json")
    feed_state = adapter.read_json("state/feed.json")
    repeat = _repeat_count(feed_state, weather)
    problems = validate_reading(weather["values"]) if weather else ["no reading has arrived"]
    age_min = ((now - pd.Timestamp(weather["observed_at"])).total_seconds() / 60
               if weather else float("inf"))
    adapter.write_json("state/feed.json", {"fingerprint": _values_fingerprint(weather),
                                           "repeat_count": repeat})

    # --- 4. yesterday's promise against today's rentals ------------------------------------
    previous = adapter.read_json("state/last_forecast.json")
    abs_error = None
    if previous:
        promised = {row["target_time"]: row["forecast"] for row in previous["rows"]}
        actual = history.get(now)
        if now.isoformat() in promised and actual is not None and pd.notna(actual):
            abs_error = abs(promised[now.isoformat()] - float(actual))
    errors = (adapter.read_json("state/errors.json") or {"recent": []})["recent"]
    if abs_error is not None:
        errors = (errors + [abs_error])[-ROLLING_WINDOW:]
        adapter.write_json("state/errors.json", {"recent": errors})
    rolling = sum(errors) / len(errors) if errors else None

    signals = monitor.Signals(
        sim_time=now.isoformat(), weather_age_min=age_min, weather_repeat_count=repeat,
        weather_valid=not problems, abs_error_1h=abs_error, rolling_mae_1h=rolling,
        job_duration_s=0.0, degraded=False)
    reasons = monitor.degraded_reasons(signals, cfg)
    signals.degraded = bool(reasons)

    # --- 3. forecast, or fall back ----------------------------------------------------------
    horizons = range(1, cfg.forecast_horizon_h + 1)
    target_times = pd.DatetimeIndex([now + pd.Timedelta(hours=h) for h in horizons])
    if signals.degraded:
        values = baseline.same_hour_last_week(history[history.index <= now], target_times)
        source = "baseline: same hour last week"
    else:
        rows = inference_frame(history, weather["values"], now, holiday_dates, horizons)
        values = [max(0.0, float(v)) for v in model.predict(rows[FEATURES])]
        source = "model"

    output = {
        "issued_at": now.isoformat(),
        "status": "degraded" if signals.degraded else "ok",
        "reasons": reasons,
        "source": source,
        "weather_observed_at": weather["observed_at"] if weather else None,
        "rows": [{"target_time": t.isoformat(), "forecast": round(v, 1)}
                 for t, v in zip(target_times, values, strict=True)],
    }
    adapter.write_json(f"forecasts/{now:%Y%m%dT%H}.json", output)
    adapter.write_json("forecasts/latest.json", output)
    adapter.write_json("state/last_forecast.json", output)

    # --- 5. signals out, alerts evaluated ---------------------------------------------------
    signals.job_duration_s = time.perf_counter() - started
    fired = monitor.alerts(signals, cfg, mae_threshold)
    for name, value in (("weather_age_min", signals.weather_age_min),
                        ("weather_repeat_count", signals.weather_repeat_count),
                        ("degraded", int(signals.degraded)),
                        ("job_duration_s", signals.job_duration_s),
                        ("alerts_fired", len(fired))):
        adapter.emit_metric(name, float(value) if value != float("inf") else 1e9)
    if signals.rolling_mae_1h is not None:
        adapter.emit_metric("rolling_mae_1h", signals.rolling_mae_1h)
    if fired:
        adapter.write_json(f"alerts/{now:%Y%m%dT%H}.json", {"sim_time": now.isoformat(),
                                                            "alerts": fired})
    return {"signals": signals.as_dict(), "status": output["status"], "alerts": fired,
            "source": source}


def main() -> int:
    """One hourly run against the configured store, model and rental ledger."""
    from cloudlayer.factory import get_adapter
    from src import config, data, registry

    cfg = config.load()
    adapter = get_adapter(cfg)
    raw = data.load_raw(cfg.raw_path)
    clock = adapter.read_json("clock.json")
    now = pd.Timestamp(clock["sim_time"]) if clock else None
    series = data.hourly(raw)["cnt"]
    history = series[series.index <= now] if now is not None else series
    model, mae_threshold = registry.load_serving_model(cfg)
    result = run_once(adapter, cfg, model, history, data.holidays(raw), mae_threshold)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
