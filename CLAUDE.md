# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`news-signal-milestone` is a pre-registered, shadow-mode trading-signal research project: news-driven long-only alerts (Buy / Strong Buy) from a champion XGBoost 4-class model + isotonic calibration + frozen thresholds, on a stock universe defined in `config/config.yaml`. It is currently deployed in shadow mode (log-only, no live notifications) on an Oracle Cloud VM, being evaluated against a pre-registered statistical test.

**`EVALUATION_PLAN.md` is the governing document — read it before any nontrivial change.** It was frozen on 2026-08-23 and defines the promotion test, minimum sample sizes, and data-quality gates.

### Change-freeze rule

EVALUATION_PLAN.md Section 7: *"Any model/threshold/config change freezes results and RESETS the clock (exception: critical bug fixes, logged, affected days excluded)."* Before editing anything under `models/`, `config/config.yaml`, or any file the deployed live loop executes, check whether the change qualifies as a "model/threshold/config change" — if so, say so explicitly and confirm before proceeding rather than deploying silently. A local-only, read-only reporting script change (e.g. to `scripts/shadow_status.py`) does not qualify since it never runs as part of the live service.

Section 7b: `live.notify_enabled` must stay `false` for the entire shadow-mode run — including during strong early results — until the Section 5 promotion test passes at minimum sample. Flipping it early (or setting Telegram env vars alone, which has no effect without the flag) is itself a change-freeze violation that must be logged.

## Environment

