import numpy as np
import pandas as pd


def et_hhmm_to_utc(date_str, hhmm):
    digits = str(hhmm).replace(":", "").zfill(4)
    ts = pd.Timestamp(f"{date_str} {digits[:2]}:{digits[2:]}", tz="America/New_York")
    return ts.tz_convert("UTC")


def build_sessions(calendar_csv):
    cal = pd.read_csv(calendar_csv)
    sessions = pd.DataFrame(
        {
            "sess_start": [et_hhmm_to_utc(d, o) for d, o in zip(cal["date"], cal["open"])],
            "sess_end": [et_hhmm_to_utc(d, c) for d, c in zip(cal["date"], cal["close"])],
        }
    ).sort_values("sess_start").reset_index(drop=True)
    return sessions


def filter_regular_minutes(minutes_df, sessions):
    idx = minutes_df.sort_index().index
    ts = idx.values
    mask = np.zeros(len(ts), dtype=bool)
    starts = sessions["sess_start"].values.astype("datetime64[ns]")
    ends = sessions["sess_end"].values.astype("datetime64[ns]")
    for s, e in zip(starts, ends):
        mask |= (ts >= s) & (ts < e)
    out = minutes_df.iloc[mask]
    return out[~out.index.duplicated(keep="first")].sort_index()


def compute_events(news_df, minutes, ticker, sessions, horizon_minutes=120, entry_max_delay_min=15):
    records = []
    starts = minutes.index.values
    opens = minutes["open"].values
    closes = minutes["close"].values
    sess_starts = sessions["sess_start"].values.astype("datetime64[ns]")
    sess_ends = sessions["sess_end"].values.astype("datetime64[ns]")
    max_delay_ns = np.timedelta64(int(entry_max_delay_min * 60), "s")
    zero = np.timedelta64(0, "s")

    for _, ev in news_df.iterrows():
        t = np.datetime64(ev["published_utc"].tz_convert("UTC").tz_localize(None))
        i0 = int(np.searchsorted(starts, t, side="left"))
        if i0 >= len(starts):
            continue
        entry_ts = starts[i0]
        si = int(np.searchsorted(sess_starts, t, side="right") - 1)
        inside = si >= 0 and t < sess_ends[si]
        if inside:
            anchor = t
            j = int(np.searchsorted(sess_starts, entry_ts, side="right") - 1)
            if j != si or entry_ts >= sess_ends[si]:
                continue
        else:
            j = int(np.searchsorted(sess_ends, entry_ts, side="left"))
            if j >= len(sessions) or entry_ts < sess_starts[j] or entry_ts >= sess_ends[j]:
                continue
            anchor = sess_starts[j]
        delay = entry_ts - anchor
        if delay > max_delay_ns or delay < zero:
            continue
        exit_i = i0 + horizon_minutes
        if exit_i >= len(starts):
            continue
        entry_price = float(opens[i0])
        exit_price = float(closes[exit_i])
        if not (entry_price > 0 and exit_price > 0):
            continue
        records.append(
            {
                "ticker": ticker,
                "headline": ev["headline"],
                "summary": str(ev.get("summary", "") or ""),
                "source": ev.get("source", ""),
                "url": ev.get("url", ""),
                "published_epoch": int(ev["published_epoch"]),
                "published_utc": ev["published_utc"],
                "relevance_tier": int(ev["relevance_tier"]) if "relevance_tier" in news_df.columns and ev.get("relevance_tier") is not None else 0,
                "entry_ts": pd.Timestamp(entry_ts, tz="UTC"),
                "delay_sec": int(delay / np.timedelta64(1, "s")),
                "entry_price": entry_price,
                "exit_ts": pd.Timestamp(starts[exit_i], tz="UTC"),
                "exit_price": exit_price,
                "fwd_ret_2h": exit_price / entry_price - 1.0,
            }
        )
    return pd.DataFrame(records)


def typical_vol_sigma(minutes, horizon_minutes=120, warmup_bars=60, step=30):
    closes = minutes["close"].values.astype(float)
    n = len(closes)
    rets = []
    for a in range(warmup_bars, n - horizon_minutes, step):
        rets.append(closes[a + horizon_minutes] / closes[a] - 1.0)
    if len(rets) < 20:
        return None, len(rets)
    return float(np.std(np.asarray(rets), ddof=1)), len(rets)


def trailing_sigma_series(minutes, horizon_minutes=120, warmup_bars=60, step=30):
    closes = minutes["close"].values.astype(float)
    idx_ns = minutes.index.values.astype("datetime64[ns]")
    n = len(closes)
    positions = np.arange(warmup_bars, max(n - horizon_minutes, warmup_bars), step)
    if len(positions) < 5:
        empty_t = np.array([], dtype="datetime64[ns]")
        return empty_t, np.array([])
    rets = closes[positions + horizon_minutes] / closes[positions] - 1.0
    end_ts = idx_ns[positions + horizon_minutes]
    order = np.argsort(end_ts)
    return end_ts[order], rets[order]


def trailing_sigma_at(end_ts, rets, t_naive_ns, min_anchors=30):
    k = int(np.searchsorted(end_ts, t_naive_ns, side="left"))
    if k < min_anchors:
        return None
    return float(np.std(rets[:k], ddof=1))
