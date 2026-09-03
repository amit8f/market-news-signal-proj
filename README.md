# news-signal

**A real-time, news-driven trading signal system for US equities — built with a pre-registered evaluation methodology designed to catch its own false positives, and its own bugs, before trusting either.**

Status: **Live, in shadow-mode evaluation** (log-only, no live trading, no capital at risk). Deployed 24/7 on a cloud VM, polling financial news, scoring it with a tuned XGBoost model, and logging what it would have done — under a frozen evaluation plan that decides in advance what "working" actually means, rather than deciding after looking at the results.

---

## What it does

Polls official financial news for a curated universe of ~40 large-cap US equities, scores each relevant item with a tuned XGBoost classifier into an actionable Buy / Strong Buy / Sell / Strong Sell call (Neutral is suppressed — no alert), attaches an entry price, a target, and an ATR-based stop-loss, and logs the result. Currently running in **shadow mode**: every decision is recorded, nothing is acted on, and no notification fires, until a pre-registered statistical bar is cleared.

## Why this is more than "a trading bot"

The interesting part of this project isn't the model — it's the discipline around trusting it, and around trusting the pipeline that feeds it. A few highlights:

- **Caught its own false positive before shipping it.** An early backtest showed what looked like a clear, statistically significant edge (t ≈ 5.5). Re-running the significance test with day-clustered standard errors — correcting for the fact that same-day trades aren't independent observations — showed the result was actually indistinguishable from noise. The system is built specifically to surface this kind of thing rather than let a lucky window get mistaken for an edge.
- **Measured news timing empirically, twice, and acted on what the data actually showed.** First discovered that a client-side recency filter had been silently discarding nearly all incoming news since launch — every "quiet day" in the logs was actually a false negative. After fixing that, discovered the deeper problem underneath it: the free news source's real-world retrieval lag was routinely measured in *hours*, not minutes — more than half of all relevant items arrived over two hours after publication. Rather than assume a faster source would simply be better, ran a real coverage comparison (volume, per-ticker breadth, content-type mix) before designing a dual-source architecture: a fast source drives real decisions, a broader source stays logged for the record, with explicit handling for when both sources cover the same story.
- **Caught a frozen-price bug before it reached a real decision.** Discovered the free price-quote source was silently returning stale, cached values — confirmed by cross-referencing against a second, independent price feed's real tick data — and fixed the entry-pricing path before any live signal ever fired on it.
- **Found and fixed a real credential-logging vulnerability during a pre-publication security audit.** Discovered that API keys had been leaking into error logs in plaintext since the code was first written — not a hypothetical risk; it explained a real, previously-unresolved leaked-key incident from earlier in the project. Traced every code path that could leak a secret, not just the one found first, fixed it with systematic redaction, verified the fix against a deliberately-triggered real API error, and rotated credentials only after the fix was confirmed live — in that order, on purpose.
- **A fully pre-registered evaluation plan, frozen before any live data existed, and actively used since** — minimum sample size (40 independent trading days *and* 300 fired signals, both required), an exact promotion rule, a no-discretionary-exclusion burn-in policy, and a hard change-freeze rule with a narrow, logged exception for genuine bug fixes. Since going live, the plan has been used to make real calls on real incidents — including determining, with actual uptime math, that a brief mid-session crash-loop stayed under the exclusion threshold and didn't need to be thrown out.
- **A real null result, reported honestly.** Tested whether news sentiment (FinBERT) carries predictive signal independent of price/technical features. It doesn't, at this horizon (Pearson r = −0.019, p = 0.004 against forward returns) — a well-powered, confidently negative result, not an unresolved question papered over.

## Architecture

```
Alpaca News (primary, scored) ──┐
                                 ├─► relevance tagging ─► feature engineering ─► XGBoost (4-class) ─► calibration
Finnhub (coverage log only) ────┘                                                                          │
Alpaca (live prices) ───────────────────────────────────────────────────────────────────────────────────  ▼
                                                                            entry / target / ATR stop-loss
                                                                                              │
                                                                                              ▼
                                                                              shadow-mode log (Telegram alert
                                                                              gated off until formal promotion)
```

Runs as a systemd service on an Oracle Cloud "Always Free" ARM VM — auto-restarting, rate-limited to stay within free-tier API budgets by design, with its own SQLite-backed signal, poll-failure, and staleness logs.

## Engineering problems solved along the way

A sample of the real production issues found and root-caused, not just patched:

- **A rate limiter that let bursts through.** The original implementation checked "have I hit the ceiling yet" rather than pacing calls individually — meaning a batch comfortably under the per-minute cap could still fire as one dense burst, tripping the API's real server-side limiter. Diagnosed by analyzing the statistical distribution of failure timestamps before finding the real cause.
- **A leaked-credential incident, resolved twice — first the symptom, then the actual cause.** Unusual, periodic traffic against a shared API key was noticed and mitigated by rotating the key. Weeks later, a security audit ahead of open-sourcing the project found the real root cause: the key had been printed into error logs on every failed request, the whole time. Fixed at the source, verified live, rotated again.
- **Cross-version model reproducibility.** A calibration artifact pickled under a newer scikit-learn than the deployment server's Python version could support. Root-caused to a hard Python-version ceiling, fixed by re-fitting under the correct library version, and verified safe by diffing predictions from both versions across thousands of held-out rows (zero difference) before redeploying.
- **Backtest-vs-live blind spots.** Several bugs only ever surfaced live because the backtest pipeline's data was implicitly "cleaner" than what live operation actually produces (empty API responses, zero-row DataFrames, genuinely stale timestamps) — a recurring pattern worth calling out on its own, since it's a common trap in any ML system with separate training and serving paths.

## Evaluation methodology

Full details in `EVALUATION_PLAN.md` — frozen before any VM data existed, and amended only through its own documented, dated exception process since. Covers: what counts as a valid trading day (mechanical, pre-registered data-quality gates only), the exact promotion decision rule, a documented change-freeze policy, and a notification freeze that keeps alerts off for the entire evaluation window regardless of how interim results look.

## Tech stack

Python · XGBoost · scikit-learn · FinBERT (Hugging Face `transformers`) · pandas · SQLite · Optuna (hyperparameter tuning) · SHAP (feature importance) · systemd · Oracle Cloud Infrastructure · Finnhub, Alpaca Market Data & News APIs

## Current status

Deployed and running on a dual-source architecture (Alpaca News primary, Finnhub coverage-logged), with corrected real-time pricing and a hardened credential-handling path. The evaluation clock has been restarted more than once as genuine architecture corrections landed — each restart logged with its reasoning in `EVALUATION_PLAN.md` rather than treated as a footnote. Currently accumulating toward the pre-registered minimum sample before any promotion decision is made.

## On the development process

Built collaboratively with AI coding agents (Claude Code and others) under close direction and review — architecture, requirements, evaluation methodology, and verification of AI-produced work were owned throughout, including catching real bugs and false-positive results the agents' own testing missed on first pass. Not presented as "written by hand" — presented as an exercise in directing and rigorously validating AI-assisted engineering work, which is its own real skill.

## Disclaimer

This is a research and engineering project, not a live trading system and not investment advice. It has not yet cleared its own pre-registered bar for statistical significance, and no real capital has ever been risked on its output.
