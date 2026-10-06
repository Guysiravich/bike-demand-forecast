"""Unit tests for the feature code: training and the hourly job must build the same rows.

Training/serving skew (course Session 2) — the feature computed one way in training and a
slightly different way at serving — is the boring failure nobody notices for six weeks. One
function computes both here, and this checks that it did.
"""
from __future__ import annotations

import pandas as pd

from src import data
from src.features import FEATURES, calendar, inference_frame, training_frame


def test_training_and_the_hourly_job_build_the_same_features(raw):
    frame = training_frame(raw)
    series = data.hourly(raw)
    issue = pd.Timestamp("2012-03-15T08:00")
    weather = {c: float(series.loc[issue, c]) for c in data.WEATHER}
    served = inference_frame(series["cnt"], weather, issue, data.holidays(raw))
    trained = frame[frame["issue_time"] == issue].sort_values("horizon")
    pd.testing.assert_frame_equal(
        served[FEATURES].reset_index(drop=True).astype(float),
        trained[FEATURES].reset_index(drop=True).astype(float),
    )


def test_calendar_marks_holidays_as_non_working():
    times = pd.DatetimeIndex([pd.Timestamp("2012-07-04T09:00")])   # a Wednesday
    plain = calendar(times, set())
    holiday = calendar(times, {pd.Timestamp("2012-07-04")})
    assert plain["workingday"].iloc[0] == 1
    assert holiday["holiday"].iloc[0] == 1 and holiday["workingday"].iloc[0] == 0


def test_weekday_follows_the_source_convention():
    # The source counts Sunday as 0. Getting this wrong shifts every weekly pattern by a day.
    sunday = calendar(pd.DatetimeIndex([pd.Timestamp("2012-03-11")]), set())
    assert sunday["weekday"].iloc[0] == 0
