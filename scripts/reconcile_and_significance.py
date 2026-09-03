import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scipy import stats

from news_signal.config import load_config, processed_dir
from news_signal.labels.make_labels import apply_frozen_labels, fit_threshold_edges
from news_signal.models.features import build_feature_matrix, balanced_sample_weight
from news_signal.models.splitting import holdout_split
from xgboost import XGBClassifier

CLASS_NAMES_4 = ["Sell", "Neutral", "Buy", "Strong Buy"]
MERGE_MAP = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3}

cfg = load_config()
mcfg = cfg["model"]
THR = {"Sell": 0.44, "Neutral": None, "Buy": 0.29, "Strong Buy": 0.21}
IDX = {"Sell": 0, "Neutral": 1, "Buy": 2, "Strong Buy": 3}

df_all = pd.read_parquet(processed_dir() / "milestone_events.parquet")
df_all = df_all.sort_values("published_utc").reset_index(drop=True)
pre_idx, _ = holdout_split(df_all["published_utc"], mcfg["holdout_start"], mcfg["embargo_days"])
edges = fit_threshold_edges((df_all["fwd_ret_2h"] / df_all["sigma_2h"]).iloc[pre_idx], quantiles=tuple(cfg["labels"]["quantiles"]))
df = apply_frozen_labels(df_all, edges)
df["label"] = df["label"].map(MERGE_MAP).astype(int)
X, meta = build_feature_matrix(df)
y = df["label"].values.astype(int)
dates = df["published_utc"]
tr_idx, te_idx = holdout_split(dates, mcfg["holdout_start"], mcfg["embargo_days"])

hist = pd.read_csv(ROOT / "outputs" / "optuna_tuning_history.csv")
best_row = hist.loc[hist["value"].idxmax()]
params = {}
for k in ["n_estimators", "max_depth", "learning_rate", "subsample", "colsample_bytree", "min_child_weight", "reg_alpha", "reg_lambda"]:
    col = f"params_{k}" if f"params_{k}" in hist.columns else k
    params[k] = int(best_row[col]) if k in ("n_estimators", "max_depth") else float(best_row[col])

clf = XGBClassifier(objective="multi:softprob", num_class=4, tree_method="hist", eval_metric="mlogloss",
                    random_state=mcfg["seed"], n_jobs=-1, **params)
clf.fit(X.iloc[tr_idx], y[tr_idx], sample_weight=balanced_sample_weight(y[tr_idx]))

from news_signal.models.splitting import walk_forward_day_blocks
from news_signal.models.calibration import (
    apply_calibration, fit_per_class_isotonic, oof_probabilities,
)

cv_splits = walk_forward_day_blocks(dates.iloc[tr_idx], n_folds=mcfg["cv_folds"],
                                    embargo_days=mcfg["embargo_days"],
                                    initial_train_days=mcfg["initial_train_days"])


def make_clf():
    return XGBClassifier(objective="multi:softprob", num_class=4, tree_method="hist",
                         eval_metric="mlogloss", random_state=mcfg["seed"], n_jobs=-1, **params)


oof = oof_probabilities(make_clf, X.iloc[tr_idx], y[tr_idx], cv_splits, num_class=4)
iso = fit_per_class_isotonic(oof, y[tr_idx], 4)
proba = apply_calibration(clf.predict_proba(X.iloc[te_idx]), iso)

te = df.iloc[te_idx].reset_index(drop=True)
te["pred_cls"] = proba.argmax(axis=1)
PRIORITY = [3, 2, 0]
ACTIONABLE = {0: "short", 2: "long", 3: "long"}

print("=" * 78)
print("RECONCILIATION: label-precision vs trade-PnL for fired LONG alerts (holdout)")
print("uses the EXACT backtest firing rule: calibrated probs + thresholds + precedence")
print("=" * 78)

fired_rows = []
for i in range(len(te)):
    crossing = [c for c in ACTIONABLE if proba[i, c] >= THR[CLASS_NAMES_4[c]]]
    if not crossing:
        continue
    cls = min(crossing, key=lambda c: PRIORITY.index(c))
    fired_rows.append((i, cls))
fired_df = te.iloc[[i for i, _ in fired_rows]].copy()
fired_df["alert_cls"] = [c for _, c in fired_rows]

