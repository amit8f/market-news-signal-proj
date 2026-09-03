import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands


def hourly_frame(minutes):
    agg = minutes.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return agg.dropna(subset=["close"])


def compute_hourly_indicators(h, cfg):
    close, high, low = h["close"], h["high"], h["low"]
    feats = pd.DataFrame(index=h.index)
    feats["rsi_14_1h"] = RSIIndicator(close=close, window=cfg["features"]["rsi_period"]).rsi()
    macd = MACD(
        close=close,
        window_slow=cfg["features"]["macd_slow"],
        window_fast=cfg["features"]["macd_fast"],
        window_sign=cfg["features"]["macd_signal"],
    )
    feats["macd_hist_1h"] = macd.macd_diff() / close
    bb = BollingerBands(close=close, window=cfg["features"]["bb_period"], window_dev=cfg["features"]["bb_std"])
    width = (bb.bollinger_hband() - bb.bollinger_lband()).replace(0, np.nan)
    feats["bb_pctb_1h"] = (close - bb.bollinger_lband()) / width
    feats["bb_width_1h"] = width / close
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    feats["atr14_1h_pct"] = tr.rolling(cfg["features"]["atr_period"]).mean() / close
    return feats


def session_vwap_before(minutes, sess_start, t):
    win = minutes.loc[(minutes.index >= sess_start) & (minutes.index < pd.Timestamp(t))]
    if not len(win):
        return np.nan, np.nan
    tp = (win["high"] + win["low"] + win["close"]) / 3.0
    vol = win["volume"].astype(float)
    total_vol = float(vol.sum())
    if total_vol <= 0:
        return np.nan, np.nan
    vwap = float((tp * vol).sum() / total_vol)
    last_close = float(win["close"].iloc[-1])
    dist = last_close / vwap - 1.0 if vwap > 0 else np.nan
    return vwap, dist


MIN_HOURLY_BARS = 30


def build_technical_features(events, minutes_by_ticker, sessions, cfg):
    out_parts = []
    skipped_warmup = 0
    for ticker, ev_group in events.groupby("ticker", sort=False):
        minutes = minutes_by_ticker[ticker]
        h = hourly_frame(minutes)
        ind = compute_hourly_indicators(h, cfg)
        hour_ends = h.index + pd.Timedelta(hours=1)
        sess_starts = sessions["sess_start"].values
        sess_ends = sessions["sess_end"].values
        for _, ev in ev_group.iterrows():
            t = pd.Timestamp(ev["published_utc"]).tz_convert("UTC")
            t_ns = np.datetime64(t.tz_localize(None))
            k = int(np.searchsorted(hour_ends.values.astype("datetime64[ns]"), t_ns, side="left") - 1)
            if k < MIN_HOURLY_BARS - 1:
                skipped_warmup += 1
                continue
            row = ind.iloc[k].to_dict()
            si = int(np.searchsorted(sess_starts.astype("datetime64[ns]"), t_ns, side="right") - 1)
            if si >= 0 and t_ns < sess_ends[si].astype("datetime64[ns]"):
                s0 = pd.Timestamp(sess_starts[si]).tz_localize("UTC")
                _, dist_vwap = session_vwap_before(minutes, s0, t)
                row["dist_from_vwap_pct"] = dist_vwap
            else:
                row["dist_from_vwap_pct"] = np.nan
            row["event_id"] = ev["event_id"]
            out_parts.append(row)
    feat_df = pd.DataFrame(out_parts)
    return feat_df, skipped_warmup
