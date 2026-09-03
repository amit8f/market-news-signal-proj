import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scipy import stats

from news_signal.config import load_config, raw_bars_dir

df = pd.read_parquet(ROOT / "data" / "processed" / "milestone_events.parquet")

print("=" * 72)
print("CHECK 1 - FINBERT SCORE DISTRIBUTION / VARIANCE")
print("=" * 72)
s = df["sent_score"]
print(s.describe().round(4).to_string())
print(f"\nstd: {s.std():.4f} | variance: {s.var():.4f}")
zero_band = ((s > -0.05) & (s < 0.05)).mean()
print(f"share within [-0.05, +0.05]: {zero_band:.1%}")
bins = [-1.01, -0.6, -0.2, 0.2, 0.6, 1.01]
labels = ["<=-0.6", "-0.6..-0.2", "-0.2..+0.2", "+0.2..+0.6", ">+0.6"]
print("\nscore bands:")
print(pd.cut(s, bins=bins, labels=labels).value_counts().reindex(labels).to_string())

print("\n" + "=" * 72)
print("CHECK 2 - UNIVARIATE SENTIMENT vs FORWARD RETURN (no model)")
print("=" * 72)
sub = df.dropna(subset=["sent_score", "fwd_ret_2h"])
pear = stats.pearsonr(sub["sent_score"], sub["fwd_ret_2h"])
spear = stats.spearmanr(sub["sent_score"], sub["fwd_ret_2h"])
score_norm = sub["fwd_ret_2h"] / sub["sigma_2h"]
pear_n = stats.pearsonr(sub["sent_score"], score_norm)
spear_n = stats.spearmanr(sub["sent_score"], score_norm)
print(f"Pearson  sent vs fwd_ret:      r={pear.statistic:+.4f}  p={pear.pvalue:.4f}")
print(f"Spearman sent vs fwd_ret:      rho={spear.statistic:+.4f} p={spear.pvalue:.4f}")
print(f"Pearson  sent vs vol-norm ret: r={pear_n.statistic:+.4f}  p={pear_n.pvalue:.4f}")
print(f"Spearman sent vs vol-norm ret: rho={spear_n.statistic:+.4f} p={spear_n.pvalue:.4f}")

q = pd.qcut(sub["sent_score"].rank(method="first"), 10, labels=False)
mono = sub.groupby(q)["fwd_ret_2h"].agg(["count", "mean"])
print("\nmean fwd_ret by sent_score decile (bottom->top):")
print(mono.round(5).to_string())
spread = mono["mean"].iloc[-1] - mono["mean"].iloc[0]
print(f"\ntop-minus-bottom decile spread: {spread:+.5f} ({spread * 1e4:.1f} bps)")

print("\nper news_type mean sent_score / mean fwd_ret:")
g = df.groupby("news_type").agg(n=("sent_score", "size"), mean_sent=("sent_score", "mean"), mean_fwd=("fwd_ret_2h", "mean"))
print(g.round(4).to_string())

t1 = df[df["relevance_tier"] == 1].dropna(subset=["sent_score", "fwd_ret_2h"])
sp1 = stats.spearmanr(t1["sent_score"], t1["fwd_ret_2h"])
print(f"\ntier-1-only Spearman: rho={sp1.statistic:+.4f} p={sp1.pvalue:.4f} (n={len(t1)})")

print("\n" + "=" * 72)
print("CHECK 3 - WEEK 2026-08-17 OUTCOME RESOLUTION")
print("=" * 72)
cfg = load_config()
wk_start = pd.Timestamp("2026-08-17", tz="UTC")
wk_end = wk_start + pd.Timedelta(days=7)
wk = df[(df["published_utc"] >= wk_start) & (df["published_utc"] < wk_end)]
print(f"events in week: {len(wk)}")
print(f"entry_ts range: {wk['entry_ts'].min()} .. {wk['entry_ts'].max()}")
print(f"exit_ts  range: {wk['exit_ts'].min()} .. {wk['exit_ts'].max()}")

last_bar = {}
for t in wk["ticker"].unique():
    path = raw_bars_dir() / f"{t}_1min.csv"
    idx = pd.read_csv(path, index_col=0, usecols=[0]).index
    idx = pd.to_datetime(idx, utc=True)
    last_bar[t] = idx.max()

wk = wk.copy()
wk["last_bar"] = wk["ticker"].map(last_bar)
wk["margin_hours"] = (wk["last_bar"] - wk["exit_ts"]).dt.total_seconds() / 3600.0
bad = wk[wk["margin_hours"] <= 0]
print(f"\nevents whose exit exceeds their ticker's last bar: {len(bad)}")
print(f"min margin after exit (hours): {wk['margin_hours'].min():.1f}")
print("margin distribution:")
print(pd.cut(wk["margin_hours"], [0, 24, 72, 168, 10000], labels=["<1d", "1-3d", "3-7d", ">7d"]).value_counts().to_string())

n_unres_possible = len(df[df["exit_ts"] >= pd.to_datetime(df["ticker"].map(last_bar))])
print(f"\nany event in whole dataset with unresolved exit: {n_unres_possible}")
print("(build-time rule: any news lacking 120 forward session bars was never emitted as an event)")
