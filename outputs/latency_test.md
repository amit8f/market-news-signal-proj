# Entry-latency backtest, 2026-09-23

Offline analysis only. Same frozen champion model, calibration, thresholds, 2h horizon,
ATR(1x) stop, and slippage as the original Phase 5 backtest (`outputs/backtest_report.txt`).
Entry bar shifted later by the stated delay (measured from each event's real `published_utc`);
exit held at entry + 120 bars, matching the offline `compute_events()` convention. Source
trades: `outputs/trades_champion_alerts_(net).csv`, Buy + Strong Buy rows only (n=226 + 53).

## Part 1 - per-headline trades

**Buy (n=226 headline rows, 15 distinct trading days)**

| delay | n | mean net | win% | day-clustered t | bootstrap 95% CI |
|---|---|---|---|---|---|
| original (reported) | 226 | +0.1724% | 51.3% | +0.616 | [-0.131%, +0.555%] |
| 0 min (resimulated) | 226 | +0.1724% | 51.3% | +0.616 | [-0.131%, +0.555%] |
| 1 min | 226 | +0.1714% | 51.8% | +0.613 | [-0.130%, +0.553%] |
| 4 min | 226 | +0.1740% | 53.1% | +0.645 | [-0.128%, +0.554%] |
| 15 min | 226 | +0.1797% | 51.3% | +0.647 | [-0.117%, +0.560%] |
| 43 min | 226 | +0.1826% | 52.2% | +0.517 | [-0.116%, +0.583%] |

**Strong Buy (n=53 headline rows, 6 distinct trading days)**

| delay | n | mean net | win% | day-clustered t | bootstrap 95% CI |
|---|---|---|---|---|---|
| original (reported) | 53 | +3.0245% | 88.7% | +1.411 | [+0.013%, +3.800%] |
| 0 min (resimulated) | 53 | +3.0245% | 88.7% | +1.411 | [+0.013%, +3.800%] |
| 1 min | 53 | +3.0223% | 88.7% | +1.381 | [+0.007%, +3.799%] |
| 4 min | 53 | +3.0096% | 86.8% | +1.149 | [-0.075%, +3.796%] |
| 15 min | 53 | +3.0095% | 86.8% | +1.148 | [-0.075%, +3.796%] |
| 43 min | 53 | +2.7991% | 88.7% | +1.733 | [+0.085%, +3.512%] |

## Part 2 - collapsed to distinct (ticker, entry_ts) events

**Buy (98 distinct of 226 raw rows at delay 0)**

| delay | n | mean net | win% | day t | boot 95% CI |
|---|---|---|---|---|---|
| original | 98 | +0.0761% | 48.0% | +0.977 | [-0.142%, +0.324%] |
| 0 min | 98 | +0.0761% | 48.0% | +0.977 | [-0.142%, +0.324%] |
| 1 min | 99 | +0.0818% | 49.5% | +0.979 | [-0.138%, +0.325%] |
| 4 min | 99 | +0.0877% | 52.5% | +1.027 | [-0.132%, +0.331%] |
| 15 min | 104 | +0.0917% | 49.0% | +1.045 | [-0.121%, +0.318%] |
| 43 min | 108 | +0.1146% | 51.9% | +1.068 | [-0.102%, +0.358%] |

**Strong Buy (11 distinct of 53 raw rows at delay 0)**

| delay | n | mean net | win% | day t | boot 95% CI |
|---|---|---|---|---|---|
| original | 11 | +1.3390% | 81.8% | +1.658 | [+0.102%, +2.711%] |
| 0 min | 11 | +1.3390% | 81.8% | +1.658 | [+0.102%, +2.711%] |
| 1 min | 11 | +1.3284% | 81.8% | +1.624 | [+0.070%, +2.707%] |
| 4 min | 11 | +1.2675% | 72.7% | +1.352 | [-0.014%, +2.668%] |
| 15 min | 11 | +1.2671% | 72.7% | +1.351 | [-0.014%, +2.667%] |
| 43 min | 17 | +1.6282% | 88.2% | +2.387 | [+0.192%, +2.436%] |

(`n` grows slightly at longer delays: each headline is shifted from its own `published_utc`,
not a shared group offset, so previously-coincident entries can spread onto different bars.)

## Part 3 - published_utc vs retrieval time (code confirmation)

`build_event_frame()` is called with `published_utc` (`run_loop.py:486`), matching the offline
`compute_events()` convention exactly - feature computation is anchored to the stated publish
time in both paths. `fetch_quote()` (`run_loop.py:420-433`) calls Alpaca's `/trades/latest`
endpoint at wall-clock call time, independent of `published_utc` - the latency gap is in entry
execution, not feature computation.

## Part 4 - fired signals rolling into next session's open

2 of 22 fired signals (with resolved outcomes, as of the 2026-09-17 pull) roll into the next
session's opening bar because `published_utc + 120 wall-clock minutes` falls after that day's
session close:

| signal_id | ticker | class | ts_utc | net return |
|---|---|---|---|---|
| 577 | NVDA | Strong Buy | 2026-09-09T19:11:39 | -1.6526% |
| 649 | NVDA | Strong Buy | 2026-09-10T18:53:41 | +1.0005% |
