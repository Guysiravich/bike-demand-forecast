# Bike Rental Demand Forecast

ITCS355 capstone — Siravich Namchan (6688067), Jirath Anuduang (6688003).

An hourly batch job forecasts bike rentals for the next 24 hours, so the dispatch team can
send trucks before a station runs empty. When the weather feed goes stale, the job falls back
to "same hour last week", marks its output **degraded**, and an alert fires. That stale feed
is the failure this project was designed around.

> **Status (2026-10-06): local build, before proposal approval.** Everything below runs on
> one machine with no cloud account. The Azure parts — storage, the scheduled job, the
> dashboard and alert rules, CD — are designed (see `cloudlayer/azure.py` and the project
> plan) and will be built after approval.

## Run it

Needs Python 3.11+ and, for the image, Docker. On Windows, use WSL2.

```bash
make setup            # pinned dependencies
make data             # hour.csv from UCI, sha256 verified (DVC-tracked; `dvc pull` once the remote exists)
make check            # lint, portability audit, secret scan, tests
make register         # train, compare with the baseline, register a version with lineage
make models           # registered versions, which one is `champion`, their lineage
make rollback         # bad model: point `champion` back at the previous version
make simulate         # twelve simulated hours, healthy feed
make simulate-freeze  # the planned failure: the feed freezes at hour 3
```

## The data

[UCI Bike Sharing Dataset](https://archive.ics.uci.edu/dataset/275/bike+sharing+dataset),
Fanaee-T and Gama (2013), **CC BY 4.0**: 17,379 hourly rows for Washington DC, 2011–2012,
with the hour, the weather, the calendar and the real number of rentals. No personal data.
The contract every copy must meet is in `src/data.py` and tested in
`tests/test_data_contract.py`. The split is by time — train to June 2012, validate July to
September, test October to December — because a forecaster never sees next week.

Because the data is historical, the service runs on a **simulated clock**: each tick is one
hour of 2012. `src/feeder.py` advances the clock and publishes that hour's weather reading.

## How it works

```
feeder (each tick)          hourly job (src/forecast.py)                    outputs
──────────────────          ──────────────────────────────────────────      ─────────────────────
clock.json          ──►     read clock + latest weather reading             forecasts/latest.json
weather/latest.json ──►     valid? how old? same values as last run?        metrics (signals)
control/feed_mode   ──►     ok  → model (from the registry)                 alerts/<hour>.json
                            not → same hour last week, status = degraded
                            score last run's 1-hour forecast vs. actual
```

All storage and metrics go through `cloudlayer/` — `LocalAdapter` today, `AzureAdapter`
after approval. `make portability-audit` fails the build if a provider detail appears in
`src/` or `tests/`.

## The planned failure: a frozen weather feed

The feed keeps delivering the same reading. The values are real, only old. Nothing raises,
and a health check passes the whole time. Three signals catch it:

| Signal | Metric | Fires when |
|---|---|---|
| The weather values stop changing | `weather_repeat_count` | 3 runs in a row (`FEED_REPEAT_ALERT`) |
| The reading is old | `weather_age_min` | older than 60 minutes (`WEATHER_MAX_AGE_MIN`) |
| The forecast gets worse | `rolling_mae_1h` | above 1.5 × the validation error at 1 hour |

**Response.** Not a model rollback — the model is not what is wrong. The job switches to
"same hour last week", which needs no weather, and marks every row `degraded` with the reason.
A bad *model* is handled differently: `make rollback` points the `champion` alias back at the
previous version, and the next run serves it (2.5 s locally; `tests/test_registry.py`).
Both drills and what they revealed: `reports/failure-drill.md`.

**The test the brief asks for** — `tests/test_frozen_feed_alert.py`: freeze the feed, and the
alert must fire within three hours, with every later forecast degraded. It runs in CI; if
detection ever stops working, the build fails.

**The price of signal 1.** Real weather can repeat by chance. `make false-alarms` counts how
often it does across the two years, in `reports/feed-false-alarms.md`.

## Service levels (from the proposal)

| Promise | Target | Measured by |
|---|---|---|
| The forecast is ready before the hour it covers | every hour | `forecasts/latest.json` issue time |
| The weather data we use is fresh | under 1 hour old | `weather_age_min` |
| The hourly job finishes | under 5 minutes | `job_duration_s` |
| Hourly runs that succeed | 99% | the platform's job history |

## Layout

```
src/            config, data (contract, split), features, baseline, train, registry,
                feeder (simulated world), forecast (the hourly job), monitor (signals, alerts),
                simulation (feeder + job together)
cloudlayer/     base (the interface), local (filesystem), azure (after approval), factory
scripts/        download_data, simulate, feed_false_alarms, portability_audit, scan_secrets
tests/          data contract, features (leakage, train/serve consistency), forecast (bad
                input), frozen feed (the required test)
```

## What is pinned

| What | Where |
|---|---|
| Python dependencies, with hashes | `requirements.txt`, compiled from `requirements.in` by `make lock` (uv, pinned) inside the pinned base image |
| Base image | `python:3.11-slim@sha256:9534e5a8…`, the same bytes the course labs use |
| Data | the UCI file's sha256 in `scripts/download_data.py`; `data/raw/hour.csv.dvc` (md5 copied onto every registered version as `data_version`). The DVC remote is added with the cloud storage |
| Seed | `20260920`, in `src/config.py` |

## Team

| Area | Owner | Reviewer |
|---|---|---|
| Data and training pipeline | Siravich | Jirath |
| Deployment and CI/CD | Jirath | Siravich |
| Monitoring and alerts | Jirath | Siravich |
| Planned failure and its test | Siravich | Jirath |
| README, model card, slides | shared | shared |

Every pull request is reviewed by the other person. Whoever builds the planned failure is not
the one who first watches its alert fire.
