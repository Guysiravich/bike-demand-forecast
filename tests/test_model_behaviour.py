"""Model behaviour tests (course Lab 4, Task 1): what the model DOES, independent of its metric.

A contract test fails when an upstream producer changes something; a behaviour test fails when
the MODEL changes. These train a small model on the real data with the production settings
and assert things the domain requires. They skip without the data, like the course's.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingRegressor

from src import config, data, seeds
from src.features import FEATURES, inference_frame, training_frame

RAW = config.load(strict=False).raw_path
# The hourly job must finish in 5 minutes (JOB_MAX_DURATION_S). Scoring 24 rows is a sliver of
# that; this fails only when the model alone would eat a large share of the budget.
SCORE_BUDGET_MS = 1000.0
ISSUE = pd.Timestamp("2012-10-10T06:00")       # a Wednesday morning in the test period


@pytest.fixture(scope="module")
def world():
    if not RAW.exists():
        pytest.skip("run `make data` first")
    seed = seeds.set_all()
    raw = data.load_raw(RAW)
    train, _, test = data.split_by_time(training_frame(raw))
    model = HistGradientBoostingRegressor(loss="poisson", max_iter=150, learning_rate=0.1,
                                          random_state=seed)
    model.fit(train[FEATURES], train["cnt"])
    series = data.hourly(raw)
    return model, test, series, data.holidays(raw)


def rows_at(world, issue=ISSUE, **weather_overrides):
    _, _, series, holidays = world
    weather = {c: float(series.loc[issue, c]) for c in data.WEATHER} | weather_overrides
    return inference_frame(series["cnt"], weather, issue, holidays)


def test_forecasts_are_counts(world):
    model, test, _, _ = world
    predicted = model.predict(test[FEATURES].head(5000))
    assert not np.isnan(predicted).any()
    assert (predicted >= 0).all(), "a Poisson model must not forecast negative rentals"


def test_the_morning_peak_beats_the_small_hours(world):
    """On a working day, 08:00 has far more rentals than 03:00 — the commute. A model that
    loses this has learned the calendar backwards, and an aggregate MAE might not show it."""
    model = world[0]
    rows = rows_at(world).set_index("target_time")
    predicted = pd.Series(model.predict(rows[FEATURES]), index=rows.index)
    peak, small_hours = pd.Timestamp("2012-10-10T08:00"), pd.Timestamp("2012-10-11T03:00")
    assert predicted[peak] > 3 * predicted[small_hours]


def test_heavy_rain_lowers_demand(world):
    """Weather code 4 (heavy rain, ice) against code 1 (clear), all else equal: fewer rides.
    Trees are not monotonic by construction, so this can genuinely fail."""
    model = world[0]
    clear = model.predict(rows_at(world, weathersit=1.0)[FEATURES]).sum()
    storm = model.predict(rows_at(world, weathersit=4.0)[FEATURES]).sum()
    assert storm < clear


def test_model_is_not_constant(world):
    model, test, _, _ = world
    assert model.predict(test[FEATURES].head(2000)).std() > 10, "forecasts barely vary"


def test_scoring_one_run_is_within_budget(world):
    model = world[0]
    rows = rows_at(world)[FEATURES]
    model.predict(rows)                      # warm up
    started = time.perf_counter()
    for _ in range(10):
        model.predict(rows)
    elapsed_ms = (time.perf_counter() - started) * 1000 / 10
    assert elapsed_ms < SCORE_BUDGET_MS, f"scoring 24 rows took {elapsed_ms:.1f} ms"
