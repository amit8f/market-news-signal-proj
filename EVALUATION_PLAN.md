# Evaluation Plan - Shadow Mode (pre-registered before data collection)

Status: FROZEN on 2026-08-23, before any VM-collected shadow data is reviewed.
Any change to this document after data collection starts must be logged with a
timestamped justification, and resets the evaluation clock.

## 1. What is being evaluated

Long-only calibrated alerts (Buy / Strong Buy) from champion_xgb_4class +
isotonic calibration + frozen thresholds (Sell 0.44 / Buy 0.29 / Strong Buy 0.21),
ATR(1x) stops, 120-minute horizon, 24-ticker slice universe.

Sell/short side is fully suppressed and is OUT OF SCOPE until it has its own fix
and passes an equivalent backtest gate on its own.

Severity field is informational-only and plays no role in sizing or gating.

## 2. Data source of truth

Only signals collected by the Oracle VM service (`data/live/signals.db` on the VM,
periodically copied for analysis). Local or manual runs NEVER advance the
evaluation clock.

## 3. Primary endpoint

Day-clustered mean NET excess-vs-SPY return per trade:

- cluster unit = entry day (ET trading day)
- statistic = mean over days of that day's mean trade excess return
- uncertainty = day-level bootstrap (B=2000 resamples) 95% percentile CI
- one-sided p-value = share of bootstrap means <= 0

## 4. Minimum sample before the decision test

Both must hold:
- >= 40 independent ET trading days with at least one fired long signal
- >= 300 total fired Buy/Strong-Buy signals

Descriptive looks are allowed anytime, but NO promotion/rejection decisions
before the minimum sample is reached.

### 4a. Burn-in policy (fixed before any VM data exists)

There is NO discretionary burn-in discard. Every VM-collected trading day counts
from the very first service cycle, because models, thresholds, calibration and
features are frozen before deployment - day 1 is statistically exchangeable with
day N, and deleting early days would create a cherry-picking knob.

The ONLY exclusions are mechanical, pre-registered data-quality gates applied
uniformly per day, never by judgment after seeing outcomes:

- A VALID ACTIVE DAY requires: (a) service uptime >= 95% of regular-session
  minutes for that ET trading day, AND (b) that day's fired signals have
  finnhub_quote entry share >= 80% (i.e., proxy-entry share <= 20%), AND
  (c) the day's cycle-error rate < 5%, AND (d) no single universe ticker
  failed to be polled (Finnhub error, per the `poll_failures` table) on more
  than 10% of that day's cycles.
- Days failing these gates are excluded from BOTH the day count and the signal
  count, and are listed by date in every review output (no silent drops).
- Known one-off warm-up effects (first-cycle bar pulls, cache priming) are
  handled BY THESE GATES, not by hand-deleting a "warm-up week".

**Amendment, 2026-08-26:** Gate (d) added after diagnosing a reproducible
per-cycle Finnhub failure pattern (Aug 24-25) that silently dropped the same
4 of 40 tickers on every cycle without ever raising an exception - `poll_news()`
catches per-ticker failures and continues, so the affected cycles registered
as fully successful and passed gate (c)'s cycle-error rate undetected. Gate
(d) closes that specific blind spot: a partial, per-ticker coverage gap that
is invisible to an exception-based cycle-error count. This is a data-quality/
validity gate governing which days are eligible to count toward the sample -
it does not touch the model, calibration, thresholds, or the Section 5
decision rule, and it is not a response to any observed outcome/return data
(it was diagnosed from ingestion/coverage logs, before any promotion decision
was made). Per Section 7, it therefore does not reset the evaluation clock.
It is not retroactive: already-logged signals are untouched, and it only
governs which days are countable going forward (and in any future replay of
already-collected data).

Consequence: once the thresholds are reached, the formal test uses ALL valid
days/signals accumulated so far - ramp-up included - unless specific dates were
excluded by the mechanical gates above (each exclusion shown in the review log).

## 5. Exact decision rule at target sample

PROMOTE to "real-signal candidate" (still not autopilot; proceeds to sizing
research) iff ALL of:

1. Bootstrap 95% CI lower bound > 0 for day-clustered excess mean
2. Bootstrap P(mean<=0) < 0.05
3. Day-clustered t-statistic >= 2.0 with sign consistent with positive edge
4. Calibration drift check: per actionable class, top-reliability-bin
   |empirical frequency - predicted| <= 0.10 within the evaluation window
5. Sanity bands: stopped-trade share within 10%..60%; proxy-entry share < 20%

If short of the bar at minimum sample: KEEP WATCHING for one more 4-week block.
Never lower thresholds, never widen classes, never relax the CI/p requirements.
Maximum 3 continuation blocks; after that, declare insufficient evidence,
stop collection, and redesign (features/horizon/universe) before any retest.

## 6. Per-class precision skepticism (Strong Buy lesson)

Holdout SB exact-label precision was 81% vs 34.9% OOF expectation in a single
3-week window. Rule: treat early shadow-mode per-class precision as regime luck
until supported by independent days. Report per-class outcome stats in 20-active-
day blocks with Wilson intervals; a class claim requires two consecutive blocks
whose intervals overlap the pooled estimate. No per-class sizing or threshold
tuning based on fewer than 40 active days.

## 7. Data-quality gates (checked every review)

- VM service uptime across market hours >= 95%
- Missed-cycle rate < 5% (cycle errors / total cycles)
- Per-ticker poll coverage: no single universe ticker missing from more than
  10% of a day's cycles (added 2026-08-26, see Section 4a amendment)
- Entry-source mix: finnhub_quote share reported; last_regular_close_proxy
  share must stay < 20% or entries are flagged unreliable for that period
- Any model/threshold/config change freezes results and RESETS the clock
  (exception: critical bug fixes, logged, affected days excluded)

**Critical bug fix, logged per the Section 7 exception, 2026-08-26:** added
429-specific retry-with-backoff (up to 2 retries, 5-15s wait, honoring
`Retry-After` when Finnhub sends it) around the per-ticker Finnhub call in
`poll_news()` (`news_signal/live/run_loop.py`). Root cause: `poll_news()` had
no retry logic at all, so a brief, recurring external contention window on
the shared Finnhub API key (VM log timestamps show it recurring roughly every
30 minutes, lasting a few minutes each time - not this service's own rate
limiter, and not a duplicate process, both ruled out) reliably 429'd the same
4 of 40 tickers (NFLX, T, CMCSA, TSLA) without ever raising a cycle-level
exception, so the affected cycles registered as fully successful. This
qualifies as the Section 7 exception: it restores intended per-ticker news
coverage and touches nothing in the model, calibration, thresholds, or the
Section 5 decision rule. Per the exception clause, results are NOT reset;
**2026-08-24 and 2026-08-25 are excluded as affected days** from the day and
signal counts (independent of, and in addition to, whatever Section 4a's
mechanical gates would already exclude them for).

