"""Shared fixtures: a small synthetic world, so the CI tests need neither the real data nor a
trained model. The real-data checks live in test_data_contract.py and skip when the file is
absent."""
from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from cloudlayer.local import LocalAdapter
from src import config


def synthetic_raw(hours: int = 24 * 14, start: str = "2012-03-05") -> pd.DataFrame:
    """Rows shaped like hour.csv. Weather changes every hour, so nothing repeats by chance."""
    times = pd.date_range(start, periods=hours, freq="h")
    i = np.arange(hours)
    cnt = (50 + 150 * np.clip(np.sin((times.hour - 6) / 24 * 2 * math.pi), 0, None)
           + 10 * (times.dayofweek < 5)).round().astype(int)
    registered = (cnt * 0.8).round().astype(int)
    return pd.DataFrame({
        "instant": i + 1,
        "dteday": times.strftime("%Y-%m-%d"),
        "season": 1, "yr": 1, "mnth": times.month, "hr": times.hour,
        "holiday": 0, "weekday": (times.dayofweek + 1) % 7,
        "workingday": (times.dayofweek < 5).astype(int),
        "weathersit": 1 + (i % 3),
        "temp": 0.30 + 0.001 * i % 0.5,
        "atemp": 0.28 + 0.0011 * i % 0.5,
        "hum": 0.40 + 0.0013 * i % 0.5,
        "windspeed": 0.10 + 0.0017 * i % 0.5,
        "casual": cnt - registered, "registered": registered, "cnt": cnt,
        "timestamp": times,
    })


class StubModel:
    """Predicts yesterday's count for the target hour. Enough to exercise the job."""

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        return rows["cnt_lag24"].fillna(0).to_numpy(dtype=float)


@pytest.fixture
def raw() -> pd.DataFrame:
    return synthetic_raw()


@pytest.fixture
def cfg(tmp_path):
    return dataclasses.replace(config.load(), provider="local", store_uri=str(tmp_path / "store"))


@pytest.fixture
def adapter(cfg):
    return LocalAdapter(cfg)


@pytest.fixture
def model():
    return StubModel()
