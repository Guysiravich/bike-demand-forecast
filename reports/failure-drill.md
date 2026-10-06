# Failure drills — local run, 2026-10-06

Both drills ran on one machine, in the pinned base image, with no cloud account. The cloud
version (alert by email, read by the teammate who did not cause it) comes after deployment.

## 1. Frozen weather feed — `make simulate-freeze`

The feed freezes at tick 3 (03:00 simulated). Nothing raises.

| Tick | Weather age | Repeats | Status | 1-hour MAE | Alerts |
|---|---|---|---|---|---|
| 2 | 0 min | 1 | ok | 8.0 | — |
| 3 | 60 min | 2 | ok | 6.4 | — (age 60 is not over the 60-minute limit) |
| **4** | 120 min | 3 | **degraded** | 5.5 | **FEED: age, FEED: repeated 3 runs** |
| 7 | 300 min | 6 | degraded | 76.9 | FEED ×2, **ACCURACY: 76.9 above 76.1** |
| 11 | 540 min | 10 | degraded | 162.5 | FEED ×2, ACCURACY |

- **Detected one tick after the freeze**, by two independent signals at once.
- From tick 4 every forecast row is the "same hour last week" baseline, marked `degraded`
  with its reasons. The model was not rolled back — it was not what was wrong.
- The accuracy signal arrives three ticks later than the feed signals. It is the backstop
  for a failure the feed signals cannot see, not the primary detector.
- CI runs the same scenario on synthetic data (`tests/test_frozen_feed_alert.py`): if the
  alert stops firing within three ticks, the build fails.

## 2. What the drill revealed: the repeat rule's false alarms — `make false-alarms`

Real weather in the dataset repeats by chance. With the alert at 3 identical readings in a
row, the rule alone would have paged **about 50 times a year** on a healthy feed:

| Consecutive identical readings | Occurrences (2 years) | Alerts per year |
|---|---|---|
| 3 or more | 99 | 49.5 |
| 4 or more | 24 | 12.0 |
| 5 or more | 3 | 1.5 |

The age signal has no such cost — a healthy feed is never an hour old — and it fired at the
same tick. Open decision: page on age alone and keep "repeated" as a dashboard signal, or
raise `FEED_REPEAT_ALERT` to 5.

## 3. Bad model — `make rollback`

Version 2 promoted to `champion`, then rolled back:

```
bike-demand: champion 1 -> 2        make promote VERSION=2
bike-demand: champion 2 -> 1        make rollback          2.5 s
```

The job reads `champion` at the start of each run, so the next hourly run serves version 1
with version 1's own alert threshold. Target from the proposal: under 15 minutes. CI covers
it in `tests/test_registry.py`.