**Critical bug fix, logged per the Section 7 exception, 2026-08-28:** removed
`poll_news()`'s client-side recency filter (previously discarded any item
whose *stated* Finnhub publish timestamp was more than ~12 minutes old) and
replaced it with the existing persistent `seen_news`/`filter_new_hashes()`
hash-dedup as the sole poll-time gate, reordered to run before relevance
tagging. Added a new decision-time staleness check in `process_items()`
enforcing the frozen `labels.entry_max_delay_minutes` (15 min) against
`published_utc`, with rejections logged to a new `stale_rejections` table for
visibility (mirroring `poll_failures`). Root cause: real-world Finnhub
syndication/indexing lag routinely exceeded the filter's own window, so items
were being judged stale and dropped before ever reaching `process_items()` -
confirmed directly via VM journal logs (a real NVDA article on 2026-08-27
that should have cleared the filter at two consecutive cycles by its own
stated timestamp, but didn't) and via a live sanity check showing observable
lag between an item's stated timestamp and its retrievability. This qualifies
as the Section 7 exception: it restores intended news capture and touches
nothing in the model, calibration, thresholds, or the Section 5 decision
rule. Confirmed working live at deploy time: two real items were correctly
rejected by the new staleness cap and logged to `stale_rejections` - an
AVGO/Marvell headline at 257.7 minutes old and an AMZN headline at 259.9
minutes old, both well past the 15-minute cutoff.

Per the exception clause, results are NOT reset; **every day from initial
deployment through 2026-08-27 inclusive is excluded as affected** - not just
the previously-excluded 2026-08-24/25 (429 issue) and 2026-08-27 (originally
flagged for the empty-table investigation). VM journal logs directly confirm
a uniform 100% zero-candidate-item rate across every day the service had a
stable active session (2026-08-25: 143/143 real cycles; 2026-08-26: 144/144
real cycles; 2026-08-27: 144/144 real cycles - corrected here from an earlier
"288/288" figure, which double-counted each cycle against two separate log
lines that both matched the original grep pattern), plus 2026-08-24
(partial/unstable, additionally hit by an unrelated crash bug,
`Cannot set a DataFrame without columns to the column relevance_tier`, active
15:01-15:57 UTC that day). 2026-08-23 had no live operation at all. **The
evaluation clock effectively restarts from 2026-08-28**, the date this fix
was deployed and confirmed capturing and correctly gating real candidate
items live.

**Genuine threshold change, 2026-09-01 - NOT a Section 7 bug-fix exception,
clock RESET per the general Section 7 rule:** post-deploy monitoring of the
2026-08-28 fix found the live staleness gate rejecting essentially 100% of
relevant items (114/114 in the 2026-08-28..08-31 VM journal, ages 52min-17h,
none anywhere near the 15-minute cutoff). Root cause, confirmed directly
against code and historical data: `labels.entry_max_delay_minutes` (15 min,
still frozen and unchanged - see below) and live's staleness check were
measuring two different things under the same config value. Offline,
`compute_events()` (`news_signal/labels/forward_returns.py`) computes `delay`
as the gap between a headline's stated `published_utc` and the next tradeable
minute bar (or, for after-hours news, the next session open) - a bar-rounding
quantity, confirmed against `data/processed/milestone_events.parquet`'s
`delay_sec` column (n=22,693: mean 11.8s, median 0s, max 533s/~8.9min). It is
not, and structurally cannot be, a measure of retrieval lag, because the
offline ingest (`news_signal/ingest/finnhub_news.py:pull_all_news()`) is a
one-shot historical bulk pull over a fixed date range - there is no
poll-and-observe step to lag in the first place. Live's staleness check instead
measures wall-clock time between a headline's stated `published_utc` and when
the live poller first observed it (real Finnhub syndication/retrieval lag) -
an unrelated quantity the 15-minute value was never fit to or calibrated
against. Reusing the offline value live was an apples-to-oranges definitional
error, not primarily evidence that Finnhub's live lag is unusually severe
(though the lag is real and independently confirmed by VM logs).

Fix: added a new, separate config key, `live.max_retrieval_lag_minutes: 60`
(`config/config.yaml`), and switched the live staleness check
(`news_signal/live/run_loop.py`, `process_items()`) to use it instead of
`labels.entry_max_delay_minutes`. **`labels.entry_max_delay_minutes` (15 min)
is untouched** and continues to govern only the offline/backtest event
construction pipeline (`compute_events()`), exactly as before. The new 60-minute
value is explicitly a provisional starting point with no empirical basis yet -
picked to unblock signal collection, not derived from data. A new table,
`retrieval_lag` (`ts_utc, ticker, headline, published_utc, lag_minutes,
rejected_stale`), now logs the retrieval lag for every item that reaches the
staleness check - fired, silent, and stale-rejected alike, not just rejections
- so that once enough live data accumulates, this threshold can be
recalibrated the same evidence-based way the other frozen thresholds in this
project were set (quantile label edges, per-class precision floors), rather
than left as a guess. Tested end-to-end locally (`--inject-demo` plus a
synthetic 5/30/90-minute-old item run against `process_items()`): a 30-minute-old
item, which would have been rejected under the old 15-minute reuse, now
correctly clears the gate and reaches a decision, while a 90-minute-old item is
still correctly rejected and logged to both `stale_rejections` and the new
`retrieval_lag` table. Deployed to the VM at **2026-09-01T08:51:49 UTC**
(confirmed via `systemctl status` at deploy time).

Unlike the two entries above, this is filed as a genuine threshold change, not
the Section 7 critical-bug-fix exception: it changes which events are eligible
to be scored and logged, not merely a defect in getting already-intended
behavior to work. Per Section 7's general rule, **results are RESET and the
evaluation clock restarts from 2026-09-01T08:51:49 UTC**, the confirmed deploy
time above. All 2026-08-28..08-31 data collected under the old (mis-scoped)
staleness gate remains excluded, as already established above, and no signal
was fired live under the old gate in that window in any case (0 rows in
`signals`). Post-deploy monitoring the same day (2026-09-01) confirmed the new
gate working as intended: of 172 items reaching the staleness check between
deploy and 17:44 UTC, 47 (27.3%) now pass (vs. 0% under the old reused
15-minute value) and reach a full decision, while 125 (72.7%) are still
correctly rejected as stale. All 47 that passed were scored Sell (42,
suppressed per `live.suppress_classes`) or Neutral (5, below the calibrated
precision floor) - zero Buy/Strong Buy signals fired on this first day under
the new gate.

**Genuine data-source correction, 2026-09-02 - NOT a Section 7 bug-fix
exception, clock RESET per the general Section 7 rule:** manual review of the
first day of real signal traffic under the corrected retrieval-lag gate above
found `entry_price` frozen at an identical value across signals fired 35-70
minutes apart on active large-cap tickers (NVDA pinned at 218.20 across five
signals 14:45-15:20 UTC; TSLA pinned at 358.02 across five signals
13:55-15:06 UTC), despite `entry_source` recording a successful live call each
time (not the `last_regular_close_proxy` fallback). Root cause, confirmed by
pulling Alpaca 1-minute bars for the same tickers/window: the true intraday
price moved substantially in that span (NVDA 215.455-218.58 across 92 distinct
closes in 116 bars; TSLA 353.73-360.355 across 103 distinct closes), and the
Alpaca close nearest each signal timestamp differed from the frozen Finnhub
value by up to $1.00 (TSLA, 14:45 UTC: Finnhub 358.02 vs Alpaca 359.015).
Finnhub's free-tier `/quote` endpoint (`fetch_quote()` in
`news_signal/live/run_loop.py`) was returning stale/cached data rather than a
live tick for these symbols, not a display quirk - a real data-quality defect
in the entry-price source that would have corrupted every fired signal's
recorded fill price and its downstream ATR-based stop (`stop_price =
entry_price * (1 - stop_atr_multiple * atr)`) and paper P&L
(`simulate_exit()`), had a Buy/Strong Buy actually fired under it.

Fix: `fetch_quote()` now sources `entry_price` from Alpaca's latest-trade
endpoint (`GET /v2/stocks/{ticker}/trades/latest`, same `alpaca_key_id` /
`alpaca_secret_key` credentials and `ingestion.alpaca_feed` already used for
bars) instead of Finnhub's `/quote`. `entry_source` for a live-sourced price is
now recorded as `"alpaca_trade"` instead of `"finnhub_quote"`; the
`"last_regular_close_proxy"` fallback path (used when the live call fails) is
unchanged. `scripts/shadow_status.py`'s proxy-rate calculation was updated to
match the new source string (a local-only reporting-script change, not subject
to Section 7 per CLAUDE.md). Verified the underlying Alpaca trade feed
genuinely moves tick-to-tick, not just at 1-minute bar granularity: pulled
individual trade prints for NVDA and TSLA over a 5-minute window
(2026-09-01T14:00-14:05 UTC) and found 29/50 and 28/50 distinct prices
respectively, several within the same second. Tested end-to-end via
`--inject-demo` against the live model artifacts: the injected NVDA signal
fired with `entry_source="alpaca_trade"`, `entry_price=217.97` (matching
Alpaca's contemporaneous latest trade), and a correctly-computed
`stop_price=216.19`. Local `data/live/signals.db` was backed up before testing
and restored to its exact pre-test state (3 signals) afterward. Deployed to
the VM at **2026-09-02T14:01:21 UTC** (confirmed via `systemctl status` at
deploy time).

This is filed as a genuine data-source/threshold change, not the Section 7
critical-bug-fix exception, on the same reasoning as the retrieval-lag entry
above: it changes the recorded value a downstream calculation (stop price,
paper P&L) depends on, not merely a defect in getting already-intended
behavior to work. Per Section 7's general rule, **results are RESET and the
evaluation clock restarts from 2026-09-02T14:01:21 UTC**, the confirmed deploy
time above. This is a separate, later reset from the retrieval-lag entry's
2026-09-01T08:51:49 UTC - that fix was already live on the VM for about a day
before this one deployed (confirmed via the populated `retrieval_lag` table
and 47 passing signals in the 2026-09-01 VM pull), not a simultaneous change,
so the two entries have distinct reset timestamps rather than sharing one. No
Buy/Strong Buy signal has ever fired live under the old Finnhub-quote entry
price (0 rows with `class_name` in `Buy`/`Strong Buy` and `status='fired'` in
any VM pull to date), so no previously-collected fired-signal data is affected
by this specific defect.

**Critical bug fix, logged per the Section 7 exception, 2026-09-03:** a
pre-deploy security audit (ahead of first `git init` for this project) found
`FINNHUB_API_KEY` present in plaintext in the VM's systemd journal and in the
`error` column of `poll_failures` in every VM-pulled copy of `signals.db`
(`signals_full.db`, `signals_review.db`, `signals_today.db` - 92 occurrences
each). Root cause: Finnhub's `/company-news` and `/stock/profile2` endpoints
take the API key as a URL query parameter (`token=...`); when a request fails
(e.g. the recurring 429/503 contention already documented above), `str()` of
the resulting `requests` exception embeds the full request URL, key included,
and that string was being printed to stdout (captured by the journal) and
persisted verbatim into `poll_failures.error` via `poll_news()` in
`news_signal/live/run_loop.py`. Separately, `notify()`'s Telegram call embeds
`TELEGRAM_BOT_TOKEN` directly in the URL path - the same class of defect,
currently dormant only because `live.notify_enabled` stays `false` (Section
7b).

Fix: added `redact_secrets()` to `news_signal/config.py`, masking any of
`FINNHUB_API_KEY`, `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`,
`TELEGRAM_BOT_TOKEN` wherever they appear in a string. Both Finnhub request
functions (`news_signal/ingest/finnhub_news.py`) now catch
`requests.exceptions.RequestException` (the base class - covers `HTTPError`,
`ConnectionError`, `Timeout`, not just the one case already seen live),
sanitize `e.args` in place, and re-raise the same exception object so its type
and attributes (e.g. `.response`, used by `poll_news()`'s 429-retry check) are
preserved but every future `str(e)` is already clean. Applied the same
redaction, defense-in-depth, at every other exception-to-print site in
`run_loop.py` (`notify`, `market_is_open`, `BarCache.get`, `refresh_spy_daily`,
`poll_alpaca_news`, `poll_news`), even where Alpaca's header-based auth was
already confirmed safe. A comprehensive grep of every `requests.get/post` and
`raise_for_status()` call in `news_signal/` and `scripts/` (8 total) confirmed
no other call site embeds a secret in a URL. Verified live, not just read:
deliberately triggered a real Finnhub 401 with a corrupted key and confirmed
the real key substring is absent from the resulting exception string, both in
isolation and through `poll_news()`'s full failures list (what actually
reaches `poll_failures.error`).

This qualifies as the Section 7 exception: it changes what gets logged on an
error path, not which events are eligible to be scored, and touches nothing in
the model, calibration, thresholds, or the Section 5 decision rule. Per the
exception clause, results are NOT reset by this fix on its own. It shipped to
the VM in the same restart as the dual-source architecture change below
(2026-09-03T17:40:36 UTC, see that entry for the deploy circumstance and the
crash-loop this exposed) - that change's general-rule reset already covers
this timestamp, so no separate reset applies here regardless.

**Genuine architecture change, 2026-09-03 - NOT a Section 7 bug-fix exception,
clock RESET per the general Section 7 rule:** background -
a separate investigation (`outputs/finnhub_retrieval_lag_finding.md`, factual
finding only, no decision) found Finnhub free-tier retrieval lag averaging
154.6 minutes median (n=418, full window since the 2026-09-01 fix), with 55%
of items arriving more than 2 hours after publish - already exceeding the
strategy's 120-minute forward-return horizon before any staleness threshold is
even applied. A parallel investigation found Alpaca News (Benzinga-sourced,
same existing Alpaca credentials, no new API access needed) delivering the
same kind of company-tagged headlines at 0.5-3.5 minute live-poll latency, but
at roughly 14% of Finnhub's raw volume over the same 2-day/42-ticker window,
with 5 of 42 tickers (`ABBV, COST, MCD, NFLX, T`) seeing zero Alpaca coverage
in that window - materially thinner, not a like-for-like replacement.

Decision: add Alpaca News as a second source scored through the **same live
decision path** as Finnhub (relevance -> sentiment -> feature construction ->
classify -> calibrate -> threshold-decide), tagged per-signal by a new
`news_source` column (`"finnhub"` or `"alpaca"`), rather than replacing
Finnhub or treating Alpaca as log-only. This lets fire rate, class
distribution, and behavior be compared by source over a real live window
before any replace/supplement decision is made. `live.notify_enabled` stays
`false` throughout for both sources - nothing alerts regardless of source
(see Section 7b).

Pre-wiring offline sanity check (per Section 7 discipline - verify before this
touches live data): ran the 268 already-pulled Alpaca items (2026-09-01/02,
42-ticker universe) through the real relevance tagger, FinBERT sentiment
scorer, and `build_event_frame()` feature construction. 123/268 passed the
tier-1/2 relevance filter; all 123 produced a valid feature frame with zero
exceptions and zero build failures (mean NaN fraction 6.2%, max 18.9%, no row
over 20%). Running the resulting features through the live champion model +
calibration + thresholds produced a non-degenerate class distribution (86
Sell, 19 Neutral, 18 Buy, 0 Strong Buy) - nothing grossly broken. One
observation carried into the dedup design below: 13 of the 18 would-fire items
were NVDA, several sharing `prob_calibrated` to 6 decimal places (expected,
since same-bar technical/regime features are shared across headlines landing
in the same 1-minute bar) and drawn from Benzinga listicle/roundup content
rather than distinct company events - the same clustering shape flagged
earlier for Finnhub-only signal review.

Cross-source duplicate handling (explicitly designed, not left implicit, per
the plan for this change): **both sources are scored independently - nothing
is suppressed.** Every item, regardless of source, gets its own row in
`signals`. A new `dedup_group_id` column tags every signal with
`md5(ticker + time-bucket)`, where the bucket width is
`live.dedup_window_minutes` (new config key, default 15 minutes) - any two
signals for the same ticker landing in the same bucket, from either source or
the same source, share a group id. This is a best-effort correlation label for
after-the-fact analysis (collapsing likely-duplicate stories when computing
metrics), not a gate: a labeling false-positive (two unrelated same-ticker
headlines sharing a bucket) or false-negative (a genuine duplicate landing in
adjacent buckets) is low-cost precisely because nothing is dropped based on
it. This also gives visibility into same-source clustering (e.g. the NVDA
pattern above), not just cross-source duplication.

Implementation: `news_signal/live/db.py` - `signals` table gains `news_source`
and `dedup_group_id` columns (`ensure_news_source_columns()` migrates
pre-existing databases via `ALTER TABLE`, since `CREATE TABLE IF NOT EXISTS`
only applies to brand-new tables); `insert_signal()` updated to write both.
`news_signal/live/run_loop.py` - `process_items()` takes a `news_source`
parameter (default `"finnhub"`, preserving `--inject-demo`'s existing
behavior), includes it in the `seen_news` dedup hash (`news_source|ticker|
headline|datetime`, so an identically-worded headline from both sources is
still scored independently rather than the second copy being silently
suppressed by the pre-existing single-source hash), and computes
`dedup_group_id` per item. `alpaca_items_to_news_shape()` reshapes
`poll_alpaca_news()`'s output (which now also captures `summary` and `url`,
previously omitted since that poll was log-only) to match the item shape
`process_items()` expects. `run_cycle()` now calls `process_items()` twice per
cycle - once for Finnhub items tagged `"finnhub"`, once for the same-cycle
Alpaca poll tagged `"alpaca"` - summing `n_fired` across both; the raw
`alpaca_news_seen` latency-logging table from the earlier additive-poll change
is unchanged and still populated from the same poll result.

