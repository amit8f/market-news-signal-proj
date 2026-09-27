import sys, json
from pathlib import Path
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.shared.env import sec_headers

headers = sec_headers()
v2 = pd.read_csv(ROOT / "research" / "v2_universe.csv")

r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=30)
ticker_to_cik = {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}

v2["cik_final"] = v2["dera_cik"]
miss = v2["cik_final"].isna()
v2.loc[miss, "cik_final"] = v2.loc[miss, "ticker_primary"].str.upper().map(ticker_to_cik)
n_miss = v2["cik_final"].isna().sum()
print(f"CIK resolved for {len(v2) - n_miss}/{len(v2)}; unresolved: {v2[v2['cik_final'].isna()]['ticker_primary'].tolist()}")

v2 = v2[v2["cik_final"].notna()].copy()
v2["cik_final"] = v2["cik_final"].astype(int)
target_ciks = dict(zip(v2["ticker_primary"], v2["cik_final"]))
json.dump(target_ciks, open(ROOT / "research" / "v2_target_ciks.json", "w"))
v2.to_csv(ROOT / "research" / "v2_universe_final.csv", index=False)
print(f"[done] v2 target tickers with a CIK: {len(target_ciks)}")
