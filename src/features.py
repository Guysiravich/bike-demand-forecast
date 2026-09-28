"""Features for a 24-hour forecast issued at time t.

One model covers every horizon: each training row is (issue time t, horizon h) and predicts
rentals at t + h. Everything a row uses is known at t:

  calendar of the target hour   hour, weekday, month, season, year, holiday, working day —
                                the calendar is known in advance
  weather at t                  the latest reading, used as-is for every horizon; the
                                service has no weather forecast, which is its main weakness
  rentals at t                  the most recent count
  rentals at t + h - 24         same hour yesterday   (always at or before t, since h <= 24)
  rentals at t + h - 168        same hour last week   (the fallback baseline uses this too)

The planned failure — a frozen weather feed — enters through the weather-at-t columns only.
"""
from __future__ import annotations

import pandas as pd

from src.data import TARGET, WEATHER, holidays, hourly

CALENDAR = ["hr", "weekday", "mnth", "season", "yr", "holiday", "workingday"]
LAGS = ["cnt_now", "cnt_lag24", "cnt_lag168"]
FEATURES = ["horizon", *CALENDAR, *WEATHER, *LAGS]


def calendar(times: pd.DatetimeIndex, holiday_dates: set[pd.Timestamp]) -> pd.DataFrame:
    """Calendar columns for arbitrary hours, derived from the timestamp alone."""
    weekday = (times.dayofweek + 1) % 7            # the source counts Sunday as 0
    holiday = times.normalize().isin(list(holiday_dates)).astype(int)
    month = times.month
    # Dec-Feb=1 ... Sep-Nov=4. Close to, not identical with, the source's astronomical
    # seasons. Training and the hourly job both use THIS function, never the source column,
    # so the two paths cannot disagree about what a feature means (training/serving skew).
    season = ((month % 12) // 3 + 1)
    return pd.DataFrame({
        "hr": times.hour,
        "weekday": weekday,
        "mnth": month,
        "season": season,
        "yr": times.year - 2011,
        "holiday": holiday,
        "workingday": ((weekday >= 1) & (weekday <= 5) & (holiday == 0)).astype(int),
    }, index=times)


def training_frame(raw: pd.DataFrame, horizons: range = range(1, 25)) -> pd.DataFrame:
    """Every (issue time, horizon) pair with a known outcome, in time order."""
    series = hourly(raw)
    cnt = series[TARGET]
    hols = holidays(raw)
    parts = []
    for h in horizons:
        target_time = series.index + pd.Timedelta(hours=h)
        cal = calendar(target_time, hols)
        part = pd.DataFrame({
            "issue_time": series.index,
            "target_time": target_time,
            "horizon": h,
        })
        for column in CALENDAR:
            part[column] = cal[column].to_numpy()
        for column in WEATHER:
            part[column] = series[column].to_numpy()          # weather at t, not at t + h
        part["cnt_now"] = cnt.to_numpy()
        part["cnt_lag24"] = cnt.shift(24 - h).to_numpy()     # value at t + h - 24
        part["cnt_lag168"] = cnt.shift(168 - h).to_numpy()   # value at t + h - 168
        part[TARGET] = cnt.shift(-h).to_numpy()              # the outcome at t + h
        parts.append(part)
    frame = pd.concat(parts, ignore_index=True)
    # An issue time needs a weather reading and a count; the outcome must be known.
    frame = frame.dropna(subset=[*WEATHER, "cnt_now", TARGET])
    return frame.sort_values(["issue_time", "horizon"]).reset_index(drop=True)


def inference_frame(history: pd.Series, weather: dict[str, float], issue_time: pd.Timestamp,
                    holiday_dates: set[pd.Timestamp],
                    horizons: range = range(1, 25)) -> pd.DataFrame:
    """The rows the hourly job scores. `history` is rentals by hour up to issue_time."""
    history = history[history.index <= issue_time]
    target_times = pd.DatetimeIndex([issue_time + pd.Timedelta(hours=h) for h in horizons])
    cal = calendar(target_times, holiday_dates)
    rows = pd.DataFrame({"issue_time": issue_time, "target_time": target_times,
                         "horizon": list(horizons)})
    for column in CALENDAR:
        rows[column] = cal[column].to_numpy()
    for column in WEATHER:
        rows[column] = float(weather[column])
    def back(hours: int) -> list[float]:
        return [history.get(t - pd.Timedelta(hours=hours), float("nan")) for t in target_times]

    rows["cnt_now"] = history.get(issue_time, float("nan"))
    rows["cnt_lag24"] = back(24)
    rows["cnt_lag168"] = back(168)
    return rows
