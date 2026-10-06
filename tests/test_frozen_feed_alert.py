"""The project brief's required test, and the dotted edge back from the drill.

1. Detection: freeze the feed and the age alert must fire on the first stale tick. If detection
   ever stops working, this fails the build.
2. Response: what the drill revealed (reports/failure-drill.md). Falling straight back to "same
   hour last week" was about twice as wrong as doing nothing, so the job now keeps the model on
   the last reading until STALE_MODEL_MAX_AGE_MIN. The last test here holds that line on the
   real data: the designed response may not be worse than doing nothing.

The synthetic-world tests drive the real feeder and the real hourly job, so the thing under test
is the code that runs in the cloud, not a copy of its logic.
"""
from __future__ import annotations

import dataclasses
import statistics

import pandas as pd
import pytest

from cloudlayer.local import LocalAdapter
from src import config, data, seeds
from src.simulation import simulate

START = pd.Timestamp("2012-03-12T00:00")     # a week in, so same-hour-last-week exists


def run(adapter, cfg, raw, model, **kwargs):
    return simulate(adapter, cfg, data.hourly(raw), model, data.holidays(raw), START, **kwargs)


def feed_alerts(result):
    return [a for a in result["alerts"] if a.startswith("FEED")]


# --- detection --------------------------------------------------------------------------------

def test_normal_feed_raises_nothing(adapter, cfg, raw, model):
    results = run(adapter, cfg, raw, model, ticks=10)
    assert all(r["status"] == "ok" for r in results)
    assert not any(feed_alerts(r) for r in results)


def test_frozen_feed_alerts_on_the_first_stale_tick(adapter, cfg, raw, model):
    freeze_at = 3
    results = run(adapter, cfg, raw, model, ticks=10, freeze_at=freeze_at)
    assert not any(feed_alerts(r) for r in results[:freeze_at]), "false alarm before the freeze"

    first = next(r for r in results if feed_alerts(r))
    # The last good reading is from tick freeze_at - 1. At tick freeze_at it is 60 minutes old,
    # at the limit; at freeze_at + 1 it is 120 minutes old and the alert must be up.
    assert first["tick"] == freeze_at + 1, first
    assert any("min old" in a for a in feed_alerts(first))


def test_repeated_values_alone_do_not_page(adapter, cfg, raw, model):
    """Real weather repeats by chance about 50 times a year at 3 hours; that was noise. A feed
    whose values repeat but whose readings are fresh is charted, not paged."""
    world = data.hourly(raw).copy()
    frozen_values = world.loc[START, data.WEATHER].to_numpy()
    world.loc[START:START + pd.Timedelta(hours=6), data.WEATHER] = frozen_values
    results = simulate(adapter, cfg, world, model, data.holidays(raw), START, ticks=6)
    assert max(r["signals"]["weather_repeat_count"] for r in results) >= 5
    assert not any(feed_alerts(r) for r in results)
    assert all(r["status"] == "ok" for r in results)


# --- response ---------------------------------------------------------------------------------

def test_a_stale_reading_keeps_the_model_and_says_so(adapter, cfg, raw, model):
    results = run(adapter, cfg, raw, model, ticks=10, freeze_at=3)
    stale = [r for r in results if feed_alerts(r)]
    assert stale
    for result in stale:
        assert result["status"] == "degraded"
        assert result["source"].startswith("model on the last reading")
    latest = adapter.read_json("forecasts/latest.json")
    assert latest["status"] == "degraded" and latest["reasons"] and latest["model_version"]


def test_an_old_reading_falls_back_to_the_baseline(adapter, cfg, raw, model):
    short = dataclasses.replace(cfg, stale_model_max_age_min=180)
    results = run(adapter, short, raw, model, ticks=10, freeze_at=3)
    sources = {r["tick"]: r["source"] for r in results}
    assert sources[5].startswith("model on the last reading")     # 180 min: still the model
    assert sources[6].startswith("baseline")                      # 240 min: the baseline
    assert all(r["status"] == "degraded" for r in results if r["tick"] >= 4)


def test_the_feed_recovering_clears_the_alert(adapter, cfg, raw, model):
    results = run(adapter, cfg, raw, model, ticks=12, freeze_at=3, unfreeze_at=7)
    assert results[-1]["status"] == "ok" and results[-1]["source"] == "model"
    assert not feed_alerts(results[-1])


def test_signals_reach_the_metric_stream(adapter, cfg, raw, model):
    run(adapter, cfg, raw, model, ticks=6, freeze_at=2)
    names = {m["name"] for m in adapter.metrics()}
    assert {"weather_age_min", "weather_repeat_count", "degraded", "alerts_fired"} <= names
    assert max(m["value"] for m in adapter.metrics() if m["name"] == "degraded") == 1.0


# --- the drill's finding, on the real data -----------------------------------------------------

RAW = config.load(strict=False).raw_path
# Freezes at 06:00 on days across the test period, holidays included (Columbus Day, the day
# before the election, Thanksgiving week).
FREEZE_DAYS = ["2012-10-08", "2012-10-15", "2012-10-24", "2012-11-05", "2012-11-19",
               "2012-12-03", "2012-12-12"]
HOURS = 24


@pytest.fixture(scope="module")
def real_world():
    if not RAW.exists():
        pytest.skip("run `make data` first")
    from sklearn.ensemble import HistGradientBoostingRegressor

    from src.features import FEATURES, training_frame

    raw = data.load_raw(RAW)
    train, _, _ = data.split_by_time(training_frame(raw))
    model = HistGradientBoostingRegressor(loss="poisson", max_iter=150, learning_rate=0.1,
                                          random_state=seeds.set_all())
    model.fit(train[FEATURES], train["cnt"])
    return data.hourly(raw), data.holidays(raw), model


def mean_error_after_freeze(tmp_path, world, holidays, model, cfg) -> float:
    errors = []
    for day in FREEZE_DAYS:
        store = tmp_path / day
        local = dataclasses.replace(cfg, blob_uri=str(store))
        results = simulate(LocalAdapter(local), local, world, model, holidays,
                           pd.Timestamp(day) + pd.Timedelta(hours=6), HOURS + 2, 1, None, None)
        errors += [r["signals"]["abs_error_1h"] for r in results[2:]
                   if r["signals"]["abs_error_1h"] is not None]
    return statistics.mean(errors)


def test_the_response_is_no_worse_than_doing_nothing(tmp_path, real_world, cfg):
    world, holidays, model = real_world
    designed = mean_error_after_freeze(tmp_path / "designed", world, holidays, model, cfg)
    nothing = mean_error_after_freeze(
        tmp_path / "nothing", world, holidays, model,
        dataclasses.replace(cfg, weather_max_age_min=10**6, stale_model_max_age_min=10**6))
    old_design = mean_error_after_freeze(
        tmp_path / "old", world, holidays, model,
        dataclasses.replace(cfg, stale_model_max_age_min=cfg.weather_max_age_min))
    print(f"mean 1-hour error over {HOURS} h: designed {designed:.1f}, "
          f"doing nothing {nothing:.1f}, baseline at once {old_design:.1f}")
    assert designed <= nothing * 1.05, "the response costs more than the failure"
    assert designed < old_design
