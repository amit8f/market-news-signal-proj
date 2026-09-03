import numpy as np
import pandas as pd

from news_signal.features.relevance import relevance_tier as _tier, build_matchers
from news_signal.features.sentiment import score_with_cache
from news_signal.features.news_type import classify
from news_signal.features.technical import build_technical_features
from news_signal.features.regime import add_regime_features, attach_sector_features
from news_signal.models.features import build_feature_matrix


def sector_peer_mean(ticker, universe, published_utc, peer_loader):
    sector = next((r["sector"] for r in universe if r["ticker"] == ticker), None)
    if sector is None:
        return np.nan
    peers = [r["ticker"] for r in universe if r["sector"] == sector]
    ref_date = pd.Timestamp(published_utc).tz_convert("UTC").normalize()
    from news_signal.features.regime import daily_closes_from_minutes

    vals = []
    for p in peers:
        m = peer_loader(p) if peer_loader else None
        if m is None or len(m) < 200:
            continue
        dc = daily_closes_from_minutes(m)
        hist = dc[dc.index < ref_date]
        if len(hist) < 6:
            continue
        vals.append(float(hist.iloc[-1] / hist.iloc[-min(6, len(hist))] - 1.0))
    return float(np.mean(vals)) if vals else np.nan


def build_event_frame(ticker, headline, summary, source, published_utc, profiles, universe,
                      minutes_by_ticker, sessions, spy_daily_close, cfg, recency_hours, prior_24h,
                      expected_columns=None, peer_loader=None):
    from news_signal.models.features import TECHNICAL_COLS, REGIME_COLS, CONTEXT_COLS

    matchers = build_matchers(universe, profiles)
    tier = _tier(ticker, headline, summary, matchers)
    if tier >= 3:
        return None, {"reason": "passing_mention"}
    info = {"tier": int(tier)}

    sent = score_with_cache([headline])
    event = pd.DataFrame(
        [
            {
                "event_id": "live",
                "ticker": ticker,
                "headline": headline,
                "summary": summary or "",
                "source": source or "",
                "url": "",
                "published_epoch": int(pd.Timestamp(published_utc).timestamp()),
                "published_utc": pd.Timestamp(published_utc),
                "relevance_tier": int(tier),
            }
        ]
    )
    tech_df, skipped = build_technical_features(event, minutes_by_ticker, sessions, cfg)
    if len(tech_df) == 0:
        return None, {"reason": f"insufficient_warmup({skipped})"}
    df = event.merge(tech_df, on="event_id", how="inner")
    regime_df = add_regime_features(df, minutes_by_ticker, spy_daily_close, cfg)
    df = df.merge(regime_df, on="event_id", how="left")
    df = attach_sector_features(df, universe)
    peer_mean = sector_peer_mean(ticker, universe, published_utc, peer_loader)
    if np.isfinite(peer_mean) and "mom_5d" in df.columns and np.isfinite(df["mom_5d"].iloc[0]):
        df["sector_mean_mom5d"] = peer_mean
        df["sector_rel_mom5d"] = float(df["mom_5d"].iloc[0]) - peer_mean
    for col in TECHNICAL_COLS + REGIME_COLS + CONTEXT_COLS:
        if col not in df.columns:
            df[col] = np.nan
    df["p_pos"], df["p_neg"], df["p_neu"], df["sent_score"] = sent.iloc[0].values
    df["news_type"] = classify(headline, summary or "")
    df["hours_since_prev_headline"] = recency_hours
    df["headlines_prior_24h"] = prior_24h
    et = pd.Timestamp(published_utc).tz_convert("America/New_York")
    df["pub_hour_et"] = et.hour + et.minute / 60.0

    end_ts, rets = trailing_series_for(minutes_by_ticker[ticker], cfg)
    t_ns = np.datetime64(pd.Timestamp(published_utc).tz_convert("UTC").tz_localize(None))
    from news_signal.labels.forward_returns import trailing_sigma_at

    sigma = trailing_sigma_at(end_ts, rets, t_ns)
    df["sigma_2h"] = sigma if sigma is not None else np.nan
    df["fwd_ret_2h"] = np.nan
    df["label"] = 0
    df["label_name"] = "Neutral"
    X, meta = build_feature_matrix(df)
    if expected_columns is not None:
        X = X.reindex(columns=list(expected_columns))
        for c in X.columns:
            if (c.startswith("sect_") or c.startswith("nt_")) and X[c].isna().iloc[0]:
                X[c] = 0.0
    info["sigma_2h"] = float(df["sigma_2h"].iloc[0])
    info["tier"] = int(tier)
    return X, info


def trailing_series_for(minutes, cfg):
    from news_signal.labels.forward_returns import trailing_sigma_series

    horizon = cfg["labels"]["horizon_minutes"]
    return trailing_sigma_series(minutes, horizon_minutes=horizon)


def simulate_exit(minutes, entry_ts, exit_ts_target, entry_price, stop_price):
    idx = minutes.index
    i0 = int(idx.searchsorted(pd.Timestamp(entry_ts)))
    i1 = int(idx.searchsorted(pd.Timestamp(exit_ts_target)))
    if i0 >= len(idx) or i1 >= len(idx) or i1 < i0:
        return None
    for j in range(i0, i1 + 1):
        low, high, opn = float(minutes["low"].iloc[j]), float(minutes["high"].iloc[j]), float(minutes["open"].iloc[j])
        if low <= stop_price <= high:
            return {"exit_ts": idx[j].isoformat(), "exit_price": stop_price, "stopped": True}
        if high < stop_price:
            continue
        break
    exit_px = float(minutes["close"].iloc[i1])
    return {"exit_ts": idx[i1].isoformat(), "exit_price": exit_px, "stopped": False}


def decide(calibrated_row, thresholds, class_names, suppressed=("Sell",)):
    name_to_idx = {n: i for i, n in enumerate(class_names)}
    priority = ["Strong Buy", "Buy", "Sell"]
    fires = []
    for cls in priority:
        thr = thresholds.get(cls)
        if thr is None or cls in suppressed:
            continue
        p = float(calibrated_row[name_to_idx[cls]])
        if p >= thr:
            fires.append((cls, p))
    if not fires:
        best = int(np.argmax(calibrated_row))
        return {"status": "silent", "class": class_names[best], "prob_calibrated": float(calibrated_row[best])}
    for cls, p in sorted(fires, key=lambda t: priority.index(t[0])):
        return {"status": "fired", "class": cls, "prob_calibrated": p}
    return {"status": "silent", "class": None, "prob_calibrated": np.nan}
