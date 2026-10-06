# Bike Rental Demand Forecast

ITCS355 capstone — Siravich Namchan (6688067), Jirath Anuduang (6688003).

An hourly batch job forecasts city-wide bike rentals for the next 24 hours, so the dispatch
team can plan truck runs and shifts. When the weather feed goes stale, the job falls back to
"same hour last week", marks its output **degraded**, and an alert fires. That stale feed is
the failure this project was designed around.

The repository follows the course's three-layer contract and lab conventions throughout: the
same `cloud.env` slots, the same `CloudAdapter`, the same `make` targets. Where a section below
is named after a lab, it answers that lab's question for this system.

> **Status (2026-10-06): everything below the "Deploying" heading runs on one machine with no
> cloud account, and was run.** The Azure adapter, CD workflow and job deployment are written
> but not yet run against Azure; they wait for proposal approval. Nothing here claims a cloud
> result that has not happened.

---

## Reproduce

```bash
make reproduce
make verify
```

expected test_mae: 55.761 ± 0.01

Rentals per hour, all 24 horizons, on the test period (October–December 2012).

**What the grader's machine needs:** Docker (with `buildx`), `make`, `git`, and network access
to the UCI archive. No Python packages, no cloud account, no `cloud.env`. `make reproduce`
builds the training image for `linux/amd64`, fetches `hour.csv` *inside* that image (sha256
checked against the value in `scripts/download_data.py`), then trains inside it. `make verify`
uses only the Python standard library. On Windows, run both from WSL2.

Runtime: about 4½ minutes from a cold Docker cache on a laptop under WSL2, most of it the
image build; about 70 seconds once the image exists.

### How the tolerance was chosen

`make reproduce` fixes the seed (20260920), so the tolerance covers how much *the same run*
moves between environments, not how much a different seed moves it (that is in
`reports/runs.md`, and it is larger).

| Run | Environment | test_mae |
|---|---|---|
| image | `make reproduce`, Python 3.11, the training image | 55.761098489579325 |
| dev container | Python 3.11, `pip install --require-hashes -r requirements.txt` | 55.761098489579325 |

Measured spread: **0** to the last digit. ± 0.01 leaves room for floating-point differences on
another CPU; it is far smaller than any hyperparameter change below.

---

## The problem and the data

Dispatch needs to know, an hour ahead and up to a day ahead, how many bikes the city will rent
in each hour. The data has **city-wide** counts only, so the forecast is city-wide; per-station
demand needs data this dataset does not have (MODEL_CARD.md, "What another week would buy").

