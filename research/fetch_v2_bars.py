import sys, json, pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from news_signal.config import load_config
from news_signal.ingest.alpaca_bars import _headers
from research.shared.bars import fetch_daily_bars

cfg = load_config()
headers = _headers(cfg)
tickers = list(json.load(open(ROOT / "research" / "v2_target_ciks.json")).keys()) + ["SPY"]
print(f"[fetch] {len(tickers)} symbols, adjustment=all, SIP")

raw = fetch_daily_bars(tickers, "2022-06-01T00:00:00Z", "2026-09-22T00:00:00Z", adjustment="all", headers=headers)
print(f"[fetch] retrieved {len(raw)}/{len(tickers)} symbols; missing: {sorted(set(tickers) - set(raw.keys()))}")
pickle.dump(raw, open(ROOT / "research" / "v2_bars_raw.pkl", "wb"))
print("[done]")
