import sys, json, pickle
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.shared.bars import to_frames
from research.shared.returns import score_events, build_eligible_population, HORIZONS

raw = pickle.load(open(ROOT / "research" / "v2_bars_raw.pkl", "rb"))
bars = to_frames(raw)
spy = bars["SPY"]
spy_ret = spy["c"].pct_change()

events = pd.read_parquet(ROOT / "research" / "v2_events.parquet")
events["FILING_DATE"] = pd.to_datetime(events["FILING_DATE"]).dt.normalize()

scored = score_events(events, bars, spy, spy_ret)
print(f"[score] real events scored: {len(scored)}/{len(events)}")
for h in HORIZONS:
    print(f"  {h}d truncated (delisting/halt-gap): {int(scored[f'truncated_{h}d'].sum())}")
scored.to_parquet(ROOT / "research" / "v2_events_scored.parquet")

# --- full eligible population, ticker-mix-matched to voluntary events ---
voluntary = scored[~scored["is_10b5_1"]]
event_dates_by_ticker = events.groupby("ticker")["FILING_DATE"].apply(list).to_dict()
w_ev = voluntary.groupby("ticker").size()

tickers = sorted(set(events["ticker"]) & set(bars.keys()))
pop = build_eligible_population(
    tickers, bars, spy, spy_ret, event_dates_by_ticker,
    window_start="2024-01-01", window_end="2026-06-30",
)
pop["month"] = pop["date"].dt.to_period("M").astype(str)
pop_elig = pop[pop["eligible"]].copy()
print(f"\n[population] eligible non-event ticker-days across {pop_elig.ticker.nunique()} tickers: {len(pop_elig):,}")
pop_elig.to_parquet(ROOT / "research" / "v2_population_eligible.parquet")

# validation: vectorised population construction vs the row-by-row study values, at real event anchors
chk = voluntary.merge(
    pop[["ticker", "date", "adj_ret_20d"]].rename(columns={"adj_ret_20d": "y_pop"}),
    left_on=["ticker", "FILING_DATE"], right_on=["ticker", "date"], how="inner",
)
if len(chk):
    diff = (chk["y_pop"] - chk["adj_ret_20d"]).abs()
    print(f"[validation] matched {len(chk)}/{len(voluntary)} | mean abs diff (vectorised vs per-event) = {diff.mean()*100:.4f}pp | corr = {np.corrcoef(chk.y_pop.fillna(0), chk.adj_ret_20d.fillna(0))[0,1]:.4f}")
print("[done]")