Tested end-to-end locally: `data/live/signals.db` backed up
(`signals.db.bak_pretest4`) before testing. Ran a full forced cycle (market
was closed at test time, so a small local harness called `run_cycle()`
directly, bypassing only the market-hours gate - no pipeline logic bypassed)
against the real live universe and artifacts: 227 Finnhub items polled, 106
passed relevance, 1 NVDA item cleared the retrieval-lag gate and **fired**
(`news_source="finnhub"`, `dedup_group_id="ecc2c36cf418"`); 1 Alpaca item
(AVGO) was polled, passed relevance, and was scored silent/sell-suppressed
(`news_source="alpaca"`, `dedup_group_id="c78a79feb9c4"`). Verified directly
against the database: pre-existing rows retained `news_source=NULL` after the
migration (no corruption of prior data), both new rows correctly tagged, and
`entry_source` unaffected (`alpaca_trade` on both, per the 2026-09-02 fix
above). Restored `data/live/signals.db` to its exact pre-test state (3
signals, original 6-table schema) afterward.

**Follow-up investigation of the NVDA clustering flagged in the sanity check,
before deploy authorization:** traced the 16 (not 13 - corrected from the
earlier estimate) would-fire NVDA items in the 268-item sanity sample against
the raw Alpaca articles. Two distinct findings, not one:

1. The repeated identical `prob_calibrated` values are **not duplicate/
   syndicated stories** - the 16 items are editorially distinct (different
   angles: an Anthropic/Lambda cloud deal, a chip redesign report, an SB
   Energy IPO filing, a MediaTek partnership, analyst commentary, a market
   roundup, etc.) spanning up to 15 hours apart, far outside any reasonable
   dedup window. Traced the actual cause in `build_technical_features()`/
   `compute_hourly_indicators()` (`news_signal/features/technical.py`):
   technical features come from the last COMPLETED regular-session hourly bar,
   so every pre-market headline on the same calendar day inherits the
   identical stale bar (and `dist_from_vwap_pct` is explicitly `NaN`
   pre-market) regardless of true publish-time spacing - confirmed directly
   against the data (all Sept-1 pre-market items before the 13:30 UTC open
   share `prob_calibrated=0.298302`; the value changes exactly at the first
   post-open item, 14:20 UTC). **`dedup_group_id` is not the right tool for
   this and was not extended to cover it** - collapsing these would wrongly
   merge genuinely distinct stories. This is a pre-existing property of the
   shared feature pipeline, not an Alpaca-specific defect - it applies equally
   to any pre-market Finnhub headline - just made more visible here because
   Benzinga publishes much more pre/after-market volume than Finnhub's mix.
   Documented as a finding for the record; no code change made for it as part
   of this entry.

2. Separately, using Alpaca's `symbols` array (ground truth Finnhub's
   per-ticker-scoped pull never exposes directly): **11 of the 16 (69%)**
   fired items tag 2+ tickers, several tagging 6-7, one tagging 33 (a broad
   "Stock Market Today" roundup covering sector/index ETFs) - NVDA is
   incidental to most of its own would-fire sample, not the dedicated
   subject. `relevance_tier()` only checks whether the ticker/company name
   appears in the headline text and has no concept of how many other
   companies an article covers. Decision (reviewed before deploy, per
   explicit instruction): tag, don't gate - added an `n_symbols` column to
   `signals`, populated from the article's `symbols` array length for
   Alpaca-sourced signals only (`NULL` for Finnhub, which has no equivalent
   ground truth), for use as an analysis filter later (e.g. restricting to
   `n_symbols<=2` when comparing fire rate/class distribution to Finnhub).
   Nothing is excluded from scoring or firing based on this.

Re-tested end-to-end after adding `n_symbols` (same backup discipline,
`signals.db.bak_pretest5`): forced cycle fired 3 signals; verified directly
against the database that every Finnhub-sourced row has `n_symbols=NULL` and
the one Alpaca-sourced row correctly recorded `n_symbols=3` matching its
actual multi-company content (a Haleon/Walmart/Target retail-shelf-space
story). Restored `data/live/signals.db` to its exact pre-test state
afterward.

This is filed as a genuine architecture change, not the Section 7
critical-bug-fix exception: it changes which events are eligible to be scored
(a second source now reaches `classify()`/`decide()`) and what a `signals` row
means (must now be read alongside `news_source`), not merely a defect in
getting already-intended behavior to work. Per Section 7's general rule,
**results are RESET and the evaluation clock restarts from 2026-09-03T17:40:36
UTC** (confirmed via `systemctl status` at deploy time) - the timestamp the
service came up successfully running this code, not when it first reached the
VM (see deploy-circumstance note and crash-loop entry immediately below).

