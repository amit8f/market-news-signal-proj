import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)

df = pd.read_parquet(ROOT / "data" / "processed" / "milestone_events.parquet")
print(f"shape: {df.shape}")
print(f"news span: {df['published_utc'].min()} .. {df['published_utc'].max()}")
print("\nrelevance tier counts:")
print(df["relevance_tier"].value_counts().sort_index().to_string())
print("\nper-ticker event counts:")
print(df["ticker"].value_counts().to_string())
print("\nnews_type counts:")
print(df["news_type"].value_counts().to_string())
sig = df.dropna(subset=["sigma_2h"]).groupby("ticker")["sigma_2h"].agg(["count", "min", "median", "max"])
print("\ntrailing sigma_2h per ticker (varies over time => strictly trailing):")
print(sig.round(5).to_string())
cols = ["ticker", "relevance_tier", "sent_score", "news_type", "pub_hour_et", "entry_price", "fwd_ret_2h"]
print("\nsample rows:")
print(df[cols].sample(8, random_state=7).round(4).to_string(index=False))
print("\ntier-1 primary examples:")
t1 = df[df["relevance_tier"] == 1].sample(4, random_state=1)
for r in t1.itertuples(index=False):
    print(f"  [{r.ticker}] {r.headline[:95]}")
print("dropped-tier (passing) examples from same raw pool would look like:")
t2 = df[df["relevance_tier"] == 2].sample(min(4, int((df["relevance_tier"] == 2).sum())), random_state=1)
for r in t2.itertuples(index=False):
    print(f"  [{r.ticker} tier2] {r.headline[:95]}")
