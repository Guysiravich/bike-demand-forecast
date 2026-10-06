"""Data contract tests (course Lab 4, Task 1): assertions about the DATA, not the code.

They fail when an upstream producer changes something, even though our code is untouched.
Each names the incident it would have caught (README, "Tests and what they catch"). The
leakage tests at the bottom are the Lab 1 split test, for a time series: a forecaster must
never see the future it is predicting.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import config, data
from src.features import training_frame

REAL = config.load(strict=False).raw_path


@pytest.fixture(scope="module")
def real():
    if not REAL.exists():
        pytest.skip("data/raw/hour.csv missing — run `make data` or `dvc pull` first")
    return data.load_raw(REAL)


# --- the real file -----------------------------------------------------------------------

def test_the_real_data_meets_the_contract(real):
    assert data.validate(real) == []


def test_the_real_data_is_the_version_we_trained_on(real):
    # 17,379 rows is the UCI release. A different count means a different file arrived
    # under the same name, and every metric in the README stops describing it.
    assert len(real) == 17_379
    assert real["timestamp"].min() == pd.Timestamp("2011-01-01 00:00")
    assert real["timestamp"].max() == pd.Timestamp("2012-12-31 23:00")


def test_missing_hours_stay_rare(real):
    # The source drops hours with no rentals. Under 1% missing is the release; a feed that
    # starts dropping whole days would starve the lag features silently.
    series = data.hourly(real)
    assert series["cnt"].isna().mean() < 0.01


# --- the contract can fail (each asserts the validator catches a real break) ---------------

def test_the_synthetic_world_meets_the_contract(raw):
    assert data.validate(raw) == []


def test_out_of_range_weather_is_caught(raw):
    broken = raw.copy()
    broken.loc[5, "temp"] = 1.7          # a feed that stops normalising (°C, not °C/41)
    assert any(p.startswith("temp:") for p in data.validate(broken))


def test_a_category_outside_its_set_is_caught(raw):
    broken = raw.copy()
    broken.loc[5, "weathersit"] = 5      # a new weather code nobody trained on
    assert any(p.startswith("weathersit:") for p in data.validate(broken))


def test_counts_that_do_not_add_up_are_caught(raw):
    broken = raw.copy()
    broken.loc[5, "cnt"] += 1
    assert any("casual + registered" in p for p in data.validate(broken))


def test_empty_values_are_caught(raw):
    broken = raw.copy()
    broken.loc[5, "hum"] = None
    assert any("empty" in p for p in data.validate(broken))


def test_a_missing_column_is_caught(raw):
    assert data.validate(raw.drop(columns=["hum"])) != []


def test_duplicate_hours_are_caught(raw):
    doubled = pd.concat([raw, raw.iloc[[3]]])
    assert any("duplicate" in p for p in data.validate(doubled))


# --- leakage: nothing from after the issue time ------------------------------------------

def test_split_is_in_time_order():
    times = pd.date_range("2012-06-25", "2012-10-05", freq="D")
    train, val, test = data.split_by_time(pd.DataFrame({"issue_time": times}))
    assert train["issue_time"].max() < val["issue_time"].min()
    assert val["issue_time"].max() < test["issue_time"].min()


def test_no_target_hour_of_training_falls_in_validation(real):
    # The time-series form of "no machine in two splits": a training row's TARGET hour may
    # not reach into the validation period, or the model has seen what it is scored on.
    train, val, _ = data.split_by_time(training_frame(real))
    assert train["target_time"].max() <= val["issue_time"].min() + pd.Timedelta(hours=24)
    assert train["issue_time"].max() < data.VAL_START


def test_every_feature_is_known_at_issue_time(raw):
    frame = training_frame(raw)
    cnt = data.hourly(raw)["cnt"]
    weather = data.hourly(raw)[data.WEATHER]
    issue = pd.Timestamp("2012-03-15T08:00")
    for h in (1, 6, 24):
        row = frame[(frame["issue_time"] == issue) & (frame["horizon"] == h)].iloc[0]
        target = issue + pd.Timedelta(hours=h)
        assert row["cnt_now"] == cnt[issue]
        assert row["cnt_lag24"] == cnt[target - pd.Timedelta(hours=24)]
        assert row["cnt_lag168"] == cnt[target - pd.Timedelta(hours=168)]
        assert row["temp"] == weather.loc[issue, "temp"], "weather must be read at t, not t+h"
        assert row["cnt"] == cnt[target]
        assert target - pd.Timedelta(hours=24) <= issue