Deploy circumstance: this reached the VM unintentionally, carried along inside
`run_loop.py` by a separate same-day deploy of the Finnhub/Telegram
secret-redaction fix (`news_signal/config.py`'s new `redact_secrets()`, applied
throughout `run_loop.py` and `news_signal/ingest/finnhub_news.py` - see the
crash-loop entry below for how this was caught) - `run_loop.py` had been
carrying this already-validated dual-source code locally since the sanity
check and end-to-end tests documented above, and both changes landed in the
same sync since they touched the same file. Reviewed after the fact and
confirmed as the intended outcome, not something to roll back: the feature was
already fully validated (offline sanity check, end-to-end local tests, the
NVDA-clustering and listicle follow-up investigation, all documented above)
and had this entry drafted and waiting. Per that review, this is being treated
as a genuine, deliberate go-live rather than an accidental deploy to be
reverted - logged here as such rather than as an incident. The
secret-redaction fix that rode along with it is a Section 7 critical-bug-fix
candidate in its own right (it doesn't touch scoring, thresholds, or the
decision path - only what gets written to logs/`poll_failures.error` on
error), but since it shipped in the same file at the same moment as this
general-rule reset, it doesn't need a separate reset entry; its own
before/after verification is documented in session history (redaction proven
against a real triggered Finnhub 401, and end-to-end through `poll_news()`'s
failures list).

**Crash-loop preceding the 2026-09-03T17:40:36 UTC restart above - resolved
with real journal evidence, gate NOT violated, today NOT excluded:** the
accidental carry-along described above meant that at some point before
17:40:36 UTC, `run_loop.py` reached the VM with a
`db.ensure_news_source_columns()` call that `news_signal/live/db.py` didn't
yet define, crashing on every `main()` startup (`AttributeError`) before
`run_cycle()` was ever reached - i.e. pure downtime under systemd's
`Restart=always`/30s backoff, not corrupted or partial data, since the crash
happens before any poll or scoring step.

Pulled directly from the VM journal: first crash **17:28:40 UTC**, last crash
17:39:18 UTC, ten further restart attempts each still crashing
(17:35:07-17:39:48 UTC, ~31s apart, consistent with the 30s backoff), then the
successful restart at **17:40:36 UTC** that finally had the matching `db.py`.
**Crash-loop duration: 17:40:36 - 17:28:40 = 716 seconds (11m56s)**, entirely
within today's regular session (13:28:40-13:40:36 ET, well inside 9:30
AM-4:00 PM ET - confirmed via direct UTC-4 conversion, not assumed).

Gate check against Section 7's "VM service uptime across market hours >= 95%":
today's session is 13:30-20:00 UTC = 390 minutes (23,400s). 716s / 23,400s =
3.06% downtime -> **96.94% uptime, above the 95% floor - the gate is not
violated.** Secondary check against the <5% missed-cycle-rate gate: at the
configured 120s poll interval, a ~390-minute session implies roughly 195
expected cycles; 716s of downtime implies roughly 6 missed cycles, ~3.08% -
also under 5%. (This second figure is a config-based estimate from the poll
interval, not a literal count of today's `[cycle]` journal lines, which
weren't pulled - the 96.94% uptime figure above is the one backed by exact
timestamps and is sufficient on its own to clear the gate.)

**Conclusion: neither Section 7 gate is tripped by this crash-loop. Today
(2026-09-03) is NOT excluded** - unlike the 2026-08-24 through 08-27
incidents above, which involved multi-day, near-100%-failure outages, this
was an ~12-minute gap fully covered by the uptime margin.

**Operational restart, 2026-09-03T17:45:26 UTC - NOT a Section 7 change, no
clock reset:** the Finnhub API key was rotated (following the leak
investigation above) and the service restarted to pick up the new value via
`.env`. This is a pure credential swap: no model, calibration, threshold, or
decision-logic file changed, and nothing about which events are eligible to
be scored or how they're classified is affected. Per Section 7's own scope
("model/threshold/config change" - a credential is none of these), this does
not reset the evaluation clock. Logged for the record as a brief operational
restart (confirmed via `systemctl status` at restart time), same as any other
service restart that isn't itself a change-freeze event.

**Diagnostic instrumentation added, 2026-09-04 - drafted, not yet deployed, no
clock reset:** investigating an unresolved live anomaly found in a VM-pulled
copy of `signals.db`: 5 signals (all NVDA, `ts_utc` 17:30:00-18:08:00 UTC on
2026-09-03, all strictly after the 17:40:36 UTC dual-source deploy above, so
not pre-migration legacy rows) have `news_source`, `dedup_group_id`, and
`n_symbols` all NULL, despite every other ticker in the same window being
tagged correctly. (Originally found as 4 rows, `ts_utc` 17:45:15-18:08:00;
re-checked and a 5th, `signal_id` 279 at `ts_utc` 17:30:00, was found sharing
the same ticker, `status=silent`/`suppress_reason=sell_side_suppressed`, and
lack of explanation - note `signal_id` 279 was still written to the database
*after* `signal_id` 278 despite its earlier `ts_utc`, i.e. this is retrieval
lag on an older headline arriving in a later poll cycle, not evidence this
row predates the others in real time.) Ruled out, with evidence, over several
rounds: legacy/
pre-migration data (timestamps postdate the deploy); per-row variation within
a single `process_items()` call (`news_source` is a call-level argument, not
recomputed per row; `dedup_group_id` is a pure per-row hash of `ticker` +
time-bucket with no dependency on prior iterations or cache; neither can be
`None` under the code that computes them); a separate/older insert path
(exactly one `INSERT INTO signals` exists anywhere in the repo or either
deploy tarball, and both already include all three columns); a stale/older
version actually running on the VM (refuted directly: `run_loop.py`/`db.py`
pulled live off the VM diff byte-for-byte identical to the local working
copies - zero differences); shared cache state across same-ticker items in
one cycle (`BarCache.get()` is the only cross-iteration shared object in the
loop, and it feeds `entry_price`/`stop_price`/feature-building only, never
`news_source`/`dedup_group_id`/`n_symbols`); and an external writer (VM
command history, Python history, cron, systemd timers, and other unit files
all checked clean; no PID-overlap gap at either 2026-09-03 restart). **Root
cause not yet found** - all mechanisms checked against the actual, confirmed-
identical running code are structurally incapable of producing this, and no
external cause was found either.

Rather than continue guessing, added durable, per-call evidence capture so a
recurrence is caught live instead of reconstructed after the fact: a new
`signal_insert_log` table in `run_loop.py` (following the existing
`poll_failures`/`stale_rejections`/`retrieval_lag` pattern - live-only
diagnostic tables stay local to `run_loop.py`, not `db.py`'s canonical
schema) and a new `_record_signal_insert()` call immediately before every
call to `db.insert_signal()` in `process_items()`, persisting the exact
kwargs dict (all 17 fields, including `news_source`/`dedup_group_id`/
`n_symbols`) with its own `logged_at_utc` timestamp. This is diagnostic-only:
it adds observability and changes nothing about which events are scored,
what features/probabilities/calibration are computed, or how `decide()`
thresholds fire - so per Section 7's scope ("model/threshold/config change"),
this does not reset the evaluation clock even once deployed. Smoke-tested
locally via `--inject-demo`: table created correctly, one row logged with the
full expected field set (`news_source='finnhub'`,
`dedup_group_id='2a8211527be0'`, `n_symbols=None`). **Not yet deployed** -
per instruction, will ship bundled with whatever the next real change to
`run_loop.py` ends up being, rather than as its own deploy.

**Correction, 2026-10-01 - no clock reset:** the "not yet deployed" status
above was wrong. `signal_insert_log` has been **live since the
2026-09-09T13:07:29 UTC deploy**: it was carried along inside `run_loop.py`
by the calendar-staleness critical-bug-fix deploy (and re-synced again by the
2026-09-14 deploy). Evidence: VM-pulled `signals_sept10.db` and
`signals_sept17.db` both contain the table, with the first row at
`logged_at_utc` 2026-09-09T13:32:35 UTC (25 minutes after that deploy) and
455 rows by 2026-09-17; the live schema matches the local code exactly. As
stated above, it is diagnostic-only, so per Section 7's scope this does not
reset the evaluation clock.

Re-checked for recurrence (2026-09-04): no signal after `signal_id` 279/the
2026-09-03 17:30:00-18:08:00 window shows a NULL `news_source`. **The
anomaly appears contained to that one Sept 3rd window - 5 affected signals
total, not an ongoing issue** - though this is an observational check against
`signals` itself, not yet the stronger, purpose-built evidence
`signal_insert_log` will provide once deployed. Root cause remains unresolved
regardless; this note only updates the count and confirms no further
occurrences since.

**Feature-parity check run for the first time, 2026-09-05 - no clock reset:**
`scripts/check_feature_parity.py` (compares live `build_event_frame()` output
against training-time features stored in `milestone_events.parquet`, per
`CLAUDE.md`'s Commands section) had never actually been executed. Running it
hit an immediate crash - `KeyError: 'ticker'` from
`df.groupby("ticker", group_keys=False).apply(...)` - caused by a pandas 3.0
behavior change (grouping column no longer passed into the applied callable
by default; local venv runs pandas 3.0.5). Fixed with a one-line,
behavior-equivalent replacement of the sampling logic
(`df.sample(frac=1, random_state=3).drop_duplicates(subset="ticker",
keep="first")` - same "one random row per ticker, seed=3" semantics). This is
a local-only, read-only reporting script that never runs as part of the live
service, so per `CLAUDE.md`'s explicit carve-out it does not qualify as a
Section 7 change regardless of outcome - logged here for the record only.
Result after the fix: 24 tickers checked, 0 with meaningful drift on every
strict `FEATURE_COLS` feature (all `strict-max-rel-diff 0.00e+00`).

**Known low-priority data-hygiene issue, 2026-09-05 - not fixed, not urgent:**
the same parity run's `SOFT_COLS` output (`sector_mean_mom5d`,
`sector_rel_mom5d` - printed for visibility, excluded from the script's
pass/fail tally) shows real, non-zero drift between live and training-time
values for several tickers, including sign flips (e.g. PFE, PG). Root cause:
`peer_loader` in the live path reads the same local bar CSVs used for
day-to-day trading, which have grown past the historical snapshot the
training-time parquet was originally built from, so a 5-day sector-peer
momentum window computed "live" today covers different calendar days than
the one baked into the frozen training features. Both affected columns rank
low in feature importance (`outputs/model_report.txt`: `sector_mean_mom5d`
0.165, `sector_rel_mom5d` 0.153, well below the top technical block), and the
strict-feature parity check above is otherwise clean, so this is logged as a
known issue worth fixing eventually (e.g. by pinning `peer_loader` to a fixed
historical window) rather than something requiring immediate action.

