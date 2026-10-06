# Post-mortem — the weather feed froze (planned failure, local drill)

First drill run on 2026-10-06 on one machine: `make simulate-freeze` and
`scripts/integration_test.sh` (the job image). Follow-up and re-run on 2026-10-07, below. The
cloud drill — alert by email, read first by the teammate who did not cause it — follows
deployment. Template: `docs/postmortem-template.md`.

**What fired:**
At simulated 04:00, one tick after the feed froze at 03:00: `FEED: weather is 120 min old
(limit 60)` and `FEED: weather repeated 3 runs in a row (limit 3)`, together. Three ticks later
`ACCURACY: rolling 1-hour MAE 76.9 above 76.1` joined them.

**True cause:**
Pipeline breakage, not drift: the feeder kept re-delivering the 02:00 reading with fresh
delivery times. Inputs looked plausible and nothing raised; the model was unchanged and correct.

**Retrain, roll back, or no action — and why:**
Neither. The job switched itself to "same hour last week" and marked every row `degraded`; the
action is to fix the feed — though the cost below shows that switch was the wrong default.
Retraining would learn from weather that never changes and destroy the last good model (Lab 4
decision tree, left branch). Rolling back would serve an older model the same stale weather.
Evidence that would change this: healthy, changing readings while the error stays above
threshold — that is the model, and `make rollback` (2.6 s locally) applies.

**What this would have cost if unnoticed for a week:**
Less than noticing it did — the drill's real finding. Mean 1-hour error over 24 simulated hours
(model version 1, feed frozen at the second hour):

| Day | Healthy feed | Frozen, detected (baseline served) | Frozen, undetected (model on stale weather) |
|---|---|---|---|
| 2012-10-08 (Columbus Day) | 53.1 | 97.1 | 38.9 |
| 2012-10-15 | 53.5 | 99.6 | 63.7 |
| 2012-11-05 | 66.1 | 156.2 | 69.8 |

Within a day, weather changes slowly and the rental lags carry most of the signal, so the model
on a frozen reading stays close to healthy. "Same hour last week" knows nothing about today and
is about twice as wrong. For the first day, the designed response cost more than the failure.

**How to prevent or detect it faster:**
Detection worked and was guarded: the age check fired on the first stale tick, and CI fails if
it stops. What the drill revealed was in the response, not the detection: (1) the fallback was
worse than doing nothing; (2) the repeat rule was too eager — real weather repeats 3 hours
running about 50 times a year (`reports/feed-false-alarms.md`). Both were acted on the next day.

---

## Follow-up, 2026-10-07 — what changed

| Finding | Change | Test that holds it |
|---|---|---|
| The fallback was worse than doing nothing | For up to 48 h the job keeps the model on the last good reading, marked `degraded` with the reading's age; "same hour last week" only after that, or when the reading is unusable (`monitor.response`, `STALE_MODEL_MAX_AGE_MIN`) | `test_the_response_is_no_worse_than_doing_nothing` (real data, in CI), `test_a_stale_reading_keeps_the_model_and_says_so`, `test_an_old_reading_falls_back_to_the_baseline` |
| The repeat rule paged on chance | Pages on age only; the repeat count is charted | `test_repeated_values_alone_do_not_page` |

**Why 48 hours.** `make stale-study` froze the feed at 06:00 on every third day of the test
period, 27 times, for 48 hours each, and scored both responses by the age of the reading
(`reports/stale-reading-study.md`). The model on the stale reading was better at every age
measured except the evening peak 10–12 hours in, where the baseline was 4% better (125.8 against
130.4) — not enough to justify switching for three hours and back. 48 hours is where the evidence stops, so it is where the fallback starts.

**The result, over 24 h after a freeze on 7 days of the test period** (the CI test's numbers):

| Response | Mean 1-hour error |
|---|---|
| Doing nothing | 54.6 |
| First design: "same hour last week" at once | 72.1 |
| **Now** | **54.6** |

**What the age rule gives up.** A feed that freezes the values but stamps each delivery with a
fresh observation time would not page. It shows on the repeat chart, and the accuracy alert is
the backstop.

## The timings, re-run after the change — `make simulate-freeze`

| Tick | Weather age | Repeats | Status | Served | Rolling 1-hour MAE (6 runs) | Alerts |
|---|---|---|---|---|---|---|
| 2 | 0 min | 1 | ok | model | 8.0 | — |
| 3 (frozen) | 60 min | 2 | ok | model | 6.4 | — (60 is not over the limit) |
| **4** | 120 min | 3 | **degraded** | model, last reading | 5.5 | **FEED: 120 min old** |
| 7 | 300 min | 6 | degraded | model, last reading | 8.6 | FEED |
| 11 | 540 min | 10 | degraded | model, last reading | 49.9 | FEED |

Before the change, the same ticks served the baseline and the rolling error reached 162.5 by
tick 11, firing the accuracy alert. In the job image (`scripts/integration_test.sh`) the
sequence ran container by container: healthy runs served model version 1; after the freeze the
job reported `degraded`, kept the model on the last reading, and wrote `alerts/<hour>.json`.

## The price of the repeat rule — `make false-alarms`

| Consecutive identical readings | Occurrences (2 years) | Pages per year if it paged |
|---|---|---|
| 3 or more | 99 | 49.5 |
| 4 or more | 24 | 12.0 |
| 5 or more | 3 | 1.5 |

## Bad model — `make rollback`

```
bike-demand@production: 1 -> 2        make promote VERSION=2 ALIAS=production
bike-demand@production: 2 -> 1        make rollback                         2.6 s
```

The job reads the alias at the start of every run, so the next tick serves version 1 with
version 1's own alert threshold. Target from the proposal: under 15 minutes.
`tests/test_registry.py` keeps it working.
