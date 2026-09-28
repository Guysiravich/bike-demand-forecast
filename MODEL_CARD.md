# Model card — bike-demand

> Draft. Figures marked «measured» are filled in from `reports/train_metrics.json` after the
> first registered training run.

## What it does

Forecasts the number of bikes rented in each of the next 24 hours, city-wide, once an hour.
It is a planning aid for the dispatch team: a person still decides where each truck goes.

## What it does not do

- **It does not forecast per station.** The data has city-wide counts only. Per-station
  demand is the obvious next step and needs data this dataset does not have.
- **It has no weather forecast.** Every horizon uses the weather at the time of issue, so the
  24-hour-ahead values are weakest when the weather is about to change.
- **It knows 2011–2012 Washington DC.** Anywhere else, or later, it must be retrained.

## Model

`HistGradientBoostingRegressor` (scikit-learn 1.8.0), Poisson loss, one model for all 24
horizons with the horizon as a feature. Features: target-hour calendar, weather at issue
time, rentals now, same hour yesterday, same hour last week (`src/features.py`).

## Data

UCI Bike Sharing Dataset, CC BY 4.0, 17,379 hours. Train 2011-01 to 2012-06, validate
2012-07 to 2012-09, test 2012-10 to 2012-12.

## Performance «measured»

| | Model | Baseline: same hour last week |
|---|---|---|
| MAE, all horizons, validation | | |
| MAE, 1 hour ahead, validation | | |
| MAE, 24 hours ahead, validation | | |
| MAE, all horizons, test | | |

## When not to trust it

When `forecasts/latest.json` says `"status": "degraded"`. The job then serves the baseline
and lists the reasons — a stale, repeated or invalid weather reading.

## Lineage

Every registered version carries: git commit, data fingerprint, data version, MLflow run,
training job, image digest, seed, validation and test error, and its alert threshold.
