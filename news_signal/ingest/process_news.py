import json
import re
from pathlib import Path

import pandas as pd


def normalize_headline(h):
    return re.sub(r"[^a-z0-9]+", " ", str(h).lower()).strip()


def load_and_dedupe_news(tickers, raw_dir):
    frames = []
    for t in tickers:
        path = Path(raw_dir) / f"{t}.json"
        if not path.exists():
            continue
        items = json.loads(path.read_text(encoding="utf-8"))
        if not items:
            continue
        df = pd.DataFrame(items)
        df["ticker"] = t
        frames.append(df)
    base_cols = ["ticker", "headline", "summary", "source", "url", "published_epoch", "published_utc"]
    if not frames:
        return pd.DataFrame(columns=base_cols)
    df = pd.concat(frames, ignore_index=True)
    df = df[df["headline"].notna() & df["datetime"].notna()].copy()
    df["published_utc"] = pd.to_datetime(df["datetime"], unit="s", utc=True)
    df = df.sort_values(["ticker", "published_utc"]).reset_index(drop=True)
    norm = df["headline"].map(normalize_headline)
    key_prefix = norm.str.slice(0, 48)
    same_prev_ticker = df["ticker"] == df["ticker"].shift(1)
    near_dup = (key_prefix == key_prefix.shift(1)) & same_prev_ticker & (
        (df["published_utc"] - df["published_utc"].shift(1)) <= pd.Timedelta(minutes=10)
    )
    tmp_exact = pd.DataFrame({"t": df["ticker"].values, "k": norm.values})
    exact_dup = tmp_exact.duplicated()
    out = df[~(near_dup.fillna(False)).values & ~exact_dup.values].copy()
    out["published_epoch"] = out["datetime"].astype("int64")
    cols = [c for c in base_cols if c in out.columns]
    return out[cols].reset_index(drop=True)
