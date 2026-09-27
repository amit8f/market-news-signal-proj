"""SIP daily bar fetch with pagination and a REQUIRED, explicit `adjustment` argument.

The v1 Form 4 study's original fetch had no `adjustment` parameter at all, which meant Alpaca's
undocumented default (`raw`) was used, and real stock splits (NKLA's 1-for-30, AVGO's 10-for-1)
showed up as fake multi-hundred-percent single-day moves. This module makes that mistake
structurally harder to repeat: there is no default value for `adjustment`.
"""
import re
import time

import numpy as np
import pandas as pd
import requests

BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"


def fetch_daily_bars(tickers, start, end, adjustment, headers, feed="sip", batch_size=50, pace_sec=0.3):
    """Paginated multi-symbol daily bar fetch. `adjustment` has no default - callers must
    decide (`"all"` for total-return-style studies, `"split"` for parity with the live
    system's training pipeline, `"raw"` only if genuinely intended). Returns
    {symbol: [bar dict, ...]}, tolerating individual invalid symbols (dropped, not fatal to
    the whole batch)."""
    assert adjustment in ("raw", "split", "all"), f"adjustment must be explicit, got {adjustment!r}"
    all_bars = {}
    tickers = list(tickers)
    for i in range(0, len(tickers), batch_size):
        batch = list(tickers[i:i + batch_size])
        while batch:
            page_token = None
            got_error = False
            while True:
                params = {"symbols": ",".join(batch), "timeframe": "1Day", "start": start, "end": end,
                          "feed": feed, "adjustment": adjustment, "limit": 10000}
                if page_token:
                    params["page_token"] = page_token
                r = requests.get(BARS_URL, headers=headers, params=params, timeout=60)
                if r.status_code != 200:
                    m = re.search(r'invalid symbol: ([^"]+)', r.text)
                    if m and m.group(1) in batch:
                        batch.remove(m.group(1))
                    else:
                        print(f"[bars] batch starting at {i} failed: {r.status_code} {r.text[:200]}")
                        time.sleep(3)
                    got_error = True
                    break
                payload = r.json()
                for sym, rows in payload.get("bars", {}).items():
                    all_bars.setdefault(sym, []).extend(rows)
                page_token = payload.get("next_page_token")
                time.sleep(pace_sec)
                if not page_token:
                    break
            if not got_error:
                break
    return all_bars


def to_frames(raw_bars, drop_zero_volume=True):
    """Converts {symbol: [bar dicts]} into {symbol: DataFrame} indexed by UTC-naive date.
    Drops zero-volume bars by default: a halted/dormant listing's frozen last-known price is
    not a real tradable price (confirmed on DTC/OABI/PRME/CZFS in the v1 study)."""
    frames = {}
    for sym, rows in raw_bars.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["t"] = pd.to_datetime(df["t"]).dt.tz_convert(None).dt.normalize()
        df = df.drop_duplicates("t").sort_values("t").set_index("t")
        if drop_zero_volume:
            df = df[df["v"] > 0]
        if len(df):
            frames[sym] = df
    return frames


def compute_adv(frames, start=None, end=None):
    """Average daily dollar volume (close * volume) per ticker over [start, end] (inclusive),
    from already-fetched daily bar frames (see to_frames)."""
    out = {}
    for sym, df in frames.items():
        d = df
        if start is not None:
            d = d[d.index >= pd.Timestamp(start)]
        if end is not None:
            d = d[d.index <= pd.Timestamp(end)]
        if len(d):
            out[sym] = float((d["c"] * d["v"]).mean())
    return out