**Recalibration planning sketch, 2026-09-08 - PLANNING ONLY, NOT AUTHORIZED,
NO EXECUTION:** documented here for the record while the zero-Buy/Strong-Buy
anomaly is still under investigation, per explicit instruction that this is a
plan, not a change. As of 2026-09-08: 186 events since the last deploy, zero
Buy/Strong Buy, vs. an ~8.73% expected rate from the training-period holdout
(P~4x10^-8 under that rate). This spans two trading sessions separated by the
Labor Day gap - confirmed via journal PID tracking that the service ran
continuously as the same process (PID 106830, since the 2026-09-03T17:45:26
restart) across that gap, so it is a fresh trading day but *not* a fresh
process; some weight against a live in-memory-state theory is separately
provided by the earlier 18/19 offline-recompute agreement, which reloads
artifacts fresh with no live-process memory involved. Root cause (live bug vs.
genuine regime shift) is not yet conclusively determined - this sketch exists
so that if/when it is, the scope of what recalibration would require is
already thought through rather than decided reactively.

Scope decision to make first if this is pursued: recalibrate-only (refit
isotonic calibration + thresholds via `run_phase5.py` against current-regime
data, keep the existing champion model and frozen label-edge definitions) vs.
full retrain (fresh label thresholds via `make_labels.py` + model refit via
`run_phase4.py`). These are different-sized Section 7 events - recalibrate-
only is the more surgical fix if the feature-outcome relationship is
unchanged but the input feature *distribution* has shifted (consistent with
the clean `check_feature_parity.py` result logged above: same pipeline,
possibly different inputs); full retrain is the bigger undertaking, needed if
the labels themselves (what forward-return quantile a given event lands in)
would differ under current conditions.

What recalibrate-only would require:
1. Fresh calibration data with matured 120-min forward returns (`run_phase5.py`
   is the only script permitted to write `calibration.pkl` /
   `alert_thresholds.json` / `severity_regressor.json` - hand-editing or
   partially replicating its logic is out of scope).
2. Minimum sample size - the original fit used an embargoed holdout of
   n=3197 across ~3 weeks (Strong Buy support alone was only 262). Shadow
   mode has been running since 2026-09-01, ~1 week of real trading (~300
   events total including today) - likely too small on its own for an
   independently-collected fresh sample without also drawing on the
   original offline dataset.
3. Leakage-safe integration - if shadow-collected events are blended into
   the training pool rather than treated as a separate fresh sample, the
   purged walk-forward CV / embargo discipline (`news_signal/models/
   splitting.py`) must be preserved exactly; shadow events, being
   chronologically newest, would most naturally extend the holdout tail
   rather than fold into train.
4. Threshold re-selection - `alert_thresholds.json`'s precision-floor
   threshold selection is fit together with calibration in `run_phase5.py`,
   not independently adjustable after the fact.

What full retrain would additionally require: re-running the full offline
pipeline (`run_milestone.py` build stage -> `run_phase4.py` Optuna retune/
retrain) on an extended dataset including the shift period, plus re-
verifying `check_feature_parity.py` and the leakage guards still hold
against the new data window.

Section 7 consequences either way: this is explicitly a threshold/
calibration/model change, not a bug fix - it would not qualify for the
"affected days excluded" exception; it resets the evaluation clock outright,
and the pre-registered promotion test would restart from zero at the new
deploy timestamp. `live.notify_enabled` stays `false` throughout regardless
of outcome, per Section 7b below. **No decision to recalibrate has been made;
this entry is a planning reference only.**

**Critical bug fix, logged per the Section 7 exception, 2026-09-09 - fixed,
verified, and deployed:** root cause of the zero-Buy/Strong-Buy
anomaly tracked down. `data/raw/calendar.csv` (the session start/end table
`build_sessions()` uses) was generated once by `fetch_calendar()` against
`config.yaml`'s frozen `dates.bars_end: "2026-08-21"`, and `run_loop.py`'s
calendar setup only ever re-fetched it if the file was entirely missing
(`if not calendar_path().exists()`), never for staleness - confirmed directly
in source, not inferred. Because every live event since real signal
collection began (2026-09-01) postdates that boundary,
`session_vwap_before()`'s "inside session" check was `False` for every single
live event, forcing `dist_from_vwap_pct` - the model's #2 most important
feature (importance 0.285 per `outputs/model_report.txt`, second only to
`macd_hist_1h` at 0.309) - to NaN on 100% of live decisions. Verified via the
literal live code path (`build_technical_features()`, called identically by
`build_event_frame()`): 459/459 live September events had this feature NaN.
This differs sharply from training, where the feature is naturally NaN only
~64% of the time (14518/22693 rows) - so XGBoost's fixed missing-value
default-direction routing, learned from that mixed pattern, was being applied
to every live decision instead of the roughly one-third of cases it was
trained for.

Fix (two parts, local-only so far): (1) `news_signal/ingest/alpaca_bars.py`'s
`fetch_calendar()` now accepts optional `start`/`end` overrides, default
unchanged, so existing offline callers (`run_milestone.py`, etc.) are
unaffected and `config.yaml`'s frozen `dates.bars_start`/`bars_end` governing
the offline research pipeline were NOT touched; (2) `run_loop.py` replaced the
exists-only check with `_calendar_is_stale()`, which refetches whenever the
calendar's last known date is within 14 days of today (pulling forward
through today+60 days), so it self-corrects going forward instead of silently
running out again.

Verified: refreshed `calendar.csv` locally (now covers through 2026-11-06);
confirmed `_calendar_is_stale()` correctly flags the old file as stale and the
refreshed one as current. Replayed all 473 September shadow-mode events (fresh
VM pull `signals_sept8_full.db`, 2026-09-01..09-08) through the real
`build_event_frame()` -> `predict_proba` -> `calibrate` -> `decide()` path
with the corrected calendar (453/473 scored; 20 skipped for relevance tier,
unrelated to this fix):
  - `dist_from_vwap_pct` now valid for 394/453 events (87%), vs. 0/453 before.
  - Recorded (broken-calendar) class distribution: Sell 401 (88.5%),
    Neutral 52 (11.5%), Buy 0, Strong Buy 0.
  - Recomputed (fixed-calendar) class distribution: Sell 259 (57.2%),
    Neutral 183 (40.4%), Buy 5 (1.1%), Strong Buy 6 (1.3%).
  - 11/453 events (2.4%) flip from Sell/Neutral all the way to Buy/Strong Buy,
    and all 11 flip `status` from `silent` to `fired` - 11 real alerts would
    have fired live in this window under a working calendar, vs. zero
    actually fired.

This qualifies as the Section 7 exception: it restores intended feature
computation for an already-trained, already-frozen model/calibration/
threshold set - nothing in the model, calibration, thresholds, or the
Section 5 decision rule was touched. Per the exception clause, results are
NOT reset; **every day with scored signals from 2026-09-01 through the fix's
VM deploy date is excluded as affected** (independent of Section 4a's
mechanical gates) - given the bug applied to 100% of live decisions across
that entire window, this covers essentially all shadow-mode data collected
to date.

**Deployed to the VM at 2026-09-09T13:07:29 UTC** (confirmed via `systemctl
status` at restart time - new PID 147806, replacing the previous
continuously-running PID 106830; journal shows a clean startup with no
calendar-refresh log line, consistent with `_calendar_is_stale()` silently
accepting the already-freshly-synced `calendar.csv` rather than needing to
refetch). **Final excluded-day range under this exception: 2026-09-01 through
2026-09-09T13:07:29 UTC** - all scored signals in that window are excluded
from the day/signal counts as affected by this bug, independent of whatever
Section 4a's mechanical gates would already exclude them for. Live
confirmation that the fix is working on a real cycle (not just a clean
restart): the 2026-09-09 post-deploy window (n=66, 2026-09-09T13:07:29 UTC
through end of session) scored Sell 30.3% / Neutral 68.2% / Buy 1.5% / Strong
Buy 0% - materially off the pre-fix 100% Sell/Neutral pattern, and included
the project's first-ever fired signals (see milestone entry below).

**Milestone, 2026-09-09 - factual record only, not a methodology change:**
first-ever fired signals in this project's history, all three correctly
staying log-only per `live.notify_enabled=false` (also that gate's first real
exercise against a genuine fire, not just `--inject-demo`):
  - `signal_id` 539, 2026-09-09T17:26:51 UTC, AAPL, Buy, p_cal=0.294,
    "Apple Introduces 'Apple Reference Image' Standard..."
  - `signal_id` 540, 2026-09-09T17:30:55 UTC, AAPL, Buy, p_cal=0.302,
    "Apple Introduces iPhone Handoff..."
  - `signal_id` 577, 2026-09-09T19:11:39 UTC, NVDA, Strong Buy, p_cal=0.372,
    "Nvidia and Meta Are Hungry for HBM..." - also the first-ever Strong Buy.

Residual note: even after the fix, the Buy/Strong Buy rate (2.4%) remains
below the ~8.73% expected from the training-period holdout, and Neutral
(40.4%) is elevated versus the training argmax baseline (25.43%) - so this
bug appears to explain the large majority of the anomaly (Sell moved from a
large over-representation to slightly *under* its 65.84% training baseline),
but not necessarily all of it. The smaller `rsi_14_1h`/`bb_pctb_1h` shift
noted in the entry above (calendar-independent features, unaffected by this
fix) remains a candidate for whatever gap is left.

