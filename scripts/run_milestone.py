import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from news_signal.config import load_config, raw_news_dir, raw_bars_dir, calendar_path, processed_dir, outputs_dir
from news_signal.ingest.finnhub_news import pull_all_news, pull_company_profiles
from news_signal.ingest.alpaca_bars import fetch_calendar, pull_all_bars
from news_signal.ingest.process_news import load_and_dedupe_news
from news_signal.labels.forward_returns import (
    build_sessions,
    filter_regular_minutes,
    compute_events,
    trailing_sigma_series,
    trailing_sigma_at,
)
from news_signal.features.relevance import tag_relevance, filter_relevance
from news_signal.features.technical import build_technical_features
from news_signal.features.regime import add_regime_features, attach_sector_features
from news_signal.features.sentiment import score_with_cache
from news_signal.features.news_type import classify


def stage_ingest(cfg):
    counts = pull_all_news(cfg)
    print(f"[ingest] finnhub done: {sum(counts.values())} raw items across {len(counts)} tickers")
    fetch_calendar(cfg)
    print("[ingest] calendar saved")
    pull_all_bars(cfg)
    print("[ingest] alpaca bars done")


def _load_minutes(ticker, sessions):
    path = raw_bars_dir() / f"{ticker}_1min.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    return filter_regular_minutes(df, sessions)


def _recency_features(news_df, events):
    rows = []
    for ticker, grp in news_df.groupby("ticker"):
        times = np.sort(grp["published_utc"].values)
        sub = events[events["ticker"] == ticker]
        for _, ev in sub.iterrows():
            t = np.datetime64(pd.Timestamp(ev["published_utc"]).tz_convert("UTC").tz_localize(None))
            i = int(np.searchsorted(times, t, side="left"))
            prev = times[i - 1] if i > 0 else None
            hours = float((t - prev) / np.timedelta64(1, "h")) if prev is not None else np.nan
            lo = int(np.searchsorted(times, t - np.timedelta64(24, "h"), side="right"))
            rows.append({"event_id": ev["event_id"], "hours_since_prev_headline": hours, "headlines_prior_24h": i - lo})
    return pd.DataFrame(rows)


def _sanity_checks(labeled):
    pub = pd.to_datetime(labeled["published_utc"])
    entry = pd.to_datetime(labeled["entry_ts"])
    exit_ = pd.to_datetime(labeled["exit_ts"])
    assert (entry >= pub).all(), "LEAKAGE CHECK FAILED: some entries precede news time"
    assert (exit_ > entry).all(), "LEAKAGE CHECK FAILED: exit before entry"
    pub_et = pub.dt.tz_convert("America/New_York").dt.date
    entry_et = entry.dt.tz_convert("America/New_York").dt.date
    n_overnight = int((entry_et != pub_et).sum())
    delays_min = labeled["delay_sec"] / 60.0
    print(
        f"[checks] all {len(labeled)} events pass ordering; overnight/next-session aligned: {n_overnight}; "
        f"median delay {delays_min.median():.2f} min, p95 {delays_min.quantile(0.95):.2f} min"
    )
    return n_overnight


def stage_build(cfg):
    sessions = build_sessions(calendar_path())
    tickers = [row["ticker"] for row in cfg["universe"]]
    universe = cfg["universe"]
    horizon = cfg["labels"]["horizon_minutes"]

    profiles = pull_company_profiles(cfg)
    news_df = load_and_dedupe_news(tickers, raw_news_dir())
    n_deduped = len(news_df)
    news_df = tag_relevance(news_df, universe, profiles, strict_sources=[])
    news_df, tier_counts = filter_relevance(news_df, drop_non_primary=True)
    print(f"[build] deduped {n_deduped} | relevance tiers: {tier_counts} | after filter: {len(news_df)}")

    minutes_by_ticker = {}
    sigma_series_by_ticker = {}
    for t in tickers:
        m = _load_minutes(t, sessions)
        if m is None or len(m) < 500:
            print(f"[build] WARNING: {t} has insufficient bar data ({0 if m is None else len(m)} regular bars), skipping")
            continue
        minutes_by_ticker[t] = m
        sigma_series_by_ticker[t] = trailing_sigma_series(m, horizon_minutes=horizon)

    parts = []
    for t, m in minutes_by_ticker.items():
        ev = compute_events(news_df[news_df["ticker"] == t], m, t, sessions,
                            horizon_minutes=horizon,
                            entry_max_delay_min=cfg["labels"]["entry_max_delay_minutes"])
        parts.append(ev)
    events = pd.concat(parts, ignore_index=True)
    events["event_id"] = (
        events["ticker"]
        + "_"
        + events["published_epoch"].astype(str)
        + "_"
        + events.groupby(["ticker", "published_epoch"]).cumcount().astype(str)
    )
    sigmas = []
    for _, row in events.iterrows():
        end_ts, rets = sigma_series_by_ticker[row["ticker"]]
        t_ns = np.datetime64(pd.Timestamp(row["published_utc"]).tz_convert("UTC").tz_localize(None))
        sigmas.append(trailing_sigma_at(end_ts, rets, t_ns))
    events["sigma_2h"] = sigmas
    print(f"[build] aligned events: {len(events)} across {len(minutes_by_ticker)} tickers")

    tech_df, skipped_warmup = build_technical_features(events, minutes_by_ticker, sessions, cfg)
    print(f"[build] technical features: {len(tech_df)} events (skipped warmup: {skipped_warmup})")

    df = events.merge(tech_df, on="event_id", how="inner")
    regime_df = add_regime_features(df, minutes_by_ticker, _spy_daily_close(cfg), cfg)
    df = df.merge(regime_df, on="event_id", how="left")
    df = attach_sector_features(df, universe)

    sent = score_with_cache(list(df["headline"]))
    df[["p_pos", "p_neg", "p_neu", "sent_score"]] = sent.values

    df["news_type"] = [classify(h, s) for h, s in zip(df["headline"], df["summary"])]

    rec = _recency_features(news_df, df)
    df = df.merge(rec, on="event_id", how="left")
    et = pd.to_datetime(df["published_utc"]).dt.tz_convert("America/New_York")
    df["pub_hour_et"] = et.dt.hour + et.dt.minute / 60.0

    n_overnight = _sanity_checks(df)

    out_parquet = processed_dir() / "milestone_events.parquet"
    df.to_parquet(out_parquet, index=False)

    summary = _make_summary(cfg, df, tier_counts, skipped_warmup, n_overnight, n_deduped)
    out_txt = outputs_dir() / "milestone_summary.txt"
    out_txt.write_text(summary, encoding="utf-8")
    print(summary)
    print(f"\n[done] dataset -> {out_parquet}")
    print(f"[done] summary  -> {out_txt}")


