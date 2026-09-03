import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from news_signal.config import load_config, calendar_path, raw_bars_dir, processed_dir
from news_signal.ingest.finnhub_news import pull_company_profiles
from news_signal.labels.forward_returns import build_sessions, filter_regular_minutes
from news_signal.live.pipeline import build_event_frame
from xgboost import XGBClassifier

_clf = XGBClassifier()
_clf.load_model(str(ROOT / "models" / "champion_xgb_4class.json"))
EXPECTED = _clf.get_booster().feature_names

pd.set_option("display.width", 200)

cfg = load_config()
sessions = build_sessions(calendar_path())
profiles = pull_company_profiles(cfg)
df = pd.read_parquet(processed_dir() / "milestone_events.parquet")

FEATURE_COLS = [
    "sent_score", "p_pos", "p_neg", "p_neu",
    "rsi_14_1h", "macd_hist_1h", "bb_pctb_1h", "bb_width_1h", "atr14_1h_pct", "dist_from_vwap_pct",
    "spy_above_sma200", "dist_sma50_pct", "dist_sma200_pct", "rv_short_5d", "vol_ratio_5d_40d",
    "mom_5d",
    "pub_hour_et", "relevance_tier", "sigma_2h",
]
SOFT_COLS = ["sector_mean_mom5d", "sector_rel_mom5d"]


def csv_minutes(ticker):
    path = raw_bars_dir() / f"{ticker}_1min.csv"
    if not path.exists():
        return None
    m = pd.read_csv(path, index_col=0)
    m.index = pd.to_datetime(m.index, utc=True)
    return filter_regular_minutes(m, sessions)

sample = df.groupby("ticker", group_keys=False).apply(lambda g: g.sample(min(1, len(g)), random_state=3))
print(f"parity check on {len(sample)} events (one per ticker), full cached bar history as input")
worst = {}
for _, ev in sample.iterrows():
    ticker = ev["ticker"]
    path = raw_bars_dir() / f"{ticker}_1min.csv"
    minutes_raw = pd.read_csv(path, index_col=0)
    minutes_raw.index = pd.to_datetime(minutes_raw.index, utc=True)
    minutes = filter_regular_minutes(minutes_raw, sessions)
    X, info = build_event_frame(
        ticker, ev["headline"], ev["summary"], ev["source"], ev["published_utc"],
        profiles, cfg["universe"], {ticker: minutes}, sessions,
        pd.read_csv(raw_bars_dir() / f"{cfg['benchmark']}_1day.csv", index_col=0)["close"].pipe(
            lambda s: s.set_axis(pd.to_datetime(s.index, utc=True).normalize())
        ).sort_index(),
        cfg, recency_hours=float(ev["hours_since_prev_headline"]), prior_24h=int(ev["headlines_prior_24h"]),
        expected_columns=EXPECTED, peer_loader=csv_minutes,
    )
    if X is None:
        print(f"  {ticker}: skipped ({info})")
        continue
    diffs = []
    for col in FEATURE_COLS:
        live_v = float(info["sigma_2h"]) if col == "sigma_2h" else float(X[col].iloc[0])
        offl_v = float(ev[col])
        d = abs(live_v - offl_v) / max(abs(offl_v), 1e-12) if not (np.isnan(live_v) and np.isnan(offl_v)) else 0.0
        diffs.append((col, d))
    max_col, max_d = max(diffs, key=lambda t: t[1])
    worst[ticker] = (max_col, max_d)
    flag = "OK " if max_d < 1e-6 else ("~  " if max_d < 1e-3 else "DIFF")
    soft_note = ""
    soft_vals = []
    for col in SOFT_COLS:
        live_v = float(X[col].iloc[0]) if col in X.columns else float("nan")
        offl_v = float(ev[col])
        soft_vals.append(f"{col}: live={live_v:+.4f} offline={offl_v:+.4f}")
    print(f"  {flag} {ticker:<6} strict-max-rel-diff {max_d:.2e} ({max_col}) | " + "; ".join(soft_vals))

bad = {t: v for t, v in worst.items() if v[1] >= 1e-3}
print(f"\nresult: {len(worst)} checked, {len(bad)} with meaningful drift")
if bad:
    for t, (c, d) in bad.items():
        print(f"  {t}: {c} rel-diff {d:.2e}")
