# Model card — bike-demand

## What it does

Forecasts the number of bikes rented city-wide in each of the next 24 hours, once an hour. It
is a planning aid for the dispatch team: a person still decides where each truck goes.

## What it does not do

- **It does not forecast per station.** The data has city-wide counts only.
- **It has no weather forecast.** Every horizon uses the weather at the time of issue, so the
  24-hour-ahead values are weakest when the weather is about to change.
- **It knows 2011–2012 Washington DC.** Anywhere else, or later, it must be retrained.

## Model

`HistGradientBoostingRegressor` (scikit-learn 1.8.0), Poisson loss, one model for all 24
horizons with the horizon as a feature; seed 20260920. Features: target-hour calendar, weather
at issue time, rentals now, same hour yesterday, same hour last week (`src/features.py`). The
same function builds training rows and serving rows (`tests/test_features.py`).

## Data

UCI Bike Sharing Dataset, Fanaee-T and Gama (2013), CC BY 4.0, 17,379 hours, DVC md5
`d50bd5a6…`. Split by time: train 2011-01 to 2012-06, validate 2012-07 to 2012-09, test 2012-10
to 2012-12.

## Performance

From `make reproduce` (`reports/metrics.json`). Rentals per hour; the hourly mean is about 190.

| | Model | Baseline: same hour last week |
|---|---|---|
| MAE, all horizons, validation | 55.1 | 55.9 |
| MAE, 1 hour ahead, validation | 50.7 | 56.0 |
| MAE, 24 hours ahead, validation | 57.4 | 55.8 |
| MAE, all horizons, test | 55.8 | 70.5 |

Accuracy carries no marks in this project and the model was not tuned beyond five tracked
runs (README). It matters for two things: the registration gate requires beating the baseline
at 1 hour ahead, and the accuracy alert fires when the live 1-hour error passes **76.1**
(1.5 × validation), a number stored on the registered version.

## When not to trust it

When `forecasts/latest.json` says `"status": "degraded"`, with its reasons. For up to 48 hours
of a stale weather feed it is still this model, on the last good reading — close to its
live-feed accuracy over the first day in the drill (`reports/failure-drill.md`) and better than
the baseline at nearly every age up to 48 hours (`reports/stale-reading-study.md`); after that, or
with an unusable reading, the job serves "same hour last week". Also at 24 hours ahead before
a weather change, where it is no better than the baseline (table above).

## Lineage

Every registered version carries: `git_commit`, `data_version`, `mlflow_run_id`,
`training_job_id`, `image_digest`, `seed`, `metric_val`, `metric_test`, and
`mae_alert_threshold`. `make models` lists them.

## What another week would buy

Per-station forecasts, if station-level data can be licensed; a real weather forecast in place
of the reading at issue time, which would fix the 24-hour weakness; and the stale-reading study
extended past 48 hours, with freezes at every hour of the day rather than 06:00 only.
