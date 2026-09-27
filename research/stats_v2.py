import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.shared.returns import month_clustered_diff_test, vs_zero, HORIZONS

scored = pd.read_parquet(ROOT / "research" / "v2_events_scored.parquet")
pop = pd.read_parquet(ROOT / "research" / "v2_population_eligible.parquet")
scored["month"] = pd.to_datetime(scored["FILING_DATE"]).dt.to_period("M").astype(str)

voluntary = scored[~scored["is_10b5_1"]].copy()
w_ev = voluntary.groupby("ticker").size()


def pf(x, d=3):
    return "nan" if pd.isna(x) else f"{x*100:+.{d}f}%"


def matched_pop(col_h):
    p = pop[pop.ticker.isin(w_ev.index)].dropna(subset=[col_h]).copy()
    n_t = p.groupby("ticker").size()
    p["w"] = p.ticker.map(w_ev) / p.ticker.map(n_t)
    return p


print("=" * 110)
print("PRIMARY TEST (pre-registered): voluntary purchases (ALL v2, 1,471 tickers) 20d beta-adj")
print("MINUS ticker-mix-matched full eligible population baseline")
print("=" * 110)
E = voluntary.dropna(subset=["adj_ret_20d"])
P = matched_pop("adj_ret_20d")
r = month_clustered_diff_test(E["adj_ret_20d"].values, E["month"].values, P["adj_ret_20d"].values, P["month"].values, P["w"].values)
print(f"events n={r['nE']} mean={pf(r['meanE'])} | population n={r['nP']} (weighted mean) {pf(r['meanP'])}")
print(f"DIFFERENCE = {pf(r['diff'])}  se={pf(r['se'])}  month-clustered t={r['t']:+.3f} (G={r['G']}, p={r['p']:.4f})")
print(f"bootstrap 95% CI (resampling calendar months) = [{pf(r['lo'])}, {pf(r['hi'])}]")
primary = r

print("\nSECONDARY: voluntary events alone vs zero")
s = vs_zero(E, "adj_ret_20d")
print(f"n={s['n']} n_months={s['n_months']} mean={pf(s['mean'])} median={pf(s['median'])} win={s['win']:.1%} t={s['t']:+.3f} CI=[{pf(s['lo'])}, {pf(s['hi'])}]")

print("\nEXPLORATORY: primary comparison at other horizons")
for h in [5, 60]:
    col = f"adj_ret_{h}d"
    Eh = voluntary.dropna(subset=[col])
    Ph = matched_pop(col)
    rr = month_clustered_diff_test(Eh[col].values, Eh["month"].values, Ph[col].values, Ph["month"].values, Ph["w"].values)
    print(f"  {h}d: event {pf(rr['meanE'])} pop {pf(rr['meanP'])} diff {pf(rr['diff'])} t={rr['t']:+.3f} CI=[{pf(rr['lo'])}, {pf(rr['hi'])}] nE={rr['nE']}")

print("\nEXPLORATORY: primary test rerun on the v1 100-ticker sample (comparison cell, not a hold-out)")
V1_DIR = ROOT / "data" / "external" / "universe" / "v1"
v1_tickers = set(pd.read_csv(V1_DIR / "final_sample_100_withcik.csv")["ticker_primary"])
v1_events = pd.read_parquet(V1_DIR / "events_scored_adj2.parquet")
v1_events["month"] = pd.to_datetime(v1_events["FILING_DATE"]).dt.to_period("M").astype(str)
v1_vol = v1_events[(v1_events.universe == "small_100") & (~v1_events.is_10b5_1)].dropna(subset=["adj_ret_20d"])
v1_base = pd.read_parquet(V1_DIR / "baseline_scored_adj2.parquet")
v1_base["month"] = pd.to_datetime(v1_base["anchor_date"]).dt.to_period("M").astype(str)
print(f"  (for reference, v1's own draw-based result: n={len(v1_vol)} mean={pf(v1_vol.adj_ret_20d.mean())}; already reported in outputs/form4_study.md)")

print("\n" + "=" * 110)
print("EXPLORATORY SPLITS (each cell vs zero, and minus the ticker-mix-matched population), all v2")
print("=" * 110)
rows = []
cells = [
    ("ALL v2 events", scored), ("voluntary (non-10b5-1)", voluntary), ("10b5_1=True (planned)", scored[scored.is_10b5_1]),
    ("role=CEO_CFO", voluntary[voluntary.role == "CEO_CFO"]), ("role=Director", voluntary[voluntary.role == "Director"]), ("role=Other", voluntary[voluntary.role == "Other"]),
    ("size=<$50k", voluntary[voluntary.size_bucket == "<$50k"]), ("size=$50k-$500k", voluntary[voluntary.size_bucket == "$50k-$500k"]), ("size=>$500k", voluntary[voluntary.size_bucket == ">$500k"]),
    ("cluster=True", voluntary[voluntary.is_cluster]), ("cluster=False", voluntary[~voluntary.is_cluster]),
]
for h in HORIZONS:
    col = f"adj_ret_{h}d"
    print(f"\n--- {h}d ---")
    for name, sub in cells:
        subc = sub.dropna(subset=[col])
        z = vs_zero(subc, col)
        thin = " **THIN (n<30)**" if z["n"] < 30 else ""
        popc = matched_pop(col) if "matched to voluntary" or True else None
        # for splits, match population weights to THIS cell's per-ticker event counts, not all-voluntary
        w_cell = subc.groupby("ticker").size()
        p = pop[pop.ticker.isin(w_cell.index)].dropna(subset=[col]).copy()
        if len(p) and len(subc):
            n_t = p.groupby("ticker").size()
            p["w"] = p.ticker.map(w_cell) / p.ticker.map(n_t)
            d = month_clustered_diff_test(subc[col].values, subc["month"].values, p[col].values, p["month"].values, p["w"].values)
            diff_str = f"{pf(d['diff'])} | t={d['t']:+.2f} | CI=[{pf(d['lo'])},{pf(d['hi'])}]"
        else:
            diff_str = "n/a"
        print(f"  {name:<24} n={z['n']:>5} mean={pf(z['mean'])} med={pf(z['median'])} win={z['win']:.1%} t0={z['t']:+.2f} CI0=[{pf(z['lo'])},{pf(z['hi'])}] | minus pop: {diff_str}{thin}")
        rows.append(dict(h=h, cell=name, n=z["n"], n_months=z.get("n_months"), mean=z.get("mean"), median=z.get("median"),
                         win=z.get("win"), t0=z.get("t"), lo0=z.get("lo"), hi0=z.get("hi"), thin=z["n"] < 30))

pd.DataFrame(rows).to_csv(ROOT / "research" / "v2_stats_cells.csv", index=False)
json.dump(primary, open(ROOT / "research" / "v2_primary.json", "w"), default=float, indent=1)
print("\n[done]")