[UCI Bike Sharing Dataset](https://archive.ics.uci.edu/dataset/275/bike+sharing+dataset),
Fanaee-T and Gama (2013), **CC BY 4.0**: 17,379 hourly rows for Washington DC, 2011–2012, with
the hour, the weather, the calendar and the real number of rentals. No personal data.

| Identifier | Value |
|---|---|
| sha256 of `hour.csv` (checked on every fetch) | `e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f` |
| Data fingerprint logged with every run | `e03de4ee4ef4dc37` |
| DVC md5 (`data/raw/hour.csv.dvc`), logged as `data_version` | `d50bd5a6f55131e72a7bedc334e2fce1` |

DVC tracks `data/raw/hour.csv`; Git tracks only the `.dvc` pointer. The DVC remote is added with
the cloud storage; until then `make data` rebuilds the identical file from the source.

**The split is by time, not at random** — train to June 2012, validate July–September, test
October–December — because a forecaster never sees next week. This is the time-series form of
Lab 1's grouped split, and `tests/test_data.py` asserts it.

Because the data is historical, the service runs on a **simulated clock**: each tick is one
hour of 2012. `src/feeder.py` advances the clock and publishes that hour's weather reading.

---

## Tracked runs

Five runs on the same data and seed, varying `max_leaf_nodes` — how complex one tree may be
(`make runs`). Then the default configuration at seeds 1–5 (`make seeds`). Both tables, with
the commit each run came from, are in `reports/runs.md` (`make compare`).

| Run | max_leaf_nodes | val_mae | val_mae, 1 h | test_mae |
|---|---|---|---|---|
| leaves-7 | 7 | 53.310 | 49.609 | 55.888 |
| leaves-15 | 15 | 52.234 | 48.272 | 54.464 |
| leaves-31 (default) | 31 | 55.071 | 50.723 | 55.761 |
| leaves-63 | 63 | 56.750 | 52.355 | 54.444 |
| leaves-127 | 127 | 58.660 | 54.597 | 55.807 |

**Seed variance** of the default: val_mae 54.506 mean, standard deviation **0.829**, range
53.435–55.555. That number sets the registration gate's margin (2 × 0.829 = 1.66).

Smaller trees validate better: 15 leaves beats the default by 2.8 on validation, more than three
seed standard deviations, so the margin is real rather than noise. On test the order is
different again, and 63 leaves scores best there — exactly why test is not used to choose.

`make reproduce` keeps the default, 31 leaves, because the claim line describes it. A change of
default goes through the pipeline's gate like any other candidate (below), on validation error.

Every run records, in MLflow at `MLFLOW_TRACKING_URI`: every hyperparameter including the seed,
`val_*` and `test_*` metrics separately (and the baseline's, for comparison), `git_commit`,
`data_fingerprint`, `data_version` (DVC md5), `training_job_id`, `image_digest`, and the model.

---

## What is pinned, and where

| What | How | Where |
|---|---|---|
| Dependencies | `uv pip compile --generate-hashes`, inside the pinned base image, for linux/amd64 | `requirements.txt` (training, tests), `requirements-job.txt` (the hourly job), `requirements-cloud.txt` (DVC and the Azure SDK, for the person driving the cloud) |
| Dependency install | `pip install --require-hashes`: a substituted package fails the build | both Dockerfiles, CI, CD |
| Base image | `python:3.11-slim@sha256:9534e5a8…604534` — the bytes the course labs use | `Dockerfile`, `Dockerfile.job` |
| Seeds | Python `random`, NumPy, `PYTHONHASHSEED`, and the model's `random_state`; logged as a parameter | `src/seeds.py`, `src/train.py` |
| Split | by time, fixed dates | `src/data.py` |
| Data | sha256 on fetch; DVC md5 on every run | `scripts/download_data.py`, `data/raw/hour.csv.dvc` |

**Which pin we would drop first: the hashes.** Every package stays pinned with `==`, so what is
lost is protection against different bytes under the same version, which PyPI's no-re-upload
rule already makes rare. The base-image digest guards the likeliest drift — `python:3.11-slim`
moves with no commit from us — and the seed is what makes the claim checkable at all.

---

## Registry, lineage and promotion (Lab 2)

```bash
make train                       # one run; writes reports/metrics.json
make register                    # register that run (or RUN_ID=<id>), lineage on the version
make promote VERSION=<n> ALIAS=staging
make promote VERSION=<n> ALIAS=production    # what the hourly job serves
make models                      # versions, aliases, lineage
make rollback                    # production back to the previous version
make reload-check VERSION=<n>    # load from the registry by version and score rows
make train-remote                # the same training as an Azure ML command job (Lab 2)
```

Every registered version carries the course's eight lineage fields — `git_commit`,
`data_version`, `mlflow_run_id`, `training_job_id`, `image_digest`, `seed`, `metric_val`,
`metric_test` — plus `mae_alert_threshold`, the accuracy-alert level the job reads from the
version it serves. Registration refuses a run with any field missing (`tests/test_registry.py`).

**Promotion.** Two aliases: `staging` is what the pipeline registers for checking; `production`
is what the job serves. The job resolves the alias at the start of every run, so promotion and
rollback take effect at the next tick with no redeploy. **Who promotes to production:** not the
person who trained the model. In a real operator it belongs to the owner of the dispatch
service, with the operations lead's agreement, because the forecast decides where trucks go.
They should require: complete lineage and a rebuild that reproduces the metric; validation
error better than production by more than seed noise (the gate's margin); a passing
`reload-check` in the job image; and the previous version still registered, so the rollback is
one command.

**Serialization, met in practice.** MLflow 3 stores scikit-learn models with skops, which
refused HistGradientBoosting's `TreePredictor` until it was named as trusted at log time
(`src/train.py`, `TRUSTED_TYPES`). Lab 3 met the same failure at load time; here it is fixed
where the course says it belongs, in the MLmodel file.

---

## Deployment: batch, on a schedule (Lab 3)

**Why batch.** The dispatch team plans hours ahead; the freshness they need is "before the
hour starts", not milliseconds. Session 3: *most systems built online should have been batch*.
Batch has no cold start in anyone's path, no autoscaling and no p99.

```
feeder job (each tick)           forecast job (each tick, src/forecast.py)           storage
──────────────────────           ───────────────────────────────────────────         ───────────────────────
advance clock.json      ──►      read clock + latest weather reading                  forecasts/latest.json
publish weather/latest  ──►      valid? how old? same values as last run?             forecasts/<hour>.json
read control/feed_mode           ok  → model from the registry (alias production)     alerts/<hour>.json
                                 stale → same model, last reading, degraded (≤48 h)  state/last_run.json
                                 bad or >48 h → same hour last week, degraded
                                 score last run's 1-hour forecast vs. actual          metrics → Azure Monitor
```

On Azure, both are **Container Apps Jobs** on a cron schedule, from one job image
(`Dockerfile.job`, runtime dependencies only), pulled by digest with a user-assigned identity —
no registry password. Not an Azure ML schedule: that was the Lab 4 drift-job pattern, and at
about 10 node-minutes a run it would cost ~860 THB a month hourly (`reports/cost.md`).

```bash
make job-image                   # build the job image
make deploy ALIAS=production     # push by digest, create or update both jobs
make run-now JOB=bike-forecast   # one execution now — the demo's "next tick"
make freeze / make unfreeze      # the planned failure, on demand
```

All storage, metrics and job calls go through `cloudlayer/` — `LocalAdapter` here, `AzureAdapter`
in the cloud. `make portability-audit` fails the build if a provider detail appears in `src/`
or `tests/`.

---

## Tests, CI and CD (Lab 4)

| Kind | File | Fails when |
|---|---|---|
| Unit | `test_features.py`, `test_forecast.py`, `test_registry.py`, `test_pipeline.py` | our code is wrong: training/serving skew, the job mishandling bad input, a rollback that does not move the alias, a gate that cannot fail |
| Data contract | `test_data.py` | the input is wrong (below) |
| Model behaviour | `test_model_behaviour.py` | the model is wrong: negative forecasts, the morning peak lost, rain raising demand, constant output, scoring too slow for the 5-minute budget |
| The planned failure | `test_frozen_feed_alert.py` | a frozen feed stops paging on the first stale tick, repeats alone start paging, or the response costs more than doing nothing (on the real data) |
| Integration | `scripts/integration_test.sh` | the images do not work together: it trains and registers in the training image, runs feeder and forecast in the **job image**, then freezes the feed and requires `degraded`, the model on the last reading, and an alert |

**The incident each data contract test would have caught:**

| Test | Incident |
|---|---|
| `test_out_of_range_weather_is_caught` | the feed starts sending °C instead of the normalised °C/41: every reading looks like a heatwave and the model forecasts summer demand in December |
| `test_a_category_outside_its_set_is_caught` | the provider adds weather code 5; the model has never seen it and treats it as worse than a storm |
| `test_counts_that_do_not_add_up_are_caught` | the rentals export double-counts a member type; the ledger the accuracy alert scores against is wrong |
| `test_empty_values_are_caught` / `test_missing_hours_stay_rare` | the export starts dropping hours; the lag features go missing and forecasts fall back silently |
| `test_a_missing_column_is_caught` | a renamed column upstream; training would fail at 02:00 on Sunday instead of in review |
| `test_duplicate_hours_are_caught` | a re-sent batch; each duplicated hour is counted twice in the training target |
| `test_the_real_data_is_the_version_we_trained_on` | a different file under the same name; every number in this README stops describing it |
| `test_no_target_hour_of_training_falls_in_validation` | a refactor of the split leaks validation hours into training; the validation error improves and production does not |

**CI** (`.github/workflows/ci.yml`), the course's order: secret scan over the full history →
lint → portability audit → unit → data contract → model behaviour → the planned-failure test →
build both images, tagged by commit SHA → integration test.

**CD** (`.github/workflows/cd.yml`), main only, green only: OIDC to Azure (no stored key), build
the job image from the commit CI tested, push by digest, update both jobs, then a smoke test
that starts one run and waits for it to report success. What CD ships is code; which model the
job serves moves only by `make promote`.

---

## Monitoring, SLOs and the alert (Lab 4)

SLOs, each with its error-budget response, are in `monitoring/slo.yaml`: freshness 99% over
7 days, weather under 60 minutes old, the run under 300 s (the platform kills it there), 99% of
runs succeed over 30 days, and the rolling 1-hour error under the version's threshold.

The job emits six metrics through `emit_metric`: `weather_age_min`, `weather_repeat_count`,
`degraded`, `job_duration_s`, `job_success`, `rolling_mae_1h` (plus `alerts_fired`). Every run
prints structured JSON log lines — `start` with the model version and alias, `done` with every
signal, or `failed` with the exception — so a crash is explained by the last line within a
minute. Bad input never crashes the job: a reading that is not JSON, has no values, carries an
unreadable time or impossible numbers is refused with its reason, and the run degrades
(`tests/test_forecast.py`).

---

## The planned failure: a frozen weather feed (R4)

The feed keeps delivering the same reading. The values are real, only old. Nothing raises and a
health check passes the whole time.

| Signal | Metric | What it does |
|---|---|---|
| The reading is old | `weather_age_min` | **pages** above 60 minutes (`WEATHER_MAX_AGE_MIN`); output marked `degraded` |
| The forecast gets worse | `rolling_mae_1h` | **pages** above 1.5 × the version's validation error at 1 hour |
| The values stop changing | `weather_repeat_count` | **charted only** — real weather repeats by chance about 50 times a year at 3 hours |

**Response: not a retrain, and not a rollback.** This is the left branch of the Lab 4 decision
tree — the upstream pipeline broke, the model did not. Retraining on a frozen feed would teach
the model that weather never changes and destroy the last good version. For up to 48 hours
(`STALE_MODEL_MAX_AGE_MIN`) the job keeps forecasting with the model on the last good reading,
marks every row `degraded` with the reading's age, and the alert pages someone to fix the feed.
After that, or if the reading is unusable, it serves "same hour last week". A bad *model* is
the other branch: `make rollback`.

### What the drill revealed, and what changed (the brief's dotted edge)

The first design switched to "same hour last week" at the first stale tick. The drill measured
it against doing nothing, and it was the wrong default:

| Over 24 h after a freeze, 7 days of the test period | Mean 1-hour error |
|---|---|
| Doing nothing — the model on the frozen reading | 54.6 |
| First design — "same hour last week" at once | 72.1 |
| **Now — the model on the last reading, degraded, for 48 h** | **54.6** |

Within a day, weather changes slowly and the rental lags carry the forecast. `make stale-study`
compares the two by age of the reading over 27 freezes of 48 hours each
(`reports/stale-reading-study.md`): the model on the stale reading was better at every age
measured except the evening peak 10–12 hours in, where the baseline was 4% better. The
fallback waits until 48 hours — as far as the evidence goes.

Two things were fed back into the tests. `test_the_response_is_no_worse_than_doing_nothing`
re-runs that comparison on the real data in CI: if a change makes the response cost more than
the failure, the build fails. `test_repeated_values_alone_do_not_page` holds the second
finding — the repeat rule was noise (`reports/feed-false-alarms.md`) and the age rule fired at
the same tick. The post-mortem, in the course template, is `reports/failure-drill.md`.

**What the age rule gives up:** a feed that freezes the values but stamps each delivery with a
fresh observation time would not page on age. It still shows on the repeat chart, and the
accuracy alert is the backstop.

---

## Pipeline, retraining and the gate (Lab 5)

`pipeline/pipeline.yaml` is the neutral DAG: ingest → validate (data contract; **abort** on
failure) → train → evaluate → register to `staging` **only if the gate passes**. `make pipeline`
runs it here, step by step. `tests/test_pipeline.py` makes the gate fail on purpose and checks
registration is skipped — a pipeline that always registers has no gate.

The gate (`scripts/evaluation_gate.py`) works on validation error, never test: the candidate
must beat "same hour last week" at 1 hour ahead, and beat the version `production` serves by
more than twice the seed standard deviation (`reports/runs.md`).

**What should trigger a retrain, for this system:**

| Strategy | When it is right here | How it fails here |
|---|---|---|
| Fixed schedule (chosen: weekly) | demand drifts with season and the bike fleet; a week of new data is a real change | retrains on a week the feed was frozen, unless the contract tests stop it — they abort the pipeline first |
| Data volume threshold | per-station data arriving unevenly | every hour adds one row; volume is constant and the trigger is just a slow schedule |
| Drift-triggered | a real shift in demand, e.g. a new bike-lane network | a frozen or broken feed *is* drift by every statistic — the worst case: it retrains on corrupted input and destroys the working model faster than any schedule would |

---

## Cost (Lab 3 Task 5, Lab 5 Task 5)

`make cost DURATION=<seconds per run>` writes `reports/cost.md`: the marginal cost of a run, the
fixed costs that dominate, and cost per 1,000 forecasts at three volumes (the batch analogue of
the course's three utilisation assumptions). The actual figure comes from Cost Management
filtered by tag `lab=capstone`, once the jobs have run for a week.

---

## Deploying (not yet run)

Prerequisites, in the order the course's `getting-started-azure.md` uses: the labs' resource
group, storage account, registry and tracking server already exist. New for the project, all
tagged `course=itcs355 student=<id> lab=capstone`:

1. a user-assigned managed identity for the jobs, with `AcrPull` on the registry, `Storage Blob
   Data Contributor` on the project's container only, and `Monitoring Metrics Publisher` on the
   forecast job (least privilege; Lab 5 Task 2);
2. `cloud.env` filled from `cloud.env.example`; `make cloud-check` passes all slots;
3. `make deploy`; then the alert rules on the job's metrics, emailing both of us;
4. for CD: a federated credential on a second identity for this repository's `production`
   environment, and the secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`,
   `CLOUD_ENV`.

**Teardown** deletes by tag, never by resource group, because the group also holds the labs:

```bash
make teardown LAB=capstone DRY_RUN=1   # list
make teardown LAB=capstone             # delete
make teardown-verify                   # run again 24 hours later; then check the portal
```

---

## Setup for development

```bash
cp cloud.env.example cloud.env      # optional locally; never commit
make setup                          # pinned, hash-checked dependencies
make data                           # inside the training image
make check                          # secret scan, lint, portability audit, all tests
make train && make register && make promote VERSION=1 ALIAS=production
make simulate                       # twelve simulated hours, healthy feed
make simulate-freeze                # the planned failure
make false-alarms                   # how often real weather repeats by chance
make stale-study                    # model on a stale reading vs. the baseline, by age
pip install -r requirements-cloud.txt   # only to drive the cloud: DVC, the Azure SDK
```

## Layout

```
src/            Layer 1: config, data (contract, time split), features, seeds, baseline, train,
                registry, feeder (simulated world), forecast (the hourly job), monitor, simulation
cloudlayer/     Layer 3: base (the course's CloudAdapter), local, azure, factory
scripts/        reproduce/verify, registry, deploy and smoke, pipeline and gate, cost, teardown,
                portability audit, secret scan, integration test
tests/          unit, data contract, model behaviour, the frozen-feed alert, the pipeline gate
pipeline/       the neutral DAG          monitoring/   SLOs          docs/   post-mortem template
reports/        metrics.json (make reproduce), runs.md, failure-drill.md, cost.md
```

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
