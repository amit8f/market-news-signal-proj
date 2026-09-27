# Placebo test: does the edge come from technical context or news content?

Offline analysis only. Holdout window (>= 2026-08-03). For each of the 3,197 real holdout
events, sampled up to 3 placebo timestamps per event: same ticker, matched ET hour-of-day,
regular-session minute bar, no real news for that ticker within +/-2h, drawn from the same
cached bar history used everywhere else in this project. 9,178 placebo candidates generated
(target ~9,591); 9,136 scored after dropping rows with incomplete features. Of the 3,197 real
events, 1,424 found an exact ET-hour match; 1,773 fell back to any-hour sampling for that
ticker (no candidate existed at the exact hour with no nearby news).

Scored with the frozen champion model + calibration + thresholds, `decide()` unchanged.
Returns simulated with the same entry(open @ first bar >= timestamp) / exit(close @ +120 bars)
/ ATR(1x) stop / slippage convention used throughout this project's backtests.

## Neutral defaults used for news-derived features (as requested, exact values)

| feature | value |
|---|---|
| `sent_score` | 0.0 |
| `p_pos` | 0.0 |
| `p_neg` | 0.0 |
| `p_neu` | 1.0 |
| `news_type` | `"other"` (`nt_other=1`, all other `nt_*`=0) |
| `relevance_tier` | 1 |

`hours_since_prev_headline` / `headlines_prior_24h` were **not** set to a neutral default -
computed genuinely from real historical news timing for that ticker (ambient recency context,
not news content itself). `pub_hour_et` computed genuinely from the placebo timestamp itself.
All technical/regime/sector features computed for real from cached bar data, same batch
functions (`build_technical_features`, `add_regime_features`, `attach_sector_features`) used
by the offline training pipeline.

## Fire rate, full sample

| class | real fire rate | placebo fire rate |
|---|---|---|
| Buy | 226/3197 = 7.069% | 377/9136 = 4.127% |
| Strong Buy | 53/3197 = 1.658% | 236/9136 = 2.583% |

## Mean calibrated Strong Buy probability (all scored events, not just fired)

| population | n | mean calibrated Strong Buy probability |
|---|---|---|
| real holdout | 3197 | 0.10339 |
| placebo | 9136 | 0.11273 |

## Returns, full sample, collapsed to distinct (ticker, entry_ts)

| | n | mean net return | win rate | day-clustered t | bootstrap 95% CI |
|---|---|---|---|---|---|
| placebo Buy | 377 | +0.0100% | 42.7% | +0.564 | [-0.175%, +0.266%] |
| REAL Buy | 98 | +0.0761% | 48.0% | +0.977 | [-0.142%, +0.324%] |
| placebo Strong Buy | 236 | -0.1355% | 47.5% | +0.792 | [-0.771%, +0.810%] |
| REAL Strong Buy | 11 | +1.3390% | 81.8% | +1.658 | [+0.102%, +2.711%] |

## 1a. Placebo Strong Buy: pooled mean vs. day-clustered t sign mismatch, explained

The day-clustered t-stat (+0.792) is computed from the **mean of day-means** (each trading
day counted once, regardless of how many placebo events fired that day), while the reported
mean return (-0.1355%) is the **pooled, row-weighted mean** (each event counted once). These
diverge whenever high-volume days and low-volume days have systematically different signs -
which is exactly what happens here. Full per-day breakdown (17 distinct days, 236 rows):

| day | n | mean net return |
|---|---|---|
| 2026-08-12 | 1 | +1.0979% |
| 2026-08-18 | 2 | +2.6027% |
| 2026-08-24 | 1 | -1.4134% |
| 2026-08-25 | 18 | -0.0400% |
| 2026-08-26 | 5 | -0.4115% |
| 2026-08-27 | 7 | +0.4573% |
| 2026-08-28 | 1 | +1.0930% |
| 2026-08-31 | 2 | -0.5948% |
| 2026-09-01 | 11 | +0.0389% |
| 2026-09-02 | 15 | +3.6336% |
| 2026-09-03 | 36 | -1.4257% |
| 2026-09-04 | 4 | -0.6821% |
| 2026-09-08 | 9 | -0.2268% |
| 2026-09-09 | 39 | -1.0910% |
| 2026-09-10 | 24 | +0.6945% |
| 2026-09-11 | 60 | -0.1832% |
| 2026-09-14 | 1 | +0.8403% |

**Pooled (row-weighted) mean: -0.1355%. Mean of day-means (unweighted across 17 days):
+0.2582%.** Three of the highest-volume days (Sept 3: n=36, Sept 9: n=39, Sept 11: n=60 -
135 of 236 rows, 57% of the sample) all have negative average returns, dragging the
row-weighted pooled mean below zero even though most of the 17 individual days (13 of 17)
average positive or near-zero. Day-mean std across the 17 days: 1.3449%.

## 1b. Restricted to exact-ET-hour-matched events only (1,423 of the 1,424 real events
resolved to a valid simulation; drops all any-hour-fallback events)

Fire rate:

| class | real fire rate (exact-hour subset) | placebo fire rate (exact-hour subset) |
|---|---|---|
| Buy | 55/1423 = 3.865% | 168/4045 = 4.153% |
| Strong Buy | 3/1423 = 0.211% | 80/4045 = 1.978% |

Returns (collapsed to distinct ticker+entry_ts):

| | n | mean net return | win rate | day-clustered t | bootstrap 95% CI |
|---|---|---|---|---|---|
| placebo Buy | 168 | +0.0592% | 45.8% | +1.040 | [-0.118%, +0.327%] |
| REAL Buy | 49 | +0.0681% | 49.0% | +0.029 | [-0.187%, +0.359%] |
| placebo Strong Buy | 80 | +0.0334% | 47.5% | +0.943 | [-0.784%, +1.470%] |
| REAL Strong Buy | 3 | +1.5542% | 100.0% | +1.246 | [+0.166%, +4.043%] |

Real Strong Buy support drops to n=3 in this restricted subset (matches the fire-rate math:
only 0.211% of 1,423 exact-matched real events fired Strong Buy) - too thin to read much into
beyond the raw number itself.
