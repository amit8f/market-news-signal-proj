# Form 4 insider-purchase study — results (rev. 2, corrected)

Pre-registered plan: `outputs/form4_study_plan.md` (unchanged). Offline research study; no live,
config, or model changes. This revision replaces the first version of this file; corrections to
that version are listed under "Bug fixes and corrections".

## PRIMARY TEST (pre-registered): event-minus-baseline difference

**20-trading-day beta-adjusted forward return of voluntary (non-10b5-1) open-market purchases in
the 100-stock small-cap sample, minus the random-date baseline (same universe).**

| | n | mean 20d beta-adj return |
|---|---|---|
| Voluntary purchases, small-100 | 505 | -0.299% |
| Random-date baseline, small-100 | 1,400 | -2.872% |
| **Difference (event minus baseline)** | | **+2.572%** |

- Test statistic: OLS of the 20d return on an event indicator, standard errors clustered by
  calendar month (CR1 small-sample correction, G = 30 months): SE 1.661%, **t = +1.549, p = 0.132**.
- **Bootstrap 95% CI, resampling calendar months** (events and baseline drawn together by month,
  10,000 draws): **[-0.241%, +5.846%]**.
- **Pre-registered verdict: NOT significant.** The difference is +2.57pp, t = 1.55, p = 0.13, and
  the month-resampled CI includes zero. This verdict is final and is not changed by anything in
  the post-hoc section below.
- The primary statistic (pooled difference with month-clustered errors) was fixed in the analysis
  code before it was run.

Same comparison at the other horizons (exploratory): 5d difference +0.265% (t = +0.727,
CI [-0.438%, +0.993%]); 60d difference +1.989% (t = +1.025, CI [-1.604%, +5.779%]).

## SECONDARY: real events alone vs. zero (not the pre-registered comparison)

| | n | months | mean | median | win rate | month-clustered t | bootstrap 95% CI |
|---|---|---|---|---|---|---|---|
| Voluntary purchases, small-100 (20d beta-adj) | 505 | 30 | -0.299% | -0.462% | 47.9% | -0.074 | [-3.239%, +3.005%] |
| Random-date baseline, small-100 (20d beta-adj) | 1,400 | 30 | -2.872% | -2.345% | 40.4% | -5.457 | [-3.996%, -1.767%] |

## Before / after the data fixes (primary cells, 20d beta-adjusted)

| | events mean | baseline mean | baseline t vs 0 |
|---|---|---|---|
| Rev. 1 (raw bars + >3x jump detector) | -0.279% | -2.905% | -5.58 |
| Rev. 2 (`adjustment=all`, jump detector removed) | -0.299% | -2.872% | -5.46 |

The fix moved the baseline by 0.03 percentage points. The negative baseline is not an
un-adjusted-split artifact (details below).

## Bug fixes and corrections (logged)

1. **Bars were fetched with Alpaca's default `adjustment=raw`.** The study's fetch script
   (`fetch_bars.py`) passed no `adjustment` parameter. Confirmed empirically: the default output
   is identical to explicit `raw` (NKLA closes 0.351 to 9.37 across its 2024-06-25 1-for-30
   reverse split; AVGO 1700.67 to 171.42 across its 10-for-1). All SIP daily bars (140 tickers +
   SPY, plus IWM for the sanity checks) were re-fetched with `adjustment=all` (splits and
   dividends, so returns are total-return style and SPY is treated identically). Fetch window
   extended to 2026-09-22. The >3x / <1/3x jump detector was removed as a split fix. The
   zero-volume-bar filter and the >15-calendar-day halt-gap filter were kept. Everything (returns,
   betas, baseline, statistics) was rerun.
2. **Impact of the split issue was small.** There are 8 splits among the 140 tickers in the study
   window (table below). Only 2 of 1,655 baseline events (AVGO, WMT) and 0 of 602 real events had a
   split inside their 20d return window (60d: 2 baseline, 1 real, NKLA). The old jump detector had
   already covered the large ratios (NVDA, DM, NKLA, AVGO, NFLX, RPT); it missed WMT's 3-for-1
   and HON's 1-for-2, hence the tiny exposure.
