# Form 4 insider-purchase study v2 (replication) — pre-registered plan

Written before computing any returns. Offline research study; no live, config, or model
changes. Replicates the v1 methodology (`outputs/form4_study_plan.md`,
`outputs/form4_study.md`) on a non-overlapping universe, with one methodology change to the
baseline, made and pre-registered before seeing v2 results.

## Universe

All eligible tickers from the same 2023-09-30 IWM N-PORT snapshot (filed 2023-11-22), same
resolution pipeline (DERA name match primary, OpenFIGI `exchCode=US`-only fallback) and same
filters as v1: price >= $1, SIP ADV >= $1M (Sept 2023), dual share classes deduped to one ticker.
Eligible pool: **1,575** tickers. **Excluding the 100 v1 tickers: 1,475** tickers for v2. The v1
100 are carried through as a labeled comparison cell only (see Exploratory), not part of the v2
primary universe.

## Period

2024 Q1 through the latest available DERA quarter at run time.

## Event rules (identical to v1)

- Transaction code P only; exclude Form 4/A amendments (`DOCUMENT_TYPE=='4'` only).
- One event per filing; multiple P lines on one filing summed to one dollar amount.
- Entry = close of the first trading day strictly after `FILING_DATE`.
- Returns at 5, 20, 60 trading days from entry.
- Beta vs. SPY: OLS slope over the 250 trading days strictly before the filing date.
- Zero-volume bars dropped before entry/exit selection (halted/dormant listings are not real
  tradable prices); a >15-calendar-day gap between remaining bars is treated as a delisting
  (forward lookup capped there, not jumped across).
- **SIP daily bars fetched with `adjustment=all` passed explicitly** on every request (the v1
  mistake - relying on Alpaca's undocumented default - is not repeated; see
  `research/shared/bars.py`).

## PRE-REGISTERED PRIMARY TEST

**20-trading-day beta-adjusted forward return of voluntary (non-10b5-1) open-market purchases,
minus the ticker-mix-matched full eligible population baseline** - every eligible day (any
trading day for that ticker outside +/-30 days of any purchase filing for that ticker, with the
same halt-gap/zero-volume/adjustment rules applied), weighted so each ticker's eligible days sum
to that ticker's number of voluntary-purchase events, exactly comparator (c1) from the v1 rev. 2
post-hoc section.

**This baseline definition was chosen after seeing the v1 results**, specifically to remove the
sampling noise inherent in v1's original ~3x-random-draw baseline (v1's draw-based primary
difference was +2.57pp; the same ticker-mix-matched full-population comparator, computed
post-hoc on the same v1 data, gave +1.53pp - a lower estimate, because the actual 1,400-draw
baseline mean itself was noisier than the full population it was sampled from). Using this
definition as v2's *pre-registered* primary test is therefore itself informed by v1 - it is not
an independent confirmation of v1's specific point estimate, but it is a methodology improvement
decided and written down here before any v2 return is computed, so the v2 primary test itself is
a fair, non-cherry-picked pre-registration on the v2 data.

**Statistics:** month-clustered t-statistic (OLS with an event indicator, errors clustered by
calendar month, CR1 small-sample correction) and a bootstrap 95% CI resampling calendar months
(10,000 draws) - identical inference machinery to v1.

## Exploratory (labeled as such, not the primary test)

- Same splits as v1: insider role (CEO/CFO vs. director vs. other), purchase size (<$50k,
  $50k-$500k, >$500k), cluster (2+ distinct insiders at the same company within 30 days) vs.
  single, Rule 10b5-1 (`AFF10B5ONE`) vs. voluntary.
- 5-day and 60-day horizons, same comparator.
- **The primary comparison rerun on the v1 100-ticker sample**, as a direct within-study
  comparison cell (not a hold-out, not blinded - the v1 100 were already fully analyzed in v1).
- All cells report n, and any cell with n<30 is flagged as too thin to read.

## Data pipeline (reusable modules)

Built under `research/shared/` for reuse by a later whole-market project, rather than as
one-off scratch scripts:

- `universe.py` - IWM N-PORT snapshot parsing, CUSIP/name resolution (DERA + OpenFIGI), price/ADV
  filtering, dual-class dedup.
- `bars.py` - SIP daily bar fetch with pagination and an explicit, required `adjustment`
  argument (no silent default), local caching.
- `corporate_actions.py` - Alpaca corporate-actions fetch and split/spin-off inventory, shared
  with (but independent of) the live system's `BarCache` fix.
- `dera.py` - DERA quarterly Form 3/4/5 data set download/extraction and P-line/event
  construction (code filtering, amendment exclusion, one-event-per-filing aggregation, role/size/
  cluster/10b5-1 classification).
- `returns.py` - the entry/exit/beta/forward-return engine, halt-gap and zero-volume handling,
  and the month-clustered-t / month-resampling-bootstrap inference functions.

## Checkpoint

After the universe is resolved and bars are fetched, funnel counts and event counts (total,
voluntary, per year) are reported before any return is computed, per instruction.

## No trading logic

Descriptive study only; no thresholds, signals, or recommendations follow from these results.
