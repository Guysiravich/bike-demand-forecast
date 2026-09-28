"""Leakage and training/serving consistency.

A forecast issued at t may use nothing from after t. And the hourly job must build exactly
the features training built — the same function computes both, and this checks it did.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import data
from src.features import FEATURES, inference_frame, training_frame


@pytest.fixture
def frame(raw):
    return training_frame(raw)


def test_every_feature_is_known_at_issue_time(raw, frame):
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


def test_training_and_the_hourly_job_build_the_same_features(raw, frame):
    series = data.hourly(raw)
    issue = pd.Timestamp("2012-03-15T08:00")
    weather = {c: float(series.loc[issue, c]) for c in data.WEATHER}
    served = inference_frame(series["cnt"], weather, issue, data.holidays(raw))
    trained = frame[frame["issue_time"] == issue].sort_values("horizon")
    pd.testing.assert_frame_equal(
        served[FEATURES].reset_index(drop=True).astype(float),
        trained[FEATURES].reset_index(drop=True).astype(float),
    )


def test_split_is_in_time_order():
    times = pd.date_range("2012-06-25", "2012-10-05", freq="D")
    train, val, test = data.split_by_time(pd.DataFrame({"issue_time": times}))
    assert train["issue_time"].max() < val["issue_time"].min()
    assert val["issue_time"].max() < test["issue_time"].min()