3. **Correction to rev. 1: "12 delisted-affected events" was wrong.** Rev. 1 bars ended 2026-08-20,
   so late filings had their 60d window cut off by the end of my data, and I mislabeled those as
   delistings (and explained AVGO/BA as split-adjustment inconsistencies; that explanation was
   wrong, they were data-end truncation). With bars through 2026-09-22: real events truncated at
   any horizon = 0. Baseline events truncated: 5 at 20d (3 stopped trading, 2 halt-gap; tickers
   COOP, HI), 33 at 60d (15 data-end, 12 stopped trading, tickers COOP, HI, LPRO, SATS; 6
   halt-gap). Four filings were not scoreable at all (DTC x4, 2026-03-31/04-01: no tradable bar
   after the filing date).
4. **Zero-volume / halt-gap handling (from rev. 1, retained):** DTC, OABI, PRME, CZFS have frozen
   zero-volume stretches; DTC reactivates on 2025-07-18 at an unrelated price level (a +22,347%
   daily move remains in the bars and is capped by the halt-gap rule). Forward lookups past a gap
   are treated like a delisting (last real price).
5. **Primary test reframed** to the pre-registered comparison (event minus baseline,
   month-clustered, bootstrap over calendar months); "real events alone vs zero" moved to
   secondary.

Earlier data-integrity fixes (unchanged): SIP instead of IEX for ADV filtering; CUSIP-to-ticker
resolution rebuilt (DERA name match primary, OpenFIGI `exchCode=US` only as fallback; 83 of 1,988
equity holdings unresolved and dropped, a universe-completeness limitation).

## Sanity checks (requested)

**1. Baseline raw return vs SPY over the same windows; betas** (20d, means unless stated)

| group | n | raw return | SPY, same windows | beta mean / median | beta x SPY | beta-adj return |
|---|---|---|---|---|---|---|
| Baseline small-100 | 1,400 | -0.925% (median -0.341%) | +1.687% (median +1.916%) | 1.172 / 1.106 | +1.947% | -2.872% |
| Baseline large-40 | 255 | +2.853% | +1.960% | 1.020 / 0.984 | +2.014% | +0.839% |
| Voluntary events small-100 | 505 | +0.895% (median +1.341%) | +1.122% | 1.088 / 1.066 | +1.194% | -0.299% |

**2. Level of the baseline vs. how the universe actually performed** (Jan 2024 to Jun 2026)

- Equal-weighted average 20d return of the 100-stock sample: **+0.879%** (equal weight by ticker;
  pooled ticker-days +1.165%, median +0.391%; 59,579 ticker-days) vs **IWM +1.551%** and SPY
  +1.594% over the same period. The 40 tracked tickers: +1.857%.
- Market exposure alone (sample mean beta 1.172 x SPY +1.594%) implies about +1.87% per 20 days,
  so the sample lagged its beta-implied return by roughly 1 percentage point per 20 days.
- The decomposition of the baseline level and the alternative comparators are in the post-hoc
  section below (not pre-registered).

**3. Splits.** 8 splits among the 140 tickers, all inside the study window:

| ticker | universe | ex-date | ratio |
|---|---|---|---|
| WMT | large-40 | 2024-02-26 | 3-for-1 |
| NVDA | large-40 | 2024-06-10 | 10-for-1 |
| DM | small-100 | 2024-06-11 | 1-for-10 reverse |
| NKLA | small-100 | 2024-06-25 | 1-for-30 reverse |
| AVGO | large-40 | 2024-07-15 | 10-for-1 |
| NFLX | large-40 | 2025-11-17 | 10-for-1 |
| RPT | small-100 | 2025-12-31 | 1-for-6 reverse |
| HON | large-40 | 2026-06-29 | 1-for-2 reverse (HONA spin-off the same day) |

