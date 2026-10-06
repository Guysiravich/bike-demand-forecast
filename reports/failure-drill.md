# Post-mortem — the weather feed froze (planned failure, local drill)

Drill run on 2026-10-06 on one machine: `make simulate-freeze` and
`scripts/integration_test.sh` (the job image). The cloud drill — alert by email, read first by
the teammate who did not cause it — follows deployment. Template: `docs/postmortem-template.md`.

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
decision tree, left branch). Rolling back would serve an older model the same stale weather. Evidence that would change this: healthy, changing readings while the
error stays above threshold — that is the model, and `make rollback` (2.6 s locally) applies.

**What this would have cost if unnoticed for a week:**
Less than noticing it did — the drill's real finding. Mean 1-hour error over 24 simulated hours
(`model version 1`, feed frozen at the second hour):

| Day | Healthy feed | Frozen, detected (baseline served) | Frozen, undetected (model on stale weather) |
|---|---|---|---|
| 2012-10-08 (Columbus Day) | 53.1 | 97.1 | 38.9 |
| 2012-10-15 | 53.5 | 99.6 | 63.7 |
| 2012-11-05 | 66.1 | 156.2 | 69.8 |

Within a day, weather changes slowly and the rental lags carry most of the signal, so the model
on a frozen reading stays close to healthy. "Same hour last week" knows nothing about today and
is about twice as wrong. Over a week the stale reading would drift further from the truth —
not measured yet — but for the first day the designed response costs more than the failure.

**How to prevent or detect it faster:**
Detection works and is guarded: the age check fires on the first stale tick, and CI fails if it
stops (`tests/test_frozen_feed_alert.py`, `scripts/integration_test.sh`). What the drill
revealed is in the response, not the detection: (1) the fallback should be no worse than doing
nothing — candidates are the model on the last good reading for the first hours, or a fallback
that also uses the latest rentals; the test to add asserts the degraded forecast's error is not
above the frozen-model error on these days. (2) The repeat rule is too eager: real weather
repeats 3 hours running about 50 times a year (`reports/feed-false-alarms.md`). Page on age;
chart the repeat count. Both are open decisions for the team.

## The timings

| Tick | Weather age | Repeats | Status | Rolling 1-hour MAE (6 runs) | Alerts |
|---|---|---|---|---|---|
| 2 | 0 min | 1 | ok | 8.0 | — |
| 3 (frozen) | 60 min | 2 | ok | 6.4 | — (60 is not over the 60-minute limit) |
| **4** | 120 min | 3 | **degraded** | 5.5 | **FEED: age, FEED: repeated** |
| 7 | 300 min | 6 | degraded | 76.9 | FEED ×2, **ACCURACY 76.9 > 76.1** |
| 11 | 540 min | 10 | degraded | 162.5 | FEED ×2, ACCURACY |

In the job image (`scripts/integration_test.sh`) the same sequence ran container by container:
healthy runs served model version 1; the first run after freezing reported `degraded`, served
the baseline, and wrote `alerts/<hour>.json`.

## The price of the repeat rule — `make false-alarms`

| Consecutive identical readings | Occurrences (2 years) | Alerts per year |
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