**Investigated and refuted, 2026-09-10 - factual record only, no changes:**
`signal_id` 577 and 649 (both NVDA, both Strong Buy) were flagged for sharing
a bit-identical `prob_calibrated` (0.3722302768652679) despite different
headlines, raised as two possible hypotheses: (1) a relevance-tagging bug
misattributing an unrelated headline to NVDA, (2) a caching bug reusing a
stale prediction across events. Both refuted with direct evidence. (1): the
underlying Alpaca article behind `signal_id` 649 (headline about SolarEdge)
was refetched from Alpaca's API directly and genuinely mentions NVIDIA in its
summary ("a joint framework with NVIDIA") - a real tier-2 secondary mention,
correctly passed through by `relevance_tier()`'s existing headline-then-
summary text match, not a misattribution. (2): `prob_raw`, `severity_score`,
`entry_price`, and `stop_price` all differ between the two rows, ruling out
any full-row cache reuse; the shared `prob_calibrated` traces to the loaded
`calibration.pkl` artifact directly - the Strong Buy isotonic calibration map
has only 38 breakpoints and both events' distinct raw scores (0.9420197606086731
and 0.9324530959129333) land in the same output plateau, confirmed by calling
the map directly.

Real finding worth keeping on record so it isn't re-investigated as a false
alarm later: `prob_calibrated` values are frequently non-unique across
signals - 75% of all 650 signals fired/scored since 2026-09-01 share an exact
`prob_calibrated` value with at least one other row - because the calibration
artifact's isotonic step-function resolution is coarse, especially for Strong
Buy given its thin training sample (262 holdout examples). **This is expected
behavior given the calibration artifact as fitted, not a defect.**

Separately, noted as a minor observability gap (not fixed, not urgent): the
`signals` table stores `headline` but never `summary`, which can make a
legitimate tier-2 secondary relevance match look unexplained on casual
review of the stored data alone, since the textual match that justified
scoring the event is often only present in the summary.

**Major finding, 2026-09-11 - factual record only, no live/config/model
change:** the live `universe` (`config.yaml`, 40 tickers) and the offline
training data (`data/processed/milestone_events.parquet`) do not match.
Training data covers only **24 distinct tickers** - every one of them already
in the live universe, so there is no unused low-risk expansion pool sitting
in training data. The reverse gap is the real finding: **16 of the 40 live
tickers have zero historical training coverage at all** - `ABBV`, `AVGO`,
`CMCSA`, `COP`, `COST`, `CRM`, `GE`, `INTC`, `LLY`, `LMT`, `MCD`, `MS`, `NKE`,
`ORCL`, `T`, `WFC`. This is not a hypothetical future risk: **160 of 650
signals scored live to date (24.6%) are on these 16 tickers** (led by AVGO 34,
ORCL 26, INTC 23, CRM 15), meaning roughly a quarter of all live decisions run
through the frozen champion model + calibration with zero ticker-specific
training exposure - the model is generalizing on shared cross-ticker features
alone for this slice of live traffic. Likely cause: the live universe was
expanded to 40 tickers after `milestone_events.parquet` was originally built,
and the offline pipeline was never rerun to backfill the added names. No
change made - this is a factual record of an existing gap, logged so it is
tracked regardless of what (if anything) gets done about it. See the
follow-up backfill entry below for a first offline-only look at whether the
frozen model's behavior actually holds up on these 16 tickers.

**Follow-up: offline backfill + model-tracking check for the 16 gap tickers,
2026-09-12 - entirely offline, no live/config/model changes, no clock
impact:** built a standalone historical dataset for the 16 tickers above,
same pipeline and same historical window as the original build
(2026-04-15..2026-08-21): 25,416 deduped headlines -> 11,059 labeled events
after relevance filtering and warmup. News written to the existing (empty for
these tickers) `data/raw/news/`; historical 1-min bars fetched into a new,
SEPARATE `data/raw/bars_backfill16/` directory - the shared `data/raw/bars/`
that live's `BarCache` owns was never read from or written to. Output is a
new, separate `data/processed/milestone_events_backfill16.parquet` -
`milestone_events.parquet` itself was never touched.

Scored this backfill with the frozen champion model + calibration +
thresholds (no retraining) and compared against the real historical outcome,
reconstructed via `make_labels.py`'s exact frozen-edge formula. Caught and
fixed an error in this reconstruction before trusting it: the champion model
merges "Strong Sell" into "Sell", so the correct Sell/Neutral boundary is
`edges[1]`, not `edges[0]` - validated the corrected methodology by
reproducing `model_report.txt`'s reported holdout accuracy (got 0.336 vs. the
reported 0.370; the small gap is consistent with that report using
pre-calibration argmax vs. this check's post-calibration argmax).

Result: **the frozen model tracks real historical outcomes on the 16
never-trained tickers about as well as on its own training tickers** -0.375
accuracy on the 16-ticker backfill vs. 0.336 on the reproduced 24-ticker
holdout (same model, same methodology). Per-ticker accuracy ranges 0.299
(ABBV) to 0.454 (MCD), comfortably inside the week-to-week variation the
model already shows on training tickers (`model_report.txt`'s weekly
stability table: 0.330-0.510). One caveat: Strong Buy precision is lower on
the backfill (0.297 vs. 0.900 on holdout), but support is thin on both sides
(54 vs. 262 predicted-Strong-Buy events) - more likely small-sample noise on
an already-rare class than a robust ticker-specific degradation.

Technical-feature distributions (RSI, MACD, Bollinger, ATR, VWAP-distance,
momentum, sentiment) are largely similar between the 16 and the original 24;
the one real difference is moderately higher realized volatility in the 16
(ATR ~20% higher, Bollinger band width ~16% wider), plausibly just
composition rather than anything structural. No action taken - this is
evidence-gathering only, explicitly not a decision to expand the live
universe, which remains a separate, later call.

**Outcome tracking expanded to silent signals, 2026-09-14 - genuine scope
expansion, not a bug fix; clock-impact read below, decision deferred to
user:** confirmed with direct evidence (code + real data from
`signals_sept10.db`) that `db.pending_outcomes()` only ever selected
`status='fired'` signals for outcome backfill - silent signals (Neutral,
suppressed Sell, below-threshold Buy) never got a real price outcome
computed, by construction, since shadow mode began. Since Sell is
unconditionally suppressed, this meant Sell's true performance had never
been tracked with real outcome data at all.

Fix: removed the `s.status='fired'` filter from `pending_outcomes()`'s SQL
(`news_signal/live/db.py`) so every signal, regardless of status, becomes
eligible for outcome backfill once old enough to have resolved.
`backfill_outcomes()` (`run_loop.py`) required one additional change to
support this: `stop_price` comes back from sqlite as `None` (not `NaN`) for
every non-Buy/Strong-Buy signal, and the existing code called `float(stop_px)`
unconditionally, which would raise on `None` - added an explicit
`None`-to-`NaN` conversion before calling `simulate_exit()`. No change to
`simulate_exit()` itself: it already treats a NaN stop as "never stops, exit
at horizon close," exactly the right behavior for a signal that was never
actually entered. No change to `decide()`, thresholds, calibration, or which
events get scored - this only affects what happens to a signal's outcome
tracking after a decision has already been made.

Tested end-to-end against a disposable copy of real data
(`signals_sept10.db`, 650 signals, 4 pre-existing outcomes, all fired): after
running the patched `backfill_outcomes()`, outcomes went from 4 to 650 -
**645 previously-untracked silent signals retroactively backfilled** (Sell
485, Neutral 160, Buy 3, Strong Buy 2), confirming it reaches old-enough
signals already sitting in the database, not just future ones. Zero silent
outcomes show `stopped=True` (correct - no real stop level exists for a
signal that never fired). The one previously-unbackfilled fired signal in
the window was also correctly picked up, and existing fired-signal outcome
values were unaffected (regression check). Sample outcome rows show sane,
realistic entry/exit prices and gross/net returns throughout.

**Deployed to the VM at 2026-09-14T19:40:37 UTC** (confirmed via `systemctl
status` at restart time, new PID 191174; deploy confirmed clean). Per the
informational-infrastructure treatment below, agreed by the user: **no clock
reset, no excluded-day accounting needed** - this is logged as the confirmed
deploy timestamp for the record only.

My own read on clock impact, since asked: I'd treat this as informational/
diagnostic infrastructure, not a Section-7-triggering change, and not
because it fits the critical-bug-fix exception either (nothing was broken -
this is scope that was apparently never built, as noted). The reasoning:
Section 7 cares about changes that affect "results" - which events get
scored, what class/probability they're assigned, whether they fire, and
anything feeding the Section 5 promotion test's statistics. This change
touches none of that; `decide()` and the entire scoring/firing path are
byte-for-byte unchanged. Outcome rows are a purely retrospective record of
what price did after an already-final decision, orthogonal to the promotion
test's actual measurements - the same category of reasoning already applied
to the `signal_insert_log` diagnostic-logging entry above (logged as
diagnostic-only, no clock reset). **Decision confirmed by user: treated as
informational/diagnostic infrastructure, no clock reset.**

**Known data issue in the frozen model's training data, 2026-09-27 - logged only, no retrain, no
clock reset:** discovered while reviewing an unrelated offline study that used Alpaca bars with
`adjustment=all`. HON underwent a real 1-for-2 reverse split plus a same-day HONA spin-off on
2026-06-29. The champion model's training pipeline (`news_signal/ingest/alpaca_bars.py`) fetches
with `adjustment=split` (splits only, not spin-off value adjustments), so the spin-off's price
drop appears in the cached bars as a raw ~51% single-day decline with no corresponding split
adjustment to offset it - a real discontinuity, not a data-fetch error, but one the feature
pipeline has no way to distinguish from a genuine 51% crash. Quantified against
`data/processed/milestone_events.parquet`: HON accounts for 384 of 22,693 training rows; 105 of
those have a non-NaN `vol_ratio_5d_40d` (the daily-regime features need >=62 trailing daily bars,
so they only start populating in mid-July), and **all 105 sit inside the 60-day window following
the discontinuity**, with median `vol_ratio_5d_40d` 0.148 versus 0.901 for all other tickers -
i.e., every HON row with a populated volatility-ratio feature during this period is corrupted by
the artifact, not a handful of edge cases. Of those, 31 fall inside the holdout (>=2026-08-03).
Separately, 29 HON rows with `published_utc` in 2026-06-29..07-02 have hourly-indicator windows
(`bb_width_1h`, etc.) spanning the discontinuous hourly bar directly: median `bb_width_1h` 1.881
vs. 0.053 for HON overall - a ~35x distortion. `mom_5d`/`rv_short_5d` are unaffected for this
window (both NaN for HON until mid-July, so they never see the bad data). This is a known,
quantified defect in the FROZEN training artifacts (`champion_xgb_4class.json`,
`calibration.pkl`) - fixing it would mean regenerating the offline dataset and re-running Phase
4/5, a genuine model change requiring the full Section 7 process, not something to do
reactively. No such change is made here. Live-side mitigation (preventing this from recurring via
stale cached bars) is a separate, already-implemented fix - see the `BarCache` corporate-actions
entry below.

