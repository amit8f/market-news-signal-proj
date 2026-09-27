# Form 4 insider-purchase study v2 (replication) — results

Pre-registered plan: `outputs/form4_v2_plan.md`. Offline research study; no live, config, or
model changes. Built on the reusable `research/shared/` modules (`universe.py`, `bars.py`,
`corporate_actions.py`, `dera.py`, `returns.py`).

## PRIMARY TEST (pre-registered)

**20-trading-day beta-adjusted forward return of voluntary (non-10b5-1) open-market purchases
across the v2 universe (1,471 tickers, excludes the v1 100), minus the ticker-mix-matched full
eligible population baseline** (every eligible day for the same tickers outside +/-30 days of any
purchase, weighted so each ticker's eligible days sum to its event count).

| | n | mean 20d beta-adj return |
|---|---|---|
| Voluntary purchases | 5,776 | +0.001% |
| Ticker-mix-matched eligible population | 430,313 ticker-days (weighted) | -0.836% |
| **Difference (event minus population)** | | **+0.837%** |

- Month-clustered test (WLS, errors clustered by calendar month, CR1 correction, G = 30 months):
  SE 0.468%, **t = +1.790, p = 0.084**.
- Bootstrap 95% CI, resampling calendar months (10,000 draws): **[-0.048%, +1.747%]**.
- **Verdict: not significant at 5%**, though closer to the boundary than v1's original estimate -
  the CI excludes zero by only 0.048pp on the low side, and p = 0.084 is inside the range some
  would call marginal. Read as "not significant," not as "trending significant" - the
  pre-registered threshold was not met.

## SECONDARY: voluntary events alone vs. zero

n = 5,776, 30 months, mean +0.001%, median -1.371%, win rate 44.4%, month-clustered t = -0.640,
bootstrap 95% CI [-1.224%, +1.268%].

## Comparison across v1 and v2 (same underlying methodology, different universes/samples)

| | universe | n (voluntary) | baseline type | difference | t | p | 95% CI |
|---|---|---|---|---|---|---|---|
| v1 primary (as reported) | v1's 100 tickers | 505 | 3x random-date draw | +2.572% | +1.549 | 0.132 | [-0.241%, +5.846%] |
| v1 post-hoc, ticker-mix-matched population (same method as v2's primary) | v1's 100 tickers | 505 | full eligible population | +1.533% | +0.906 | 0.372 | [-1.413%, +4.910%] |
| **v2 primary** | **1,471 tickers (v1's 100 excluded)** | **5,776** | **full eligible population** | **+0.837%** | **+1.790** | **0.084** | **[-0.048%, +1.747%]** |

Same methodology, three population sizes, same direction (positive) every time, shrinking point
estimate as the sample grows (2.57% to 1.53% to 0.84%) while the t-statistic actually rises
(1.55 to 0.91 to 1.79, non-monotonic across the three because the underlying samples differ, not
strictly nested) as the standard error shrinks with more data. This pattern - a real but
small, imprecisely-estimated effect in a small sample that shrinks and stabilizes with more data
- is consistent with the v1 100-ticker estimate having been somewhat inflated by sampling noise,
which is exactly the concern the ticker-mix-matched population baseline was introduced to
address. It is also consistent with a genuine small positive effect that v2's larger sample
estimates more precisely but still does not have the power to confirm at 5%.

## Exploratory: other horizons (same primary comparison, not pre-registered)

| horizon | event mean | population mean | difference | t | 95% CI |
|---|---|---|---|---|---|
| 5d | +0.191% | -0.189% | +0.380% | +1.623 | [-0.070%, +0.822%] |
| 20d (primary) | +0.001% | -0.836% | +0.837% | +1.790 | [-0.048%, +1.747%] |
| 60d | +0.351% | -1.890% | **+2.241%** | **+2.192** | **[+0.270%, +4.178%]** |

The 60-day horizon is the one cell across both studies (v1 and v2) where the primary-style
comparison clears conventional significance. This is exploratory (the pre-registered primary is
20d) and should be read as suggestive rather than confirmatory - it was not the designated test
and is one of several horizons examined.

## Exploratory splits (v2, labeled exploratory; cells with n<30 flagged - none are this time,
smallest cell is n=177)

Each cell: own stats vs. zero (month-clustered t, bootstrap CI), and minus the population
baseline matched to that cell's own ticker mix (so, e.g., the "role=Director" population weights
eligible days only for tickers that had a Director purchase, in proportion to how many).

### 5-day

| cell | n | mean | median | win | t vs 0 | minus population | t | 95% CI (diff) |
|---|---|---|---|---|---|---|---|---|
| ALL v2 events | 5,953 | +0.171% | -0.287% | 47.5% | +0.44 | +0.366% | +1.59 | [-0.074%, +0.802%] |
| Voluntary (non-10b5-1) | 5,776 | +0.191% | -0.296% | 47.5% | +0.52 | +0.380% | +1.62 | [-0.070%, +0.822%] |
| 10b5-1 (planned) | 177 | -0.462% | -0.178% | 46.9% | -0.07 | -0.091% | -0.16 | [-1.182%, +0.969%] |
| role = CEO/CFO | 1,349 | +0.153% | -0.395% | 46.8% | -0.14 | +0.479% | +1.59 | [-0.139%, +1.045%] |
| role = Director | 3,079 | +0.467% | -0.186% | 48.7% | +1.45 | +0.591% | +2.30 | [+0.111%, +1.111%] |
| role = Other | 1,348 | -0.403% | -0.483% | 45.5% | -0.78 | -0.208% | -0.45 | [-1.181%, +0.563%] |
| size < $50k | 2,284 | +0.272% | -0.282% | 47.1% | +0.78 | +0.545% | +1.93 | [+0.017%, +1.082%] |
| size $50k-$500k | 2,448 | -0.007% | -0.391% | 46.7% | -0.36 | +0.175% | +0.58 | [-0.419%, +0.762%] |
| size > $500k | 1,044 | +0.476% | +0.023% | 50.1% | +1.17 | +0.507% | +1.66 | [-0.106%, +1.071%] |
| cluster = True | 3,880 | +0.242% | -0.287% | 47.6% | +0.77 | +0.504% | +1.86 | [-0.031%, +1.009%] |
| cluster = False | 1,896 | +0.085% | -0.313% | 47.3% | -0.34 | +0.131% | +0.49 | [-0.387%, +0.662%] |

### 20-day

| cell | n | mean | median | win | t vs 0 | minus population | t | 95% CI (diff) |
|---|---|---|---|---|---|---|---|---|
| ALL v2 events | 5,953 | -0.067% | -1.371% | 44.3% | -0.74 | +0.798% | +1.68 | [-0.120%, +1.720%] |
| Voluntary (non-10b5-1) | 5,776 | +0.001% | -1.371% | 44.4% | -0.64 | +0.837% | +1.79 | [-0.048%, +1.747%] |
| 10b5-1 (planned) | 177 | -2.265% | -1.636% | 42.9% | -1.24 | -0.498% | -0.26 | [-3.969%, +3.098%] |
| role = CEO/CFO | 1,349 | +0.236% | -1.024% | 46.5% | -0.14 | +1.643% | +2.31 | [+0.226%, +3.009%] |
| role = Director | 3,079 | +0.106% | -1.162% | 45.1% | -0.64 | +0.735% | +1.27 | [-0.384%, +1.867%] |
| role = Other | 1,348 | -0.473% | -1.893% | 40.5% | -0.33 | +0.244% | +0.39 | [-0.935%, +1.485%] |
| size < $50k | 2,284 | +0.597% | -1.114% | 45.4% | +0.32 | +1.488% | +1.94 | [+0.015%, +2.970%] |
| size $50k-$500k | 2,448 | -0.553% | -1.648% | 43.1% | -1.04 | +0.425% | +0.78 | [-0.608%, +1.515%] |
| size > $500k | 1,044 | -0.006% | -1.330% | 45.1% | -0.07 | +0.382% | +0.83 | [-0.489%, +1.292%] |
| cluster = True | 3,880 | +0.172% | -1.427% | 44.3% | -0.18 | +1.235% | +1.96 | [+0.020%, +2.485%] |
| cluster = False | 1,896 | -0.349% | -1.271% | 44.5% | -1.29 | +0.036% | +0.07 | [-0.960%, +1.015%] |

### 60-day

| cell | n | mean | median | win | t vs 0 | minus population | t | 95% CI (diff) |
|---|---|---|---|---|---|---|---|---|
| ALL v2 events | 5,953 | +0.090% | -2.915% | 43.3% | -0.33 | +1.999% | +1.99 | [+0.056%, +3.895%] |
| Voluntary (non-10b5-1) | 5,776 | +0.351% | -2.770% | 43.7% | -0.11 | +2.241% | +2.19 | [+0.270%, +4.178%] |
| 10b5-1 (planned) | 177 | -8.417% | -7.571% | 30.5% | **-2.60** | **-5.912%** | **-2.13** | **[-11.123%, -0.184%]** |
| role = CEO/CFO | 1,349 | +1.011% | -3.046% | 44.2% | +0.09 | +3.803% | +2.76 | [+1.194%, +6.518%] |
| role = Director | 3,079 | +0.829% | -2.251% | 44.5% | +0.06 | +2.527% | +2.31 | [+0.370%, +4.636%] |
| role = Other | 1,348 | -1.401% | -3.734% | 41.5% | -0.63 | +0.007% | +0.00 | [-3.788%, +3.979%] |
| size < $50k | 2,284 | +2.192% | -1.059% | 47.0% | +1.44 | +3.808% | +3.43 | [+1.595%, +5.920%] |
| size $50k-$500k | 2,448 | -0.092% | -3.656% | 43.0% | -0.32 | +2.377% | +1.60 | [-0.340%, +5.358%] |
| size > $500k | 1,044 | -2.639% | -5.475% | 38.3% | -0.86 | -1.536% | -1.00 | [-4.355%, +1.574%] |
| cluster = True | 3,880 | +0.795% | -2.562% | 44.3% | +0.37 | +3.216% | +2.51 | [+0.712%, +5.643%] |
| cluster = False | 1,896 | -0.559% | -3.029% | 42.6% | -0.66 | +0.276% | +0.20 | [-2.407%, +3.123%] |

**Worth flagging (exploratory, not the primary test):** planned (10b5-1) purchases show a
significant *negative* 60-day result (-5.91%, t = -2.13) with a much less thin sample than v1's
(n=177 here vs. n=17 in v1, where the same cell was strongly positive but explicitly flagged
THIN). This is a real reversal of direction between the two studies on the one cell where v1's
result was least trustworthy - consistent with v1's 10b5-1 finding having been a small-sample
artifact, though v2's own n=177 result should also not be over-read as a single exploratory cell
among many. CEO/CFO and cluster-purchase cells are the more consistently positive exploratory
splits at 20d and 60d, but none of these were pre-registered.

## Data pipeline notes

- Universe: 1,475 tickers from the same 2023-09-30 IWM snapshot (excluding v1's 100); 1,471
  resolved to a CIK (4 unresolved: CARM, NBN, TOWN, HIFS - dropped, not guessed at).
- DERA extraction (2024 Q1 - 2026 Q2, 10 quarters): 6,089 distinct filings (events); 925 of the
  1,471 tickers have at least one purchase event. 5,954/6,089 events scored (135 had no tradable
  bar after the filing date). Truncated (delisting/halt-gap) events: 4 at 5d, 10 at 20d, 35 at
  60d - out of thousands, a small fraction, handled the same way as v1 (return measured to the
  last available price, not dropped).
- Events per year: 2024 total 2,351 (voluntary 2,298); 2025 total 2,685 (voluntary 2,592); 2026
  (through June) total 1,053 (voluntary 1,022). Voluntary vs. planned overall: 5,912 / 177.
- Bars: SIP daily, `adjustment=all` passed explicitly on every request (no repeat of the v1
  default-adjustment mistake) via `research/shared/bars.fetch_daily_bars`, which has no default
  value for `adjustment` at all.
- Population construction validated against the row-by-row event scoring at the 5,777 real
  voluntary-event anchors that matched: mean absolute difference 0.059pp, correlation 0.997
  (slightly less exact than v1's 0.027pp/1.000 validation, at 10x the scale - still strong
  agreement).

## Conclusions and next hypotheses

- **Primary verdict is unchanged from the checkpoint: not significant.** The pre-registered 20-day
  test gives +0.84pp (t = +1.79, p = 0.084, bootstrap 95% CI [-0.05pp, +1.75pp]). The pre-registered
  threshold (p < 0.05) was not met.
- **The point estimate has shrunk monotonically as the sample grew**, under the same methodology:
  +2.57pp (v1, n=505) -> +1.53pp (v1, re-scored with v2's population method) -> +0.84pp (v2, n=5,776).
  This is consistent with v1's original estimate having been partly sampling noise, though it is
  also consistent with a genuine small positive effect that a larger sample estimates more precisely
  but still can't confirm at 5%. Either way, the honest reading is that the effect, if real, is
  smaller than v1 alone suggested.
- **Two exploratory results are hypotheses for a future pre-registered test, not findings from
  this study:**
  1. The 60-day horizon result (+2.24pp, t = +2.19) is the one cell where the primary-style
     comparison clears significance, in both v1 and v2. Hypothesis for a future study: "the
     20d test is under-powered relative to a 60d horizon for this effect" - to be pre-registered
     as the primary test on independent (post-2026Q2) data, not retrofitted onto data already
     examined here.
  2. The negative 60-day result for planned (10b5-1) purchases (-5.91pp, t = -2.13, n=177) reverses
     v1's thin (n=17), positive-leaning result on the same split. Hypothesis for a future study:
     "planned purchases underperform at 60 days" - also to be pre-registered and tested on
     independent data before being treated as a real effect.
  Both are exploratory outputs of this study, surfaced because they were large and reasonably
  powered here, not because they were the designated test. Neither should inform any live
  threshold, model, or trading decision.

## No trading logic

Descriptive study only; no thresholds, signals, or recommendations follow from these results.
