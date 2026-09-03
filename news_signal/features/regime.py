import numpy as np
import pandas as pd


def daily_closes_from_minutes(minutes):
    g = minutes.groupby(minutes.index.normalize())["close"].last()
    return g.sort_index()


def spy_regime_row(spy_daily_close, t, sma_fast=50, sma_slow=200):
    today = pd.Timestamp(t).normalize()
    hist = spy_daily_close.loc[spy_daily_close.index < today]
    if len(hist) < 30:
        return None
    out = {"spy_above_sma200": np.nan, "dist_sma50_pct": np.nan, "dist_sma200_pct": np.nan}
    last = float(hist.iloc[-1])
    if len(hist) >= sma_fast:
        out["dist_sma50_pct"] = last / float(hist.tail(sma_fast).mean()) - 1.0
    if len(hist) >= sma_slow:
        sma200 = float(hist.tail(sma_slow).mean())
        out["dist_sma200_pct"] = last / sma200 - 1.0
        out["spy_above_sma200"] = int(last > sma200)
    return out


def ticker_regime_row(daily_close, t, short_d=5, long_d=40):
    today = pd.Timestamp(t).normalize()
    hist = daily_close.loc[daily_close.index < today]
    if len(hist) < long_d + 2:
        return None
    logret = np.log(hist / hist.shift(1)).dropna()
    rv_short = float(logret.tail(short_d).std(ddof=1))
    rv_long = float(logret.tail(long_d).std(ddof=1))
    if not (rv_short >= 0 and rv_long > 0):
        return None
    mom5 = float(hist.iloc[-1] / hist.iloc[-min(6, len(hist))] - 1.0)
    return {
        "rv_short_5d": rv_short,
        "vol_ratio_5d_40d": rv_short / rv_long,
        "mom_5d": mom5,
    }


def add_regime_features(events, minutes_by_ticker, spy_daily_close, cfg):
    feat_cfg = cfg["features"]
    rows = []
    for _, ev in events.iterrows():
        t = ev["published_utc"]
        row = {"event_id": ev["event_id"]}
        spy_feats = spy_regime_row(
            spy_daily_close, t, feat_cfg["sma_fast"], min(feat_cfg["sma_slow"], 200)
        )
        if spy_feats:
            row.update(spy_feats)
        ticker_feats = ticker_regime_row(
            daily_closes_from_minutes(minutes_by_ticker[ev["ticker"]]),
            t,
            feat_cfg["vol_regime_short_days"],
            feat_cfg["vol_regime_long_days"],
        )
        if ticker_feats:
            row.update(ticker_feats)
        rows.append(row)
    return pd.DataFrame(rows)


def attach_sector_features(events_feat, universe):
    sector_map = {row["ticker"]: row["sector"] for row in universe}
    df = events_feat.copy()
    df["sector"] = df["ticker"].map(sector_map)
    df["published_date"] = pd.to_datetime(df["published_utc"]).dt.normalize()
    for col in ["mom_5d", "sector_mean_mom5d", "sector_rel_mom5d"]:
        if col not in df.columns:
            df[col] = np.nan
    has_mom = df.dropna(subset=["mom_5d"])
    if len(has_mom):
        day_sector_mean = has_mom.groupby(["published_date", "sector"])["mom_5d"].transform("mean")
        idx = has_mom.index
        df.loc[idx, "sector_mean_mom5d"] = day_sector_mean.values
    else:
        df["sector_mean_mom5d"] = np.nan
    df["sector_rel_mom5d"] = df["mom_5d"] - df["sector_mean_mom5d"]
    dummies = pd.get_dummies(df["sector"], prefix="sect")
    for c in dummies.columns:
        df[c] = dummies[c].astype(int)
    return df