**`BarCache` corporate-actions fix, 2026-09-27 - Section 7 data-quality fix, implemented and
tested locally, NOT deployed:** the live loop's `BarCache.get()` (`news_signal/live/run_loop.py`)
only ever appends newly-fetched bars onto whatever CSV is already cached for a ticker; it never
re-fetches historical data. If a split or spin-off occurs on a ticker whose cache already holds
pre-event bars (exactly the HON situation above, live-side), the discontinuity would sit
permanently in that ticker's cache file until manually deleted - a live-only latent risk distinct
from the training-data issue already logged. This entry supersedes the first version of this fix
(also dated 2026-09-27, same day): a same-day review found the first version handled spin-offs
incorrectly and could re-delete an already-fixed cache; both are corrected below. No model,
threshold, or config value changed; no clock reset - this only affects data hygiene for
already-frozen live-side caches and a new suppression path for a rare event type.

Fix, three parts:
1. **Splits (`forward_split`/`reverse_split`):** unchanged from the first version - if a ticker's
   cache already spans across a detected split's `ex_date`, the whole cached CSV is deleted so the
   next `get()` call re-fetches it from scratch, consistently `adjustment=split`-adjusted, instead
   of half raw/half adjusted.
2. **Spin-offs (correction):** `adjustment=split` does not adjust for spin-off value changes at
   all (confirmed on HON), so a re-fetch would still contain the fake price drop - deleting and
   refetching does nothing useful here. Instead, a detected `spin_off` action now suppresses that
   ticker's live decisions with `status='silent'`, `suppress_reason='corporate_action'` for
   `CA_SUPPRESSION_TRADING_DAYS` (60) trading days from `ex_date` - long enough to cover the
   longest affected feature window (`vol_ratio_5d_40d`). The signal is still fully logged
   (`signal_insert_log`, `signals`) and its outcome still resolved as usual via `backfill_outcomes()`
   (which already covers every status, not just fired) - only the decide()-driven fire/notify path
   is overridden. These rows should be excluded from evaluation for that ticker over that window
   (filter on `suppress_reason='corporate_action'` when computing fire rates, class distributions,
   or hit rates) - a policy note for whoever runs `shadow_status.py`-style review, not a code
   change to that read-only script.
3. **Repeat-handling bug fix:** the first version re-checked every day within the lookback window
   and would delete an already-correctly-refetched cache again, since a legitimately-adjusted
   cache still spans across `ex_date` post-fix. Each `(ticker, ex_date, type)` is now recorded in
   `data/raw/bars/corporate_actions_handled.json` once handled; a later check for an
   already-recorded action is a no-op.
4. **Lookback widened from 7 to 30 days** (`CA_LOOKBACK_DAYS`), so a VM outage of a few weeks can't
   cause an action to age out of the check window before it's ever seen.

Tested locally (`scripts/test_barcache_split_refetch.py`, three cases, all passing):
- A cached ticker with pre-split-only bars, given a stubbed reverse-split action: cache is deleted
  and refetched, resulting max single-day move 0.25% (previously would show a fake ~50%+ jump).