- Local dev venv (`.venv/`) runs **Python 3.14**. The deployed Oracle VM runs **Python 3.10.12** and installs only `requirements-live.txt` (which pins exact versions live needs, e.g. `scikit-learn==1.7.2`, vs. the looser bounds implied by local dev packages). An artifact fit/pickled locally under a newer package version (e.g. `models/calibration.pkl` via scikit-learn) may not load under the VM's pinned version — verify cross-version compatibility, or regenerate the artifact under the pinned version, before syncing any new model artifact to the VM.
- Secrets live in `.env` (`FINNHUB_API_KEY`, `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, optional `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`); `news_signal/config.py`'s `load_config()` raises `RuntimeError` if any of the three required keys is missing.

## Commands

Activate the venv first: `.venv\Scripts\python.exe ...` (or `.venv\Scripts\activate` in PowerShell).

**Offline research pipeline** (run in this order; each stage reads the previous stage's output):
1. `python scripts/run_milestone.py [--stage ingest|sentiment|build|all]` — pulls news/bars, scores sentiment (FinBERT, disk-cached), builds `data/processed/milestone_events.parquet`, the labeled event dataset every downstream script reads.
2. `python scripts/verify_milestone.py` and `python scripts/check_feature_parity.py` — sanity-check the built dataset, and confirm the live feature-construction path (`news_signal/live/pipeline.py`) produces the same features the model was trained on.
3. `python scripts/run_phase4.py` — tunes/trains the champion XGBoost classifier; writes `outputs/model_report.txt` and `outputs/confusion_matrix_holdout.csv`.
4. `python scripts/pre_phase5_checks.py` and `python scripts/reconcile_and_significance.py` — pre-calibration sanity checks and significance testing.
5. `python scripts/run_phase5.py` — fits per-class isotonic calibration + severity regressor on the frozen champion model, runs the backtest, and **persists the live artifacts**: `models/calibration.pkl`, `models/alert_thresholds.json`, `models/severity_regressor.json`. This is the only script that (re)writes those three files — re-run it in full to regenerate any one of them rather than hand-editing or partially replicating its logic.

**Live loop** (shadow mode):
- `python -m news_signal.live.run_loop --once` — run a single poll/decision cycle.
- `python -m news_signal.live.run_loop --loop` — run continuously at `live.poll_interval_sec` (config.yaml), market-hours aware.
- `python -m news_signal.live.run_loop --inject-demo` — push one synthetic NVDA headline through `process_items()` to smoke-test the decision path without hitting Finnhub/Alpaca.

**Reporting**:
- `python scripts/shadow_status.py --db path/to/signals.db` — weekly review report (pipeline funnel, fired signals by class, minimum-sample gates, per-ticker poll failures, descriptive paper outcomes). Run against a **downloaded copy** of the VM's `data/live/signals.db` — per EVALUATION_PLAN.md Section 2, local/manual runs never advance the evaluation clock. Append output to `outputs/shadow_reviews/`.

There is no automated test suite (no `tests/` directory, no pytest config). Verification is done by running the `verify_*` / `check_*` / `pre_*_checks` scripts above against real pipeline output and artifacts, plus targeted ad hoc scripts.

## Deployment

Manual SSH deploy to an Oracle Cloud Always Free ARM VM; full steps in `deploy/README_DEPLOY.md`. Key points:
- Sync tarball contents: `news_signal scripts config models deploy requirements-live.txt .env.example EVALUATION_PLAN.md data/raw/calendar.csv data/raw/profiles.json`. Never sync `.env` itself (type secrets directly on the VM) or `data/live/` (the VM owns its own signal database — overwriting it would destroy collected evaluation data).
- The VM runs `news_signal.live.run_loop` under systemd (`deploy/news-signal.service`, `Restart=always`, 30s backoff).
- Updates: re-sync changed files, then `sudo systemctl restart news-signal` — and see the change-freeze rule above before doing so.

## Architecture

The offline/backtest path lives under `news_signal/` in four layers:

1. **`ingest/`** — external API pulls: `finnhub_news.py` (per-ticker company news + company profiles — one call per ticker, no bulk endpoint), `alpaca_bars.py` (1-min/1-day bars), `process_news.py` (dedup). Calls are paced against Finnhub's free-tier ~60 calls/min limit via `config.yaml`'s `ingestion.finnhub_rate_limit_per_min`.
2. **`features/`** — independent feature builders: `relevance.py` tiers each headline as a primary/secondary/passing mention of a ticker (only tier-1 primary mentions reach the model); `technical.py` computes hourly indicators from the last COMPLETED bar only; `regime.py` computes daily SPY/sector regime from strictly prior-day closes; `sentiment.py` runs FinBERT with a disk cache keyed by headline hash; `news_type.py` classifies headline type.
3. **`labels/`** — `forward_returns.py` builds trading sessions/events and a strictly trailing per-event volatility (`sigma_2h`, computed only from windows completed before publish — a core leakage guard); `make_labels.py` fits quantile-based class-edge thresholds once on the train split and freezes them (never refit on holdout or live data).
4. **`models/`** — `features.py` assembles the final feature matrix and class-balanced sample weights; `splitting.py` implements purged walk-forward CV with embargo plus the holdout split; `tune.py` runs the Optuna XGBoost search; `calibration.py` does per-class isotonic calibration and precision-floor threshold selection.

**`news_signal/live/`** is the deployed shadow-mode path and is architecturally distinct from the backtest path above — this is the source of a recurring bug class, since backtest data is structurally always non-empty/columned by construction, while live network calls legitimately can return nothing:
- `run_loop.py` — the service entrypoint. `RateLimiter` is a minimum-interval pacer (not a count ceiling) shared across `poll_news()` and `fetch_quote()`, so Finnhub calls are evenly spaced rather than able to burst. `BarCache` holds a per-ticker 1-min bar cache backed by CSV + incremental Alpaca refresh. `process_items()` is the per-headline decision pipeline: relevance-tag → build feature frame → classify → calibrate → threshold-decide → severity-score → fetch entry quote → simulate stop → persist to sqlite. `run_cycle()`/`main()` handle loop orchestration and per-cycle poll-failure counting/logging (persisted to a `poll_failures` table, surfaced in `shadow_status.py`).
- `pipeline.py` — `build_event_frame()` assembles one live feature row matching the trained model's exact `feature_names`; `decide()` maps calibrated probability → class/status against the frozen thresholds (Sell is suppressed by default); `simulate_exit()` runs the stop/horizon exit simulation used to backfill paper outcomes.
- `artifacts.py` — loads the four frozen live artifacts: `champion_xgb_4class.json` and `severity_regressor.json` via XGBoost's native JSON format (version-independent of scikit-learn/Python), `calibration.pkl` via `pickle` (scikit-learn version-sensitive — see Environment above), `alert_thresholds.json`.
- `db.py` — owns the canonical sqlite schema (`signals`, `outcomes` tables) for `data/live/signals.db`. Any new live-only table (e.g. `poll_failures`) that isn't part of this canonical schema has so far been kept local to the file that uses it (`run_loop.py`) rather than added here, on request.

When touching live-path code, check whether it silently assumes non-empty/well-formed results — a valid assumption in the backtest path (which never sees a truly empty poll) but not in live operation. This exact bug class has previously hit `process_items()`'s `pd.DataFrame(items)` construction and `BarCache.get()`'s empty-bars handling.

---

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
