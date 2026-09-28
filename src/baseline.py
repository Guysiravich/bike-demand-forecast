"""The fallback forecast: rentals in the same hour last week.

It needs no weather and no model, which is the point. When the weather feed is stale the
model is being fed old inputs, and rolling the model back would not help — the model is not
what is wrong. The job switches to this and marks its output degraded.
"""
from __future__ import annotations

import pandas as pd


def same_hour_last_week(history: pd.Series, target_times: pd.DatetimeIndex) -> list[float]:
    """For each target hour: the count 168 h earlier, else 24 h earlier, else that
    hour-of-week's median over the history, else 0. Every step is known at issue time."""
    hour_of_week = history.groupby([history.index.dayofweek, history.index.hour]).median()
    out = []
    for t in target_times:
        for back in (168, 24):
            value = history.get(t - pd.Timedelta(hours=back))
            if value is not None and pd.notna(value):
                out.append(float(value))
                break
        else:
            key = (t.dayofweek, t.hour)
            value = hour_of_week.get(key)
            out.append(float(value) if value is not None and pd.notna(value) else 0.0)
    return out