- The same action re-checked on a fresh `BarCache` instance (simulating the next day's process):
  the already-correctly-adjusted cache is left alone, not deleted again.
- A stubbed spin-off action: suppression is confirmed active 5 trading days after `ex_date` and
  lifted 61 trading days after; the action is recorded in the on-disk registry; no cache
  deletion/refetch is attempted for the spin-off case.

**Not yet deployed** - staged locally, to be bundled with the `signal_insert_log` change (already
logged above) at the next real deploy, per instruction. The VM was not touched.

**Deployed to the VM at 2026-10-01T06:43:38 UTC** (confirmed via `systemctl show` at restart time -
`ActiveEnterTimestamp` 2026-10-01T06:43:38 UTC, new PID 371921, `NRestarts=0`). Section 7 data-quality
fix: **no clock reset**. Service was stopped 06:40:18-06:43:38 UTC (3m20s, market closed, no signals
missed). Pre-deploy diff of the VM's running code against the bundle showed only `EVALUATION_PLAN.md`,
`news_signal/live/run_loop.py`, `scripts/check_feature_parity.py` and
`scripts/test_barcache_split_refetch.py` changed - nothing under `models/` or `config/`. This deploy
shipped only the corporate-actions fix: `signal_insert_log` was already live since 2026-09-09 (see the
correction to that entry above), and no DB migration was needed. Pre-deploy tests:
`scripts/test_barcache_split_refetch.py` 3/3 passing, `--inject-demo` smoke test clean, all shipped
`.py` files compile under Python 3.10. Post-deploy: live DB `PRAGMA integrity_check` ok, `signal_insert_log`
present (1,200 rows). Backups on the VM: `~/deploy-backups/code-20261001T063926Z.tgz` and
`~/deploy-backups/signals-20261001T063926Z.db` (integrity ok, 1,673 signals).

**Spin-off detection bug in the `BarCache` corporate-actions fix, 2026-10-01 - Section 7 bug fix,
implemented and tested locally, NOT deployed, no clock reset:** found during the 2026-10-01
read-only diagnostics. `fetch_corporate_actions()` (`news_signal/live/run_loop.py`) kept a returned
action only if `row["symbol"] == ticker`. Per Alpaca's corporate-actions schema, splits carry a
`symbol` field but spin-offs do not: they name the parent in `source_symbol` and the spun-off child
in `new_symbol`. Every spin-off was therefore silently dropped, and the spin-off suppression path
of the entry above (part 2) could never trigger in production. Confirmed on Alpaca's real HON
response for 2026-06-01..07-31: the old parser returned only the `reverse_split`, not the
`spin_off` (`source_symbol: "HON"`, `new_symbol: "HONA"`, ex_date 2026-06-29). Test 3 of
`scripts/test_barcache_split_refetch.py` stubbed `fetch_corporate_actions()` itself, so it never
exercised the parser and missed this.

Fix: an action is kept if the ticker matches `symbol` OR `source_symbol`. `new_symbol` is
deliberately not matched: it is the spun-off child, a new listing with no pre-event cache to
protect. One line changed in `fetch_corporate_actions()`; no model, threshold, or config value
changed. New test 4 in `scripts/test_barcache_split_refetch.py` feeds the verbatim HON Alpaca
response through the real parser and `_maybe_handle_corporate_actions()`. It fails on the old code
("spin-off NOT detected") and passes on the new code: the spin-off is detected, recorded, and
suppression runs exactly `CA_SUPPRESSION_TRADING_DAYS` (60) trading days from ex_date (cutoff
2026-09-23 13:30 UTC; active at +5 days, lifted at +61). All 4 tests pass; both changed files parse
under Python 3.10; the `--inject-demo` smoke test is clean.

Effect on collected data: none. Since the 2026-10-01T06:43:38 UTC deploy, no split or spin-off
occurred in the 30-day lookback for any of the 40 tickers (Alpaca queried 2026-10-01). HON's
2026-06-29 event is outside the lookback, and its 60-day window would have ended 2026-09-23 anyway,
so deploying this fix will not suppress any ticker today. It only makes the next spin-off among the
40 detectable.

**Deployed to the VM at 2026-10-03T12:17:07 UTC** (`systemctl show`: `ActiveEnterTimestamp`
2026-10-03T12:17:07 UTC, new PID 396718, `NRestarts=0`). Section 7 bug fix: **no clock reset**.
Service was stopped 12:12:40-12:17:07 UTC (4m27s, Saturday, market closed, no signals missed).
Bundle `news-signal-bundle-20261001b.tgz`, SHA-256
`dfb3fd3f3416fc31fd60532eb007f0aad38b0f829b5701e7bde39dfeaffc6867`. Pre-deploy diff of the VM's running
code against the bundle showed only `news_signal/live/run_loop.py`, `scripts/weekly_report.py` (new,
read-only reporting script never run by the service), `scripts/test_barcache_split_refetch.py` and
`EVALUATION_PLAN.md` changed - nothing under `models/` or `config/`. Only those four files were copied
in. Pre-deploy tests on the VM's Python 3.10 in a staging directory:
`scripts/test_barcache_split_refetch.py` 4/4 passing. Post-deploy: deployed `run_loop.py` SHA-256
`35dbae3e8aaf783c536e642ad8541e441212668fb34f69e0184db4a8ddc8dacf` (matches the bundle); a read-only
`fetch_corporate_actions('HON', lookback_days=120)` on the VM now returns the 2026-06-29 `spin_off`.
Backups on the VM: `~/deploy-backups/code-20261003T121214Z.tgz` and
`~/deploy-backups/signals-20261003T121214Z.db` (integrity ok, 1,854 signals).

**Descriptive diagnostics, 2026-10-01 - descriptive note only, no decision, no change, no clock
reset.** Source: `signals_oct1.db` (VM snapshot through 2026-09-30) plus local frozen artifacts. Not
the Section 3 primary endpoint; not used in any Section 5 decision. Read-only; scratch scripts were
not committed.

*Latency.* Sample: the 1,200 signals in the Section 9 funnel (from 2026-09-09T13:07:29 UTC, not
corporate-action, matched to `signal_insert_log`). Publish -> decision: median 29.45 min, p90 54.9.
The split below uses `seen_news.first_seen_utc` (hash recomputed per signal; 1,200/1,200 matched).

| feed | n | publish -> first seen, median / p90 | first seen -> decision, median / p90 |
|---|---|---|---|
| Finnhub | 705 | 43.6 / 56.7 min | 9.7 / 22.7 s |
| Alpaca (Benzinga) | 495 | 3.7 / 6.2 min | 5.6 / 10.4 s |
| fired Buy/Strong Buy, Finnhub | 29 | 44.8 / 53.0 min | 8.2 / 17.8 s |
| fired Buy/Strong Buy, Alpaca | 19 | 4.4 / 6.0 min | 5.7 / 11.3 s |

The 29.5 min median is a blend of two feeds, not processing time. The Finnhub row survives the
60-min stale gate. Across all 5,548 Finnhub items in `retrieval_lag` since 2026-09-09, the median
lag is 143.5 min, 12.6% arrive within 60 min, and none within 5 min. Alpaca, all 1,224
`alpaca_news_seen` rows over the same period: median 3.9 min, p90 6.5. Each poll cycle adds
~1.4 min of waiting on average (~2.7 min worst): 40 paced Finnhub calls, ~44 s, plus 120 s sleep.
Articles' original sources are not stored, so no per-source breakdown is possible.

Alpaca news WebSocket check (`wss://stream.data.alpaca.markets/v1beta1/news`, existing keys,
`news: ["*"]`, local machine only, the VM stays REST-only). Auth and subscribe succeeded, so the
stream works on our plan. Two 3-min sessions during market hours: 0 items, then 1 item
(19:14:41-19:17:42 UTC) received 0.5 s after its `created_at`. That item was not yet returned by
REST ~2.6 min after creation and was by ~3.6 min. n=1, anecdotal.

*Feature-group importance (frozen `champion_xgb_4class.json`).* Severity is not a model input.
Share of total gain:
- technical 1-h/intraday 62.7%
- regime/daily 18.3%
- news flow (`hours_since_prev_headline`, `headlines_prior_24h`) 5.8%
- news content (sentiment, `nt_*`, `relevance_tier`) 5.6%
- time of day 4.4%
- sector dummies 3.1%

Mean |SHAP| share for the predicted class, 40 offline-replayed fired Buy/Strong Buy signals since
2026-09-09:
- technical 47.8%
- regime 21.1%
- news flow 11.0%
- news content 9.8%
- sector 6.5%
- time of day 4.0%

On the 24 whose replayed class matched live: 46.3 / 22.2 / 12.9 / 9.6 / 4.6 / 4.4%. The replay is
approximate: the DB stores no summaries, and bars were refetched from Alpaca (IEX), not taken from
the VM cache. 3 signals with identical bars reproduced exactly; overall class agreement was 60%.
31 of 40 replayed rows were `nt_other`.

*Headline content.* 50 random headlines from those 1,200 (pandas `sample`, random_state=7),
hand-classified:
- new material company fact: 3 (6%) - NVDA buyback, twice; ORCL Project Jupiter warning
- new minor company fact: 3 (6%)
- analyst rating change: 2 (4%)
- recap / opinion / move-explainer / listicle / market commentary: 42 (84%)

In 5 of the 50, the tagged ticker is not the headline's subject.

*Passing mentions firing.* Replaying the 48 fired Buy/Strong Buy signals from headline text alone,
8 are tier-3 passing mentions, i.e. tier 1 came only from the (unstored) summary. Examples:
- signal 649, NVDA Strong Buy: "SolarEdge Stock Is Trending Higher: What's Going On?"
- signals 1251/1254, NVDA Strong Buy: "What's Going On With Super Micro Computer Stock Thursday?"
- signal 676, T Buy: "Company News for Sep 11, 2026"
- signal 775, NVDA Strong Buy: "Vertical Data Secures $192 Million AI Infrastructure Commitment…"

Only one of the 8 (signal 1179, JNJ, a TECVAYLI/DARZALEX data headline) is plausibly about the
tagged company.

*Flat Buy calibration.* The Buy isotonic map in `calibration.pkl` is nearly flat: raw 0.1 -> 0.240,
and every raw value from 0.3 to 0.95 maps to 0.261. After the four classes are renormalized,
whether Buy reaches its 0.29 threshold depends mainly on how small the other classes' calibrated
mass is, not on the model's Buy confidence. Example (offline, 2026-08-20, WMT): raw Buy 0.869 ->
calibrated 0.289 -> silent. For comparison, Strong Buy's map spans 0.125-0.449.

*Case study.* MRK and MRNA are not in the universe. The 2026-08-19 melanoma-vaccine news reached
the system only as tier-1 PFE read-across headlines; offline, both scored raw Sell (0.61, 0.59) and
stayed silent.

## 7b. Notification freeze

`live.notify_enabled` stays `false` for the ENTIRE shadow-mode run, regardless
of how interim results look - including strong early stretches. It may only be
flipped to `true` AFTER the formal Section-5 promotion test passes at minimum
sample. Enabling notifications earlier is a Section-7 change-freeze violation:
results reset and the incident is logged with justification. (Presence of
TELEGRAM_* env vars alone has no effect; both the env vars AND the flag are
required, and the flag stays off.) Notification delivery is downstream of
signal logging, so this freeze cannot bias the dataset itself.

## 8. Reporting cadence

Weekly: scripts/shadow_status.py output appended to outputs/shadow_reviews/,
including counts vs Section 4 targets, hit-rate Wilson CIs, calibration drift,
and uptime proxies. The formal Section-5 test runs only at minimum sample.

## 9. Secondary descriptive analyses (registered 2026-10-01, before looking)

**Registered before looking:** written and committed on 2026-10-01 before any
return, outcome, or class-level statistic from `signals_oct1.db` (VM snapshot
through 2026-09-30) or any later DB copy was computed or viewed for these
analyses. Implemented in `scripts/weekly_report.py` (read-only on the DB; no
live-path code touched). These are SECONDARY/DESCRIPTIVE analyses: they do not
replace or amend the Section 3 primary endpoint or the Section 5 decision rule,
they support no promotion/rejection decision, and adding them changes no
model, threshold, config, or Section 1-7b rule - so, consistent with every
dated log entry above, this addition does not reset the evaluation clock.

**Sample.** All rows of the DB's `signals` table, minus (counted, never silent):
- signals with `ts_utc` before 2026-09-09T13:07:29 UTC (the Section 7
  calendar-bug affected window; class labels there are known-wrong);
- `suppress_reason='corporate_action'` rows (per the Section 7 BarCache entry);
- signals with no matching `signal_insert_log` row (no decision time);
- signals whose decision time is outside a regular session;
- signals with no usable bars for the stock or SPY in the window.
Section 4a's per-day validity gates are NOT applied here (this report does
not compute uptime); that is stated in every report.

**Window and returns.** Decision time t0 = `signal_insert_log.logged_at_utc`
(matched to its `signals` row on `ts_utc`, `ticker`, `url`, `headline`;
duplicates paired in insertion order) - the first moment the system could act,
not the headline's publish time. t1 = min(t0 + 120 min, that session's close).
Bars: Alpaca 1-min, `feed=sip`, `adjustment=all`, pagination followed,
zero-volume bars dropped, regular-session bars only. P0 = open of the first
bar starting at/after t0; P1 = close of the last bar starting before t1.
Raw return = P1/P0 - 1 (gross, no costs). Market-adjusted return = stock raw
return minus SPY raw return over the identical [t0, t1).

**Statistic and uncertainty.** Trading day = ET date of t0. Point estimate =
day-clustered mean (mean over trading days of each day's mean; Section 3
convention), with the pooled per-signal mean shown alongside. 95% CI = day
bootstrap, B=2000, percentile, seed 20261001. Every number is printed with
its n signals and n trading days.

**(a)** Raw and market-adjusted 2h return: all signals; each class (Strong
Buy, Buy, Neutral, Sell); fired Buy/Strong Buy.

**(b) Random-ticker control.** For each signal, one ticker drawn uniformly
from the other universe tickers in `config.yaml` (currently 39) that have a
valid return over the identical [t0, t1); its market-adjusted return replaces
the signal's. Repeat 1,000 times (seed 20261001), computing the same
day-clustered mean each time. Report the percentile of the real mean in that
distribution (share of draw means below it, ties counted half). Groups: all
signals; fired Buy/Strong Buy. **The fired Buy/Strong Buy percentile is this
section's headline number** - still descriptive, not a decision test.

**(c) Breakdowns of (a), exploratory.** Groups: all signals; fired Buy/Strong
Buy. Regime features via `news_signal/features/regime.py`'s own
`spy_regime_row()` / `ticker_regime_row()` with `config.yaml`'s windows
(SMA 50/200; vol 5/60 days), from strictly prior-day daily closes (Alpaca
daily, `feed=sip`, `adjustment=all` - approximates, does not reproduce, the
live features, which use `feed=iex`/`adjustment=split`). Fixed cuts, chosen
before looking: `spy_above_sma200` 1 vs 0; `vol_ratio_5d_40d` > 1 vs <= 1
(short-window realized vol expanding vs contracting); `mom_5d` > 0 vs <= 0;
missing values reported as their own bucket. Time of day of t0: first hour
(< open + 60 min), last 2h (>= close - 120 min; windows here are clipped at
the close, so shorter than 2h), midday (everything else).

**(d) Silent-Sell check, EXPLORATORY ONLY.** Signals with `class_name='Sell'`
(any status; all are logged, none acted on): day-clustered mean
market-adjusted 2h return with CI, plus the share of signals with a negative
market-adjusted return. Descriptive only: creates no short strategy, does not
lift the Section 1 Sell suppression, and resets no clock.

**Sample-size rules applied when reading these numbers.** Section 4 (>= 40
valid trading days with a fired long signal AND >= 300 fired Buy/Strong Buy)
and Section 6 (no per-class claim under 40 active days) apply: below them,
every result is labelled "too small to conclude". Any cell with < 30 signals
is additionally flagged as thin. With (a)-(d) producing dozens of cells, some
will look "significant" by chance; any such cell is a hypothesis for a
future pre-registered test, never a finding.
