import sys, json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.shared import dera

DERA_DIR = ROOT / "data" / "external" / "dera"
QUARTERS = ["2024q1", "2024q2", "2024q3", "2024q4", "2025q1", "2025q2", "2025q3", "2025q4", "2026q1", "2026q2"]
quarter_dirs = {q: DERA_DIR / f"form345_{q}" for q in QUARTERS}
assert all(d.exists() for d in quarter_dirs.values()), f"missing a cached DERA quarter directory under {DERA_DIR}"

target_ciks = {int(v): k for k, v in json.load(open(ROOT / "research" / "v2_target_ciks.json")).items()}
# target_ciks here: cik -> ticker (build_purchase_events expects cik_to_ticker)

events, diag = dera.build_purchase_events(quarter_dirs, cik_to_ticker=target_ciks)
print("per-quarter diagnostics (candidate submissions / P-lines / filings):")
for q, d in diag.items():
    print(f"  {q}: {d}")

print(f"\ntotal distinct filings (events): {len(events)}")
print(f"date range: {events['FILING_DATE'].min()} .. {events['FILING_DATE'].max()}")
print(f"voluntary (non-10b5-1): {(~events['is_10b5_1']).sum()} / planned (10b5-1): {events['is_10b5_1'].sum()}")
events["year"] = events["FILING_DATE"].dt.year
print("\nevents per year (all / voluntary):")
for y, g in events.groupby("year"):
    print(f"  {y}: total={len(g)}  voluntary={(~g['is_10b5_1']).sum()}")

print("\nrole distribution:", events["role"].value_counts().to_dict())
print("size distribution:", events["size_bucket"].value_counts().to_dict())
print("cluster distribution:", events["is_cluster"].value_counts().to_dict())

events.to_parquet(ROOT / "research" / "v2_events.parquet")
print(f"\n[done] {len(events)} events, {events['ticker'].nunique()} distinct tickers with >=1 purchase event")