for cls_name in ["Buy", "Strong Buy"]:
    c = IDX[cls_name]
    fired = fired_df[fired_df["alert_cls"] == c]
    print(f"\n--- fired {cls_name} alerts (cal P>={THR[cls_name]}, after precedence): n={len(fired)} ---")
    out = []
    for i2, name in enumerate(CLASS_NAMES_4):
        n = int((fired["label"] == i2).sum())
        mr = fired.loc[fired["label"] == i2, "fwd_ret_2h"].mean() if n else np.nan
        out.append(f"{name:<11} n={n:>4} ({n/max(len(fired),1):.0%})  mean_fwd={mr:+.4%}")
    print("\n".join(out))
    wr = (fired["fwd_ret_2h"] > 0).mean()
    avg = fired["fwd_ret_2h"].mean()
    exact = (fired["label"] == c).mean()
    print(f"exact-label precision: {exact:.1%} | win rate (raw ret>0): {wr:.1%} | mean raw fwd ret: {avg:+.4%}")
    print(f"actual-Sell share among fired {cls_name}: {(fired['label'] == 0).mean():.1%}")

sb_mask = fired_df["alert_cls"] == 3
print(f"\nfired StrongBuy realized exact-label precision on holdout: {(fired_df.loc[sb_mask,'label']==3).mean():.1%} (OOF expectation was 34.9%)")

q = np.quantile(proba[:, IDX["Strong Buy"]], [0.5, 0.9, 0.95, 0.99, 1.0])
n_sb_fire = int((proba[:, IDX["Strong Buy"]] >= THR["Strong Buy"]).sum())
print(f"holdout calibrated SB prob quantiles p50/p90/p95/p99/max: {np.round(q, 3).tolist()}; n>=0.21 anywhere: {n_sb_fire}")
print("(reliability bins shown earlier were 5 equal-count bins over ALL events -> top-bin MEAN 0.16;")
print(" the firing cut 0.21 sits in the extreme tail - illustrative bin, not the threshold)")

print()
print("=" * 78)
print("SIGNIFICANCE REDO - day-clustered + block bootstrap (cluster = entry day)")
print("=" * 78)

trades = pd.read_csv(ROOT / "outputs" / "trades_champion_alerts_(net).csv")
trades["entry_day"] = pd.to_datetime(trades["entry_ts"]).dt.date


def cluster_stats(tr, col):
    daily = tr.groupby("entry_day")[col].agg(["sum", "count"])
    n_per_day = daily["count"]
    day_mean = tr.groupby("entry_day")[col].mean()
    nb = len(day_mean)
    mu = day_mean.mean()
    se = day_mean.std(ddof=1) / np.sqrt(nb)
    t = mu / se if se > 0 else np.nan
    rng = np.random.default_rng(42)
    boots = []
    arr = day_mean.values
    for _ in range(2000):
        sample = rng.choice(arr, size=nb, replace=True)
        boots.append(np.average(sample, weights=daily.loc[daily.index.isin([])] if False else None) if False else sample.mean())
    boots = np.array(boots)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    p_one_sided = float((boots <= 0).mean())
    exp_trades = int(n_per_day.mean() * nb)
    return {
        "per_trade_mean": tr[col].mean(),
        "day_clustered_mean": mu,
        "t_clustered": t,
        "n_days": nb,
        "boot_ci_lo": lo,
        "boot_ci_hi": hi,
        "boot_p_gt0_vs_le0": p_one_sided,
        "avg_trades_per_day": float(n_per_day.mean()),
        "expected_total": exp_trades,
    }


def show(label, tr, col):
    s = cluster_stats(tr, col)
    print(
        f"{label:<34} per-trade {s['per_trade_mean']:+.4%} | day-clustered mean {s['day_clustered_mean']:+.4%} "
        f"(t={s['t_clustered']:+.2f}, {s['n_days']} days, ~{s['avg_trades_per_day']:.1f} trades/day) | "
        f"bootstrap 95% CI [{s['boot_ci_lo']:+.4%}, {s['boot_ci_hi']:+.4%}] | P(mean<=0)={s['boot_p_gt0_vs_le0']:.3f}"
    )


show("champion NET", trades, "net_ret")
show("champion excess vs SPY (gross)", trades, "excess_gross")
longs = trades[trades["direction"] == "long"]
shorts = trades[trades["direction"] == "short"]
show("champion NET - longs only", longs, "net_ret")
if len(shorts):
    show("champion NET - shorts only", shorts, "net_ret")
try:
    rnd = pd.read_csv(ROOT / "outputs" / "trades_freq-matched_random_(net).csv")
    show("random baseline NET", rnd, "net_ret")
except Exception:
    pass
