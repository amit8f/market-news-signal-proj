# Form 4 insider-purchase study — pre-registered plan

Written before computing any returns. Offline research study, separate from the news-signal
live system — no live, config, or model changes.

## Pre-registered primary test (decided before seeing results)

**20-trading-day beta-adjusted forward return of voluntary (non-Rule-10b5-1) open-market
purchases (Form 4, transaction code P) in the 100-stock small-cap sample, versus the
random-date baseline.**

Everything else in this study is exploratory and is labeled as such in the report. No trading
logic is proposed as a result of this study.

## Universe

- 40 currently-tracked live-system tickers.
- 100 tickers sampled from IWM (Russell 2000 ETF) holdings as of the 2023-09-30 N-PORT
  snapshot (filed 2023-11-22), after CUSIP/name resolution, sub-$1 and <$1M-ADV filtering,
  random draw with seed=7. See `outputs/latency_test.md`/prior conversation record for the
  full resolution funnel.

## Data source

SEC DERA quarterly Insider Transactions Data Sets (`sec.gov/dera/data/form-345`), 2024 Q1
through the latest available quarter. Structured TSV tables (`SUBMISSION`, `NONDERIV_TRANS`,
`REPORTINGOWNER`), not individual filing scraping.

## Event and entry rules

- **Transaction code P only** (open-market purchase). Sales, option exercises, grants, and all
  other codes excluded.
- **Exclude Form 4/A amendments** — keep only the original filing (`DOCUMENT_TYPE == '4'`).
- **One event per filing.** If a filing has multiple P lines, sum the dollar amounts into one
  event.
- **Entry = close of the first trading day after the filing date** (`FILING_DATE` in
  `SUBMISSION.tsv`) — conservative, since a filing can land after hours and the trade date
  itself was not yet public information.
- **Forward returns at 5, 20, and 60 trading days from entry.**
- **Beta vs. SPY** estimated on the 250 trading days strictly before the filing date only — no
  look-ahead. Beta-adjusted return = stock return − beta × SPY return over the same window.
- **Delisted names:** forward return runs to the last available price rather than being
  dropped. Number of events affected by this is reported explicitly.

## Splits (exploratory, not the primary test)

- Insider role: CEO/CFO vs. director vs. other.
- Purchase size: <$50k, $50k-$500k, >$500k.
- Cluster (2+ distinct insiders at the same company within 30 days) vs. single.
- Rule 10b5-1 plan (via the `AFF10B5ONE` field, confirmed present in the DERA data set) vs.
  voluntary.
- Large-cap (the 40 tracked tickers) vs. small-cap (the 100-stock sample).

## Baseline

Random dates for the same ticker with no insider purchase (any code) within ±30 days, ~3x the
real event count, same entry/return/beta rules.

## Statistics reported for every cell

Mean, median, win rate, t-stat clustered by calendar month, bootstrap 95% CI. Event count
reported for every cell; any cell with n<30 is explicitly flagged as too thin to read.

## Also reported

- Market cap distribution of the 100-stock sample at the snapshot date.
- The 83 unresolved N-PORT holdings (out of 1,988 equity holdings), as a limitation — dropped,
  not guessed at.

## What this is not

No trading logic, no threshold selection, no recommendation. Real numbers only.
