"""The signals the hourly job reports, and the alert rules that read them.

The planned failure is a weather feed that freezes: it keeps delivering the same reading,
the values are plausible, nothing raises. A health check cannot see it. Two signals page:

  weather_age_min        how old the reading's own timestamp is at issue time
  rolling_mae_1h         the 1-hour-ahead forecast against rentals actually observed

and one is charted, not paged:

  weather_repeat_count   consecutive runs that received identical values. Real weather repeats
                         3 hours running about 50 times a year (reports/feed-false-alarms.md);
                         as a page it was noise, and the age signal fired at the same tick.

What the job serves with a stale reading is `response()`, below. The drill measured it
(reports/failure-drill.md): for the first hours the model on the last reading beats "same hour
last week" by a wide margin, so the baseline is the fallback only once the reading is old.

The same rules run in two places: here, where CI tests them (tests/test_frozen_feed_alert.py
fails the build if a frozen feed stops being detected), and as alert rules on the cloud
metrics, which page a person. Keep the thresholds in one place: src/config.py.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.config import Config


@dataclass
class Signals:
    sim_time: str
    weather_age_min: float
    weather_repeat_count: int
    weather_valid: bool
    abs_error_1h: float | None
    rolling_mae_1h: float | None
    job_duration_s: float
    degraded: bool
    weather_problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def degraded_reasons(signals: Signals, cfg: Config) -> list[str]:
    """Why the job should not trust the weather this hour. Empty means it may."""
    reasons = []
    if not signals.weather_valid:
        detail = "; ".join(signals.weather_problems) or "unknown"
        reasons.append(f"weather reading failed validation: {detail}")
    if signals.weather_age_min > cfg.weather_max_age_min:
        reasons.append(f"weather is {signals.weather_age_min:.0f} min old "
                       f"(limit {cfg.weather_max_age_min})")
    return reasons


def response(signals: Signals, cfg: Config) -> str:
    """What the job serves this hour:

      "model"        the reading is valid and fresh
      "stale-model"  valid, older than WEATHER_MAX_AGE_MIN but not STALE_MODEL_MAX_AGE_MIN:
                     the model on the last reading, marked degraded
      "baseline"     no valid reading, or one older than that: same hour last week, degraded
    """
    if not signals.weather_valid:
        return "baseline"
    if signals.weather_age_min <= cfg.weather_max_age_min:
        return "model"
    if signals.weather_age_min <= cfg.stale_model_max_age_min:
        return "stale-model"
    return "baseline"


def alerts(signals: Signals, cfg: Config, mae_threshold: float | None = None) -> list[str]:
    """The alert rules. Each returned string is one alert that would page someone."""
    fired = [f"FEED: {reason}" for reason in degraded_reasons(signals, cfg)]
    if (mae_threshold is not None and signals.rolling_mae_1h is not None
            and signals.rolling_mae_1h > mae_threshold):
        fired.append(f"ACCURACY: rolling 1-hour MAE {signals.rolling_mae_1h:.1f} "
                     f"above {mae_threshold:.1f}")
    if signals.job_duration_s > cfg.job_max_duration_s:
        fired.append(f"JOB: took {signals.job_duration_s:.0f} s (limit {cfg.job_max_duration_s})")
    return fired
