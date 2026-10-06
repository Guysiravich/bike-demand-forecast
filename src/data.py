"""The UCI Bike Sharing hourly data: loading, the data contract, and a time-based split.

Source: UCI Machine Learning Repository, Bike Sharing Dataset (id 275), Fanaee-T and Gama,
2013, CC BY 4.0. 17,379 hourly rows for Washington DC, 2011-01-01 to 2012-12-31. Some hours
are missing (no rentals were recorded), so the series is re-indexed to every hour and the
gaps are kept as gaps, never filled with invented values.

The weather columns are normalised by the source: temp / 41, atemp / 50, hum / 100,
windspeed / 67. They are used as given.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

WEATHER = ["weathersit", "temp", "atemp", "hum", "windspeed"]
TARGET = "cnt"

# The contract every copy of the data must meet. Lab 4 asserts the same bounds in CI, and the
# feed validator in src/feeder.py uses the weather part of it at run time.
RANGES: dict[str, tuple[float, float]] = {
    "season": (1, 4),
    "yr": (0, 1),
    "mnth": (1, 12),
    "hr": (0, 23),
    "holiday": (0, 1),
    "weekday": (0, 6),
    "workingday": (0, 1),
    "weathersit": (1, 4),
    "temp": (0.0, 1.0),
    "atemp": (0.0, 1.0),
    "hum": (0.0, 1.0),
    "windspeed": (0.0, 1.0),
    "casual": (0, 10_000),
    "registered": (0, 10_000),
    "cnt": (0, 10_000),
}
COLUMNS = ["instant", "dteday", *RANGES]

# Train, validate and test are consecutive periods. A random split would let the model see
# next week's rentals while it learns this week's, which a forecaster never can.
VAL_START = pd.Timestamp("2012-07-01")
TEST_START = pd.Timestamp("2012-10-01")


def load_raw(path: Path) -> pd.DataFrame:
    """Read hour.csv and add a `timestamp` column (date + hour). Sorted by time."""
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["dteday"]) + pd.to_timedelta(df["hr"], unit="h")
    return df.sort_values("timestamp").reset_index(drop=True)


def validate(df: pd.DataFrame) -> list[str]:
    """Return every way the frame breaks the contract. Empty means it passes."""
    problems: list[str] = []
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        return [f"missing columns: {missing}"]
    for column, (low, high) in RANGES.items():
        if df[column].isna().any():
            problems.append(f"{column}: {int(df[column].isna().sum())} empty values")
        outside = df[(df[column] < low) | (df[column] > high)]
        if len(outside):
            problems.append(f"{column}: {len(outside)} values outside [{low}, {high}]")
    mismatch = df[df["casual"] + df["registered"] != df["cnt"]]
    if len(mismatch):
        problems.append(f"cnt != casual + registered on {len(mismatch)} rows")
    if "timestamp" in df.columns and df["timestamp"].duplicated().any():
        problems.append(f"{int(df['timestamp'].duplicated().sum())} duplicate hours")
    return problems


def hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Index by timestamp over every hour of the period; missing hours stay NaN."""
    full = pd.date_range(df["timestamp"].min(), df["timestamp"].max(), freq="h")
    return df.set_index("timestamp").reindex(full)


def holidays(df: pd.DataFrame) -> set[pd.Timestamp]:
    """Dates the source marks as public holidays. The calendar is known ahead of time."""
    return set(pd.to_datetime(df.loc[df["holiday"] == 1, "dteday"]).dt.normalize())


def split_by_time(frame: pd.DataFrame, time_column: str = "issue_time") -> tuple[
        pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Train before 2012-07, validate 2012-07 to 2012-09, test 2012-10 onward."""
    t = frame[time_column]
    return (frame[t < VAL_START], frame[(t >= VAL_START) & (t < TEST_START)],
            frame[t >= TEST_START])


def fingerprint(path: Path) -> str:
    """First 16 hex characters of the file's sha256. Logged with every run."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def dvc_hash(dvc_file: Path) -> str:
    """The md5 DVC recorded for the tracked file — the data version a run consumed."""
    if not dvc_file.exists():
        return "unversioned"
    for line in dvc_file.read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().lstrip("- ").partition(":")
        if key == "md5":
            return value.strip()
    return "unknown"