def _spy_daily_close(cfg):
    path = raw_bars_dir() / f"{cfg['benchmark']}_1day.csv"
    s = pd.read_csv(path, index_col=0)["close"]
    s.index = pd.to_datetime(s.index, utc=True).normalize()
    return s.sort_index()


def _make_summary(cfg, df, tier_counts, skipped_warmup, n_overnight, n_deduped):
    lines = []
    ap = lines.append
    ap("=" * 72)
    ap("MILESTONE SLICE - EVENTS DATASET SUMMARY (labels frozen at train split)")
    ap("=" * 72)
    ap(f"universe: {len(cfg['universe'])} tickers | news window: {cfg['dates']['news_start']} .. {cfg['dates']['news_end']}")
    ap(f"horizon: {cfg['labels']['horizon_minutes']} trading minutes | entry max delay: {cfg['labels']['entry_max_delay_minutes']} min")
    ap("")
    ap("-- pipeline funnel --")
    ap(f"deduped news items:                 {n_deduped}")
    ap(f"relevance tiers (1=primary, 2=secondary, 3=passing): {tier_counts}")
    ap(f"after relevance filter:             {len(df) + skipped_warmup}")
    ap(f"dropped (insufficient hourly warmup): {skipped_warmup}")
    ap(f"final events with features:         {len(df)}")
    ap(f"overnight-aligned to next open:     {n_overnight}")
    ap("")
    ap("-- relevance tier distribution in final dataset --")
    for tier, name in [(1, "primary subject"), (2, "secondary mention"), (3, "passing")]:
        c = int((df["relevance_tier"] == tier).sum())
        ap(f"  tier {tier} ({name:<17}) {c:>6}  ({c / len(df):.1%})")
    ap("")
    ap("-- per-ticker median trailing sigma (2h) --")
    med = df.groupby("ticker")["sigma_2h"].median().dropna().sort_values(ascending=False)
    for t, s in med.items():
        n_valid = int(df[(df["ticker"] == t)]["sigma_2h"].notna().sum())
        ap(f"  {t:<6} sigma={s:.4%}  (valid trailing sigma for {n_valid} events)")
    n_no_sigma = int(df["sigma_2h"].isna().sum())
    ap(f"  events without trailing sigma (excluded from labeling): {n_no_sigma}")
    ap("")
    ap("-- features present --")
    feats = [c for c in df.columns if c not in {
        "ticker", "headline", "summary", "source", "url", "published_epoch", "published_utc",
        "entry_ts", "exit_ts", "event_id", "sector"}]
    ap(f"  {len(feats)} columns: {', '.join(sorted(feats))}")
    ap("")
    ap("-- leakage guards applied --")
    ap("  * entry strictly at/after publish; exit exactly {} trading min later".format(cfg["labels"]["horizon_minutes"]))
    ap("  * hourly indicators taken from last COMPLETED hour bar only")
    ap("  * daily regime uses strictly prior-day closes")
    ap("  * sigma_2h is STRICTLY TRAILING per event (windows completed before publish)")
    ap("  * class quantile thresholds are NOT set here - fit once on train split in phase 4 and frozen")
    ap("  * sentiment from headline as published (no later corrections)")
    ap("  * relevance filter drops passing mentions before event construction")
    ap("  * walk-forward-safe by construction (no shuffle anywhere)")
    ap("=" * 72)
    return "\n".join(lines)


def stage_sentiment(cfg):
    tickers = [row["ticker"] for row in cfg["universe"]]
    news_df = load_and_dedupe_news(tickers, raw_news_dir())
    print(f"[sentiment-stage] deduped headlines: {len(news_df)}")
    score_with_cache(list(news_df["headline"]))
    print("[sentiment-stage] cache ready")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["ingest", "sentiment", "build", "all"], default="all")
    args = parser.parse_args()
    config = load_config()
    if args.stage in ("ingest", "sentiment", "all"):
        if args.stage == "ingest" or args.stage == "all":
            stage_ingest(config)
        if args.stage == "sentiment" or args.stage == "all":
            stage_sentiment(config)
    if args.stage in ("build", "all"):
        stage_build(config)
