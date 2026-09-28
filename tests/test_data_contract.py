"""The data contract: what every copy of hour.csv must satisfy, and proof it can fail."""
from __future__ import annotations

import pandas as pd
import pytest

from src import config, data

REAL = config.load().raw_path


@pytest.mark.skipif(not REAL.exists(), reason="run `make data` (or `dvc pull`) first")
def test_the_real_data_meets_the_contract():
    raw = data.load_raw(REAL)
    assert data.validate(raw) == []
    assert len(raw) == 17_379


def test_the_synthetic_world_meets_the_contract(raw):
    assert data.validate(raw) == []


def test_out_of_range_weather_is_caught(raw):
    broken = raw.copy()
    broken.loc[5, "temp"] = 1.7
    assert any(p.startswith("temp:") for p in data.validate(broken))


def test_counts_that_do_not_add_up_are_caught(raw):
    broken = raw.copy()
    broken.loc[5, "cnt"] += 1
    assert any("casual + registered" in p for p in data.validate(broken))


def test_a_missing_column_is_caught(raw):
    assert data.validate(raw.drop(columns=["hum"])) != []


def test_duplicate_hours_are_caught(raw):
    doubled = pd.concat([raw, raw.iloc[[3]]])
    assert any("duplicate" in p for p in data.validate(doubled))
