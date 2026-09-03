# Finding: Finnhub free-tier retrieval lag (2026-09-02)

Status: **factual finding only — no decision made, no config/threshold change proposed.**
This is not an EVALUATION_PLAN.md entry; it documents an empirical measurement for
the record ahead of a separate design discussion about whether/how to change the
live news source.

## What was measured

Retrieval lag = wall-clock gap between a headline's Finnhub-reported `published_utc`
and the moment the live poller (`news_signal/live/run_loop.py`) first observed it,
logged unconditionally for every item reaching the staleness check via the
`retrieval_lag` table added alongside the 2026-09-01 `max_retrieval_lag_minutes` fix.

## Data source

`signals_full.db` — a fresh, WAL-checkpointed pull of the VM's `data/live/signals.db`,
covering the complete window since that fix deployed:
`2026-09-01T13:31:49 UTC` through `2026-09-02T17:44:32 UTC` (two full trading days).
n = 418 logged items.

## Distribution

| stat | value |
|---|---|
| min | -52.4 min (timestamp jitter) |
| median | **154.6 min** |
| mean | 248.9 min |
| p90 | 659.3 min (11.0h) |
| p95 | 734.2 min (12.2h) |
| max | 1027.3 min (17.1h) |

| cutoff | fraction &le; cutoff |
|---|---|
| &le; 15 min | 14.4% (60/418) |
| &le; 30 min | 18.7% (78/418) |
| &le; 60 min | 29.2% (122/418) |
| &le; 120 min | 45.0% (188/418) |
| **> 120 min** | **55.0% (230/418)** |

By day: Sept 1 median 138.1 min (n=284), Sept 2 median 256.7 min (n=134, worse, not
better). Consistent direction on both days — this is not a one-day anomaly.

## Interpretation (finding, not a decision)

Median retrieval lag alone (154.6 min) already exceeds the strategy's full
120-minute forward-return horizon, and 55% of items arrive with more than 2 hours
of lag. No `max_retrieval_lag_minutes` threshold choice recovers this: the mass of
the distribution sits in the hours-to-overnight range, not the minutes range this
system's poll cadence (120s) would need. This lag is attributable to Finnhub's own
free-tier syndication delay, not to polling frequency or the lookback window.

Caveat: this table can only measure lag for items the poller *did* eventually
observe. It cannot measure the "never delivered" fraction, since an item Finnhub's
free tier never surfaces at all would never appear here.

## Not addressed here

Whether Alpaca News (measured separately at ~0.5-3.5 min live-poll latency) replaces
Finnhub as the primary source, supplements it, or something else — that is an open
design question to be worked through separately before any implementation proceeds.
