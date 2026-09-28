"""The hourly job's handling of bad input — including input nobody planned for. The instructor
sends unexpected input during the demo; the job must refuse it clearly, not crash."""
from __future__ import annotations

import pandas as pd

from src import baseline, data, forecast


def setup_world(adapter, raw, values, observed_at="2012-03-12T00:00", now="2012-03-12T00:00"):
    adapter.write_json("clock.json", {"sim_time": now})
    adapter.write_json("weather/latest.json", {"observed_at": observed_at, "delivered_at": now,
                                               "values": values})
    series = data.hourly(raw)["cnt"]
    return series[series.index <= pd.Timestamp(now)]


def good_values(raw):
    row = data.hourly(raw).loc[pd.Timestamp("2012-03-12T00:00")]
    return {c: float(row[c]) for c in data.WEATHER}


def test_a_good_reading_is_served_by_the_model(adapter, cfg, raw, model):
    history = setup_world(adapter, raw, good_values(raw))
    result = forecast.run_once(adapter, cfg, model, history, data.holidays(raw))
    assert result["status"] == "ok" and result["source"] == "model"
    assert len(adapter.read_json("forecasts/latest.json")["rows"]) == 24


def test_an_impossible_reading_degrades_instead_of_crashing(adapter, cfg, raw, model):
    values = {**good_values(raw), "temp": 5.0}
    history = setup_world(adapter, raw, values)
    result = forecast.run_once(adapter, cfg, model, history, data.holidays(raw))
    assert result["status"] == "degraded"
    assert any("validation" in a for a in result["alerts"])


def test_a_malformed_reading_degrades_instead_of_crashing(adapter, cfg, raw, model):
    values = {**good_values(raw), "hum": "wet", "surprise": 1}
    history = setup_world(adapter, raw, values)
    result = forecast.run_once(adapter, cfg, model, history, data.holidays(raw))
    assert result["status"] == "degraded"


def test_an_old_reading_degrades(adapter, cfg, raw, model):
    history = setup_world(adapter, raw, good_values(raw), observed_at="2012-03-11T20:00")
    result = forecast.run_once(adapter, cfg, model, history, data.holidays(raw))
    assert result["status"] == "degraded"
    assert any("min old" in r for r in adapter.read_json("forecasts/latest.json")["reasons"])


def test_the_baseline_is_same_hour_last_week(raw):
    series = data.hourly(raw)["cnt"]
    targets = pd.DatetimeIndex([pd.Timestamp("2012-03-15T09:00")])
    expected = series[pd.Timestamp("2012-03-08T09:00")]
    assert baseline.same_hour_last_week(series, targets) == [float(expected)]


def test_the_baseline_falls_back_when_last_week_is_missing(raw):
    series = data.hourly(raw)["cnt"].copy()
    series[pd.Timestamp("2012-03-08T09:00")] = float("nan")
    targets = pd.DatetimeIndex([pd.Timestamp("2012-03-15T09:00")])
    yesterday = float(series[pd.Timestamp("2012-03-14T09:00")])
    assert baseline.same_hour_last_week(series, targets) == [yesterday]
