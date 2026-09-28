"""The project brief's required test: if the weather feed repeats for three hours, the alert
must fire. It runs in CI and fails the build if detection ever stops working.

These tests drive the real feeder and the real hourly job against a synthetic world, so the
thing under test is the same code that runs in the cloud, not a copy of its logic.
"""
from __future__ import annotations

import pandas as pd

from src import data
from src.simulation import simulate

START = pd.Timestamp("2012-03-12T00:00")     # a week in, so same-hour-last-week exists


def run(adapter, cfg, raw, model, **kwargs):
    return simulate(adapter, cfg, data.hourly(raw), model, data.holidays(raw), START, **kwargs)


def feed_alerts(result):
    return [a for a in result["alerts"] if a.startswith("FEED")]


def test_normal_feed_raises_nothing(adapter, cfg, raw, model):
    results = run(adapter, cfg, raw, model, ticks=10)
    assert all(r["status"] == "ok" for r in results)
    assert not any(feed_alerts(r) for r in results)


def test_frozen_feed_alerts_within_three_hours(adapter, cfg, raw, model):
    freeze_at = 3
    results = run(adapter, cfg, raw, model, ticks=10, freeze_at=freeze_at)

    before = results[:freeze_at]
    assert not any(feed_alerts(r) for r in before), "false alarm before the feed froze"

    first = next(r for r in results if feed_alerts(r))
    # The last good reading arrived at tick freeze_at - 1. By tick freeze_at + 1 the job has
    # seen that reading three runs in a row — three hours — and the alert must be up.
    assert first["tick"] <= freeze_at + cfg.feed_repeat_alert - 2, first
    assert any("repeated" in a for a in feed_alerts(first))


def test_frozen_feed_switches_to_the_baseline_and_says_so(adapter, cfg, raw, model):
    results = run(adapter, cfg, raw, model, ticks=10, freeze_at=3)
    first_alert = next(x["tick"] for x in results if x["alerts"])
    after_alert = [r for r in results if r["tick"] >= first_alert]
    assert after_alert
    for result in after_alert:
        assert result["status"] == "degraded"
        assert result["source"].startswith("baseline")
    latest = adapter.read_json("forecasts/latest.json")
    assert latest["status"] == "degraded" and latest["reasons"]


def test_the_feed_recovering_clears_the_alert(adapter, cfg, raw, model):
    results = run(adapter, cfg, raw, model, ticks=12, freeze_at=3, unfreeze_at=7)
    assert results[-1]["status"] == "ok"
    assert not feed_alerts(results[-1])


def test_signals_reach_the_metric_stream(adapter, cfg, raw, model):
    run(adapter, cfg, raw, model, ticks=6, freeze_at=2)
    names = {m["name"] for m in adapter.metrics()}
    assert {"weather_age_min", "weather_repeat_count", "degraded", "alerts_fired"} <= names
    assert max(m["value"] for m in adapter.metrics() if m["name"] == "degraded") == 1.0
