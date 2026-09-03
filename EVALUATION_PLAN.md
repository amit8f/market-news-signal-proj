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