Events with a split inside their return window: real 0 (5d, 20d) and 1 (60d, NKLA) of 602;
baseline 2 (AVGO, WMT) of 1,655 at every horizon. A residual-jump scan of the adjusted bars still
shows large single-day moves in small caps (after DTC: DM +99% on 2025-03-25, UTZ +89% on
2026-07-21, OPEN +80% on 2025-09-11, VRRM -71% on 2026-05-27); only DTC, OPEN, PRME, and NKLA were
individually inspected against raw bars (DTC artifact; OPEN and PRME genuine rallies; NKLA split).

## POST-HOC / NOT PRE-REGISTERED

Everything in this section was designed after seeing the primary result. It is interpretation
support only and does not change the pre-registered verdict above.

**(a) Equal weighting of months.** Averaging the month-level differences (each month weighted
equally, 30 months) gives +3.149%, t = +2.977, versus the pre-registered pooled version's +2.572%,
t = +1.549. The two disagree on significance, which indicates the result depends on how sparsely
populated months are weighted.

**(b) Why the baseline level is so low (small-100, entry next-bar close, +20 bars, means per 20
trading days).**

| step | raw 20d | beta-adj 20d |
|---|---|---|
| Ordinary days, weighted by baseline draw counts | +0.603% | -1.188% |
| Same, excluding +/-30 days around insider purchases (the baseline's eligible days) | -0.219% | -2.071% |
| Actual baseline draws (n=1,400) | -0.925% | -2.872% |
| Ordinary days, weighted by voluntary-event counts | +0.786% | -0.990% |
| Actual voluntary events (n=505) | +0.895% | -0.299% |

The sample itself lagged its beta-implied return (about -1.0 to -1.2% per 20 days); excluding the
+/-30-day windows around insider purchases removes relatively strong periods (about -0.9pp more);
the remaining -0.8pp is the gap between the eligible-day expectation and the 1,400 actual draws
(sampling variation with heavily overlapping windows and uneven ticker weights: TCBI 112 draws,
BUSE 94, FLWS 87, ACDC 72).

**(c) Estimates against the full eligible non-event population** (every ticker-day outside +/-30
days of any purchase filing for that ticker, not a 3x random draw, so the sampling noise of the
baseline draw is removed). Each ticker-day's 20d beta-adjusted return is computed with the same
construction as the study (entry = next-bar close, +20 bars, beta from the trailing 250 days
strictly before the anchor). A vectorised implementation was validated against the study's own
values at the 505 real event anchors (mean absolute difference 0.027pp, correlation 1.000). The
halt-gap rule is applied by dropping windows that cross a gap of more than 15 calendar days rather
than capping them. Inference is the same as the primary test: weighted least squares with
month-clustered errors, bootstrap CI resampling calendar months (10,000 draws). Voluntary events:
n = 505, mean -0.299%.

| comparator population | ticker-days | population mean (bootstrap 95% CI) | event minus population | month-clustered t | p | bootstrap 95% CI of difference |
|---|---|---|---|---|---|---|
| (c1) Eligible non-event days, ticker mix matched to the event tickers (each ticker's days weighted to its number of voluntary events; 65 tickers) | 30,403 | -1.832% (-3.275%, -0.313%) | **+1.533%** | +0.906 | 0.372 | [-1.413%, +4.910%] |
| (c2) All eligible non-event days of all 100 sample tickers, equal weight per ticker-day | 50,428 | -0.917% (-1.935%, +0.084%) | +0.618% | +0.404 | 0.689 | [-1.966%, +3.707%] |
| (c3) All days including the +/-30-day windows, ticker mix matched (the earlier "ordinary-day benchmark") | 39,542 | -0.990% | +0.691% | +0.493 | 0.626 | [-1.686%, +3.496%] |

With the baseline's draw noise removed, the ticker-mix-matched difference (c1) is +1.53pp rather
than +2.57pp and remains statistically indistinguishable from zero (t = +0.91); the other two
comparators give smaller differences (+0.62pp, +0.69pp), also not significant. The population mean
in (c1) (-1.83%) is higher than the actual 1,400-draw baseline mean (-2.87%), consistent with the
draw-noise component in (b).

## Universe, data, and events

- Source: SEC DERA Insider Transactions Data Sets, 2024 Q1 to 2026 Q2. 606 distinct filings with
  code-P purchases after excluding Form 4/A; 602 scored (filings 2024-01-24 to 2026-06-16).
- Universe: 40 tracked tickers + 100 sampled from IWM's 2023-09-30 N-PORT holdings (filed
  2023-11-22, seed 7 after resolution and liquidity filters).
- Entry = close of the first trading day after `FILING_DATE`; horizons 5/20/60 trading days;
  beta = OLS slope vs SPY over the 250 trading days strictly before the filing date (median 249
  days used; none under 100); baseline = random dates at least 30 days from any purchase filing
  for that ticker, about 3x events per ticker (1,655 scored).
- Sample price at snapshot (n=100): min $1.03, 25th pct $8.86, median $20.40, 75th pct $49.00,
  max $265.66. Market cap (n=89; 11 tickers lack a retrievable shares-outstanding fact, one $0
  artifact excluded): min $120M, 25th pct $559M, median $1.01B, 75th pct $2.50B, max $6.94B.
- Limitation: 83 of 1,988 equity holdings (4.2%) could not be resolved to a ticker and were
  dropped, not guessed at.

## Exploratory splits (labeled exploratory; the pre-registered primary test is above)

Each cell: own statistics vs. zero, and cell minus the pooled baseline (all universes pooled;
"large_40" and "small_100" cells use their own universe's baseline). t-statistics are clustered by
calendar month; CIs resample calendar months; cells with n<30 are flagged. Because these are many
comparisons, none should be read as a confirmed effect.

### 5-day
| cell | n | months | mean | median | win | t vs 0 | 95% CI vs 0 | minus baseline | t | 95% CI (diff) |
|---|---|---|---|---|---|---|---|---|---|---|
| ALL real events | 602 | 30 | -0.089% | -0.305% | 46.2% | +0.46 | [-0.792%, +0.728%] | +0.375% | +0.89 | [-0.416%, +1.265%] |
| large_40 | 85 | 27 | -0.286% | -0.271% | 48.2% | -1.08 | [-1.778%, +1.252%] | -0.936% | -1.10 | [-2.547%, +0.693%] |
| small_100 | 517 | 30 | -0.056% | -0.322% | 45.8% | +0.67 | [-0.807%, +0.840%] | +0.610% | +1.33 | [-0.234%, +1.591%] |
| role=CEO_CFO | 98 | 28 | -0.910% | -1.026% | 38.8% | -1.17 | [-2.148%, +0.575%] | -0.447% | -0.65 | [-1.682%, +1.057%] |
| role=Director | 325 | 30 | -0.342% | -0.353% | 46.2% | +0.29 | [-1.001%, +0.303%] | +0.122% | +0.31 | [-0.691%, +0.871%] |
| role=Other | 179 | 28 | +0.820% | +0.060% | 50.3% | +1.48 | [-0.632%, +2.494%] | +1.283% | +1.59 | [-0.157%, +3.025%] |
| size=<$50k | 214 | 30 | +0.729% | -0.255% | 47.7% | +1.79 | [-0.464%, +2.233%] | +1.193% | +1.79 | [+0.075%, +2.696%] |
| size=$50k-$500k | 247 | 30 | +0.077% | -0.322% | 45.3% | +0.63 | [-0.833%, +1.125%] | +0.540% | +0.98 | [-0.534%, +1.647%] |
| size=>$500k | 141 | 26 | -1.621% | -0.413% | 45.4% | -1.74 | [-2.972%, -0.294%] | -1.157% | -1.51 | [-2.680%, +0.277%] |
| cluster=True | 396 | 30 | +0.243% | -0.108% | 48.7% | +0.93 | [-0.624%, +1.225%] | +0.707% | +1.47 | [-0.192%, +1.733%] |
| cluster=False | 206 | 30 | -0.728% | -0.995% | 41.3% | +0.32 | [-1.568%, +0.376%] | -0.264% | -0.49 | [-1.241%, +0.892%] |
| 10b5_1=True (planned) **THIN (n<30)** | 17 | 9 | +9.658% | +3.913% | 64.7% | +1.37 | [+0.159%, +22.571%] | +10.122% | +1.74 | [+0.231%, +24.359%] |
| 10b5_1=False (voluntary) | 585 | 30 | -0.372% | -0.353% | 45.6% | -0.16 | [-0.976%, +0.256%] | +0.091% | +0.26 | [-0.592%, +0.790%] |
| baseline small_100 | 1400 | 30 | -0.666% | -0.755% | 43.3% | -2.93 | [-1.150%, -0.159%] | — | — | — |
| baseline large_40 | 255 | 30 | +0.650% | +0.084% | 50.2% | +1.37 | [-0.101%, +1.445%] | — | — | — |

### 20-day
| cell | n | months | mean | median | win | t vs 0 | 95% CI vs 0 | minus baseline | t | 95% CI (diff) |
|---|---|---|---|---|---|---|---|---|---|---|
| ALL real events | 602 | 30 | +0.577% | -0.405% | 48.3% | +0.34 | [-2.386%, +3.739%] | +2.877% | +1.86 | [+0.128%, +5.900%] |
| large_40 | 85 | 27 | -0.464% | -1.205% | 44.7% | -1.17 | [-3.239%, +2.197%] | -1.303% | -0.66 | [-5.460%, +2.172%] |
| small_100 | 517 | 30 | +0.749% | -0.252% | 48.9% | +0.71 | [-2.559%, +4.391%] | +3.620% | +2.01 | [+0.453%, +7.173%] |
| role=CEO_CFO | 98 | 28 | -1.698% | -1.784% | 40.8% | -1.84 | [-5.680%, +2.585%] | +0.602% | +0.29 | [-3.066%, +4.717%] |
| role=Director | 325 | 30 | +0.614% | +0.072% | 50.5% | +0.84 | [-1.399%, +2.572%] | +2.914% | +2.75 | [+0.889%, +4.919%] |
| role=Other | 179 | 28 | +1.756% | -0.266% | 48.6% | +0.80 | [-3.929%, +8.771%] | +4.056% | +1.27 | [-1.324%, +10.789%] |
| size=<$50k | 214 | 30 | +2.429% | +0.556% | 55.1% | +1.19 | [-1.590%, +7.263%] | +4.729% | +2.19 | [+1.047%, +9.372%] |
| size=$50k-$500k | 247 | 30 | +1.294% | -0.125% | 49.0% | +0.23 | [-1.853%, +4.601%] | +3.594% | +2.17 | [+0.631%, +6.758%] |
| size=>$500k | 141 | 26 | -3.489% | -3.186% | 36.9% | -0.58 | [-7.563%, +0.519%] | -1.189% | -0.54 | [-5.482%, +3.065%] |
| cluster=True | 396 | 30 | +0.889% | +0.323% | 51.0% | +0.11 | [-2.805%, +4.860%] | +3.189% | +1.61 | [-0.244%, +7.052%] |
| cluster=False | 206 | 30 | -0.022% | -1.223% | 43.2% | +0.71 | [-2.407%, +2.490%] | +2.278% | +1.90 | [+0.072%, +4.711%] |
| 10b5_1=True (planned) **THIN (n<30)** | 17 | 9 | +32.237% | +16.922% | 82.4% | +1.42 | [+3.252%, +76.044%] | +34.537% | +1.82 | [+4.721%, +79.050%] |
| 10b5_1=False (voluntary) | 585 | 30 | -0.343% | -0.666% | 47.4% | -0.47 | [-3.042%, +2.552%] | +1.957% | +1.35 | [-0.518%, +4.797%] |
| baseline small_100 | 1400 | 30 | -2.872% | -2.345% | 40.4% | -5.46 | [-3.996%, -1.767%] | — | — | — |
| baseline large_40 | 255 | 30 | +0.839% | -0.929% | 46.3% | +0.56 | [-1.371%, +3.307%] | — | — | — |

### 60-day
| cell | n | months | mean | median | win | t vs 0 | 95% CI vs 0 | minus baseline | t | 95% CI (diff) |
|---|---|---|---|---|---|---|---|---|---|---|
| ALL real events | 602 | 30 | -0.845% | -3.232% | 40.5% | -0.55 | [-4.571%, +3.069%] | +2.637% | +1.62 | [-0.340%, +5.792%] |
| large_40 | 85 | 27 | +0.443% | -3.227% | 41.2% | -0.10 | [-5.969%, +8.357%] | -2.030% | -0.52 | [-10.018%, +5.323%] |
| small_100 | 517 | 30 | -1.057% | -3.377% | 40.4% | -0.64 | [-5.354%, +3.592%] | +3.510% | +1.91 | [+0.197%, +7.129%] |
| role=CEO_CFO | 98 | 28 | -1.774% | -8.005% | 33.7% | -0.73 | [-8.593%, +5.826%] | +1.708% | +0.48 | [-4.797%, +8.952%] |
| role=Director | 325 | 30 | -0.354% | -2.452% | 43.4% | +0.07 | [-2.892%, +2.275%] | +3.128% | +2.29 | [+0.489%, +5.730%] |
| role=Other | 179 | 28 | -1.228% | -7.601% | 39.1% | -0.17 | [-8.240%, +6.483%] | +2.254% | +0.69 | [-3.676%, +8.759%] |
| size=<$50k | 214 | 30 | +1.234% | -2.964% | 42.5% | +0.10 | [-4.369%, +7.038%] | +4.716% | +1.87 | [-0.153%, +9.601%] |
| size=$50k-$500k | 247 | 30 | +0.754% | -2.964% | 43.7% | +0.83 | [-3.672%, +5.345%] | +4.236% | +1.87 | [+0.148%, +8.582%] |
| size=>$500k | 141 | 26 | -6.801% | -10.404% | 31.9% | -1.62 | [-13.495%, -0.047%] | -3.319% | -1.00 | [-9.825%, +2.935%] |
| cluster=True | 396 | 30 | -2.009% | -5.005% | 37.1% | -1.16 | [-6.899%, +3.062%] | +1.474% | +0.65 | [-2.643%, +5.732%] |
| cluster=False | 206 | 30 | +1.392% | -0.835% | 47.1% | +1.27 | [-1.620%, +4.635%] | +4.874% | +3.33 | [+2.202%, +7.986%] |
| 10b5_1=True (planned) **THIN (n<30)** | 17 | 9 | +46.530% | +39.188% | 88.2% | +2.22 | [+11.263%, +76.356%] | +50.013% | +3.41 | [+13.980%, +81.442%] |
| 10b5_1=False (voluntary) | 585 | 30 | -2.222% | -3.412% | 39.1% | -1.59 | [-5.655%, +1.334%] | +1.260% | +0.74 | [-1.923%, +4.575%] |
| baseline small_100 | 1400 | 30 | -4.567% | -5.354% | 35.6% | -3.33 | [-7.054%, -2.047%] | — | — | — |
| baseline large_40 | 255 | 30 | +2.473% | -0.789% | 48.6% | +0.63 | [-2.606%, +7.782%] | — | — | — |

## No trading logic

Descriptive study only; no thresholds, signals, or recommendations follow from these results.
