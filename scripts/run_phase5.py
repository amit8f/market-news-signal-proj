import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scipy import stats
from sklearn.metrics import accuracy_score, f1_score
from xgboost import XGBClassifier, XGBRegressor

from news_signal.config import load_config, raw_bars_dir, calendar_path, processed_dir, outputs_dir
from news_signal.labels.forward_returns import build_sessions, filter_regular_minutes
from news_signal.labels.make_labels import apply_frozen_labels, fit_threshold_edges
from news_signal.models.features import build_feature_matrix, balanced_sample_weight
from news_signal.models.splitting import holdout_split, walk_forward_day_blocks
from news_signal.models.calibration import (
    apply_calibration,
    choose_thresholds,
    fit_per_class_isotonic,
    oof_probabilities,
    reliability_table,
)

CLASS_NAMES_4 = ["Sell", "Neutral", "Buy", "Strong Buy"]
MERGE_MAP = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3}
ACTIONABLE = {0: "short", 2: "long", 3: "long"}
PRIORITY = [3, 2, 0]


def load_best_params():
    hist = pd.read_csv(outputs_dir() / "optuna_tuning_history.csv")
    best = hist.loc[hist["value"].idxmax()]
    keys = [
        "n_estimators", "max_depth", "learning_rate", "subsample",
        "colsample_bytree", "min_child_weight", "reg_alpha", "reg_lambda",
    ]

    def get(k):
        col = f"params_{k}" if f"params_{k}" in hist.columns else k
        return int(best[col]) if k in ("n_estimators", "max_depth") else float(best[col])

    return {k: get(k) for k in keys}


def _minutes_loader(sessions):
    cache = {}

    def get(ticker):
        if ticker not in cache:
            df = pd.read_csv(raw_bars_dir() / f"{ticker}_1min.csv", index_col=0)
            df.index = pd.to_datetime(df.index, utc=True)
            cache[ticker] = filter_regular_minutes(df, sessions)
        return cache[ticker]

    return get


def simulate_trade(minutes, entry_ts, exit_ts, entry_price, exit_price, direction, stop_dist):
    idx = minutes.index
    i0 = int(idx.searchsorted(pd.Timestamp(entry_ts)))
    i1 = int(idx.searchsorted(pd.Timestamp(exit_ts)))
    if i0 >= len(idx) or i1 >= len(idx) or i1 < i0:
        return None
    if not np.isfinite(stop_dist) or stop_dist <= 0:
        stop_dist = np.inf
    long = direction == "long"
    stop = entry_price - stop_dist if long else entry_price + stop_dist
    exit_fill = None
    stopped = False
    for j in range(i0, i1 + 1):
        bar_open = float(minutes["open"].iloc[j])
        bar_low = float(minutes["low"].iloc[j])
        bar_high = float(minutes["high"].iloc[j])
        if long and bar_low <= stop:
            exit_fill = min(bar_open, stop)
            stopped = True
            break
        if (not long) and bar_high >= stop:
            exit_fill = max(bar_open, stop)
            stopped = True
            break
    if exit_fill is None:
        exit_fill = float(exit_price)
    return {"exit_fill": exit_fill, "stopped": stopped}


def trade_stats(trades, label):
    if not trades:
        return {"label": label, "n": 0}
    r = np.array([t["net_ret"] for t in trades])
    gross = np.array([t["gross_ret"] for t in trades])
    cum = np.cumsum(r)
    dd = float(np.max(np.maximum.accumulate(cum) - cum)) if len(cum) else 0.0
    longs = [t for t in trades if t["direction"] == "long"]
    shorts = [t for t in trades if t["direction"] == "short"]
    sev = [t for t in trades if t.get("severe")]
    non_sev = [t for t in trades if not t.get("severe")]

    def blk(ts_):
        rr = np.array([t["net_ret"] for t in ts_]) if ts_ else np.array([])
        return f"{len(rr)}({np.mean(rr):+.4%})" if len(rr) else "0"

    out = {
        "label": label,
        "n": len(trades),
        "win": float((r > 0).mean()),
        "mean": float(r.mean()),
        "median": float(np.median(r)),
        "sum": float(r.sum()),
        "tstat": float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 and r.std(ddof=1) > 0 else np.nan,
        "maxdd_sumunits": dd,
        "gross_mean": float(gross.mean()),
        "stopped": float(np.mean([t["stopped"] for t in trades])),
        "longs": blk(longs),
        "shorts": blk(shorts),
        "severe": blk(sev),
        "nonsevere": blk(non_sev),
        "excess_mean": float(np.nanmean([t.get("excess_gross", np.nan) for t in trades])),
        "excess_t": (
            lambda ex: float(np.mean(ex) / (np.std(ex, ddof=1) / np.sqrt(len(ex))))
            if len(ex) > 1 and np.std(ex, ddof=1) > 0 else np.nan
        )(np.array([t["excess_gross"] for t in trades if np.isfinite(t.get("excess_gross", np.nan))])),
    }
    return out


def stats_row(out):
    if out["n"] == 0:
        return f"{out['label']:<28} n=0"
    return (
        f"{out['label']:<28} n={out['n']:>4}  win={out['win']:.1%}  mean/trade={out['mean']:+.4%}  "
        f"sum={out['sum']:+.2%}  t={out['tstat']:+.2f}  excess_vs_SPY={out['excess_mean']:+.4%}(t={out['excess_t']:+.2f})  "
        f"stop%={out['stopped']:.0%}  L{out['longs']} S{out['shorts']} sev{out['severe']} non{out['nonsevere']}  gross_mean={out['gross_mean']:+.4%}"
    )


def main():
    cfg = load_config()
    mcfg = cfg["model"]
    cal_cfg = cfg["calibration"]
    bt_cfg = cfg["backtest"]
    slip = bt_cfg["slippage_bps_per_side"] / 1e4

    df_all = pd.read_parquet(processed_dir() / "milestone_events.parquet")
    df_all = df_all.sort_values("published_utc").reset_index(drop=True)
    pre_idx, _ = holdout_split(df_all["published_utc"], mcfg["holdout_start"], mcfg["embargo_days"])
    edges = fit_threshold_edges(
        (df_all["fwd_ret_2h"] / df_all["sigma_2h"]).iloc[pre_idx],
        quantiles=tuple(cfg["labels"]["quantiles"]),
    )
    print(f"[labels] frozen edges recomputed identically: {np.round(edges, 4).tolist()}")
    SEVERE_SELL, SEVERE_BUY = float(edges[0]), float(edges[3])

    df = apply_frozen_labels(df_all, edges)
    df["label"] = df["label"].map(MERGE_MAP).astype(int)
    X, meta = build_feature_matrix(df)
    y = df["label"].values.astype(int)
    dates = df["published_utc"]

    tr_idx, te_idx = holdout_split(dates, mcfg["holdout_start"], mcfg["embargo_days"])
    X_tr, y_tr = X.iloc[tr_idx], y[tr_idx]
    X_te, y_te = X.iloc[te_idx], y[te_idx]

    best_params = load_best_params()
    print(f"[model] best params from tuning history: {best_params}")

    def make_clf():
        return XGBClassifier(
            objective="multi:softprob", num_class=4, tree_method="hist",
            eval_metric="mlogloss", random_state=mcfg["seed"], n_jobs=-1, **best_params,
        )

    champion = make_clf()
    champion.fit(X_tr, y_tr, sample_weight=balanced_sample_weight(y_tr))
    champion.save_model(ROOT / "models" / "champion_xgb_4class.json")

    cv_splits = walk_forward_day_blocks(
        dates.iloc[tr_idx], n_folds=mcfg["cv_folds"], embargo_days=mcfg["embargo_days"],
        initial_train_days=mcfg["initial_train_days"],
    )
    oof = oof_probabilities(make_clf, X_tr, y_tr, cv_splits, num_class=4)
    iso = fit_per_class_isotonic(oof, y_tr, 4)
    cal_oof = apply_calibration(oof, iso)

    floor_by_class = {}
    name_to_idx = {"Sell": 0, "Neutral": 1, "Buy": 2, "Strong Buy": 3}
    for cname, floor in cal_cfg["precision_floor_by_class"].items():
        floor_by_class[name_to_idx[cname]] = float(floor)
    thresholds, curves = choose_thresholds(
        cal_oof, y_tr, floor_by_class, cal_cfg["min_fire_rate"], max_fire_rate=cal_cfg["max_fire_rate"]
    )
    print("\n[CALIBRATION] thresholds chosen on train-pool OOF isotonic-calibrated probs:")
    for c, t in thresholds.items():
        print(f"   {CLASS_NAMES_4[c]:<11} thr={t['threshold']}  oof_prec={t['oof_precision']:.3f}  oof_rec={t['oof_recall']:.3f}  oof_fire={t['oof_fire_rate']:.1%}  {t.get('note','')}")

    raw_te = champion.predict_proba(X_te)
    cal_te = apply_calibration(raw_te, iso)
    pred_raw = raw_te.argmax(axis=1)

    L = []
    a = L.append
    a("=" * 78)
    a("PRE-PHASE-5 ANSWERS")
    a("=" * 78)
    a("")
    a("(1) PER-CLASS CALIBRATION (isotonic fit on train-pool OOF only)")
    for c in [0, 1, 2, 3]:
        rt = reliability_table(cal_oof[:, [c]], (y_tr == c).astype(int), 1, n_bins=5)
        line = " | ".join(f"p~{r['mean_pred']:.2f}->{r['emp_freq']:.2f}" for r in rt)
        a(f"   {CLASS_NAMES_4[c]:<11} OOF calibrated: {line}")
    a("   ALERT THRESHOLDS (frozen for live use):")
    for c, t in thresholds.items():
        if t["threshold"] is None:
            a(f"   {CLASS_NAMES_4[c]:<11} NO USABLE THRESHOLD")
        else:
            a(f"   {CLASS_NAMES_4[c]:<11} fire when calibrated P >= {t['threshold']:.2f}  (OOF precision {t['oof_precision']:.1%})")

    for c in [0, 2, 3]:
        rt = reliability_table(cal_te[:, [c]], (y_te == c).astype(int), 1, n_bins=5)
        line = " | ".join(f"{r['mean_pred']:.2f}->{r['emp_freq']:.2f}" for r in rt)
        a(f"   HOLDOUT check {CLASS_NAMES_4[c]:<11}: {line}")

    inv_buy = int(((y_te == 2) & (pred_raw == 0)).sum())
    inv_sb = int(((y_te == 3) & (pred_raw == 0)).sum())
    n_buy = int((y_te == 2).sum())
    n_sb = int((y_te == 3).sum())
    a("")
    a("(2) BUY-SIDE WRONG-DIRECTION under current 4-class model (holdout, raw argmax)")
    a(f"   actual Buy      -> predicted Sell: {inv_buy}/{n_buy} ({inv_buy / max(n_buy, 1):.1%})")
    a(f"   actual StrongBuy-> predicted Sell: {inv_sb}/{n_sb} ({inv_sb / max(n_sb, 1):.1%})")

    reg = XGBRegressor(
        objective="reg:quantileerror", quantile_alpha=0.5, tree_method="hist",
        n_estimators=int(best_params["n_estimators"]), max_depth=int(best_params["max_depth"]),
        learning_rate=float(best_params["learning_rate"]), subsample=float(best_params["subsample"]),
        colsample_bytree=float(best_params["colsample_bytree"]),
        min_child_weight=float(best_params["min_child_weight"]),
        reg_alpha=float(best_params["reg_alpha"]), reg_lambda=float(best_params["reg_lambda"]),
        random_state=mcfg["seed"], n_jobs=-1,
    )
    score_pool = ((df["fwd_ret_2h"] / df["sigma_2h"]).values)[tr_idx]
    reg.fit(X_tr, score_pool)
    pred_score_te = reg.predict(X_te)
    act_score_te = (df["fwd_ret_2h"] / df["sigma_2h"]).values[te_idx]
    sp = stats.spearmanr(pred_score_te, act_score_te)
    mae = float(np.mean(np.abs(pred_score_te - act_score_te)))
    sev_sell_mask = pred_score_te <= SEVERE_SELL
    sev_buy_mask = pred_score_te >= SEVERE_BUY
    sev_sell_hit = float((act_score_te[sev_sell_mask] <= SEVERE_SELL).mean()) if sev_sell_mask.any() else np.nan
    sev_buy_hit = float((act_score_te[sev_buy_mask] >= SEVERE_BUY).mean()) if sev_buy_mask.any() else np.nan
    a("")
    a("(3) SEVERITY DERIVATION")
    a("   severity = median-quantile regressor's predicted vol-normalized 2h score")
    a(f"   severe-Sell: pred_score <= {SEVERE_SELL:+.4f} (old StrongSell edge) | severe-Buy: >= {SEVERE_BUY:+.4f}")
    a("   BOTH edges are the SAME frozen train-pool-fit thresholds - nothing new fit")
    a(f"   regressor trained on train pool only | holdout Spearman={sp.statistic:+.3f} MAE={mae:.3f}")
    a(f"   severe-Sell flagged {int(sev_sell_mask.sum())} events, realized-severe rate {sev_sell_hit:.1%}")
    a(f"   severe-Buy  flagged {int(sev_buy_mask.sum())} events, realized-severe rate {sev_buy_hit:.1%}")

    fired = []
    for i in range(len(y_te)):
        crossing = [c for c in ACTIONABLE if cal_te[i, c] >= thresholds[c]["threshold"]]
        if not crossing:
            continue
        cls = min(crossing, key=lambda c: PRIORITY.index(c))
        fired.append({
            "row": te_idx[i], "cls": cls, "prob": float(cal_te[i, cls]),
            "direction": ACTIONABLE[cls], "severe": bool(
                (pred_score_te[i] <= SEVERE_SELL and cls == 0) or (pred_score_te[i] >= SEVERE_BUY and cls in (2, 3))
            ),
            "pred_score": float(pred_score_te[i]),
        })
    print(f"\n[alerts] champion fires on {len(fired)}/{len(te_idx)} holdout events ({len(fired) / len(te_idx):.1%})")
    from collections import Counter
    print("[alerts] by class:", dict(Counter(CLASS_NAMES_4[f['cls']] for f in fired)))

    sessions = build_sessions(calendar_path())
    loader = _minutes_loader(sessions)
    atr = df["atr14_1h_pct"].values

    def run_backtest(alert_rows, label, seed=None):
        trades = []
        rng = np.random.default_rng(seed) if seed is not None else None
        for ar in alert_rows:
            row = df.iloc[ar["row"]] if isinstance(ar, dict) and "row" in ar else ar
            if isinstance(ar, dict) and "random_direction" in ar:
                direction = ar["random_direction"]
                cls_name = "Random"
            elif isinstance(ar, dict) and "sent_direction" in ar:
                direction = ar["sent_direction"]
                cls_name = "SentRule"
            else:
                direction = ar["direction"]
                cls_name = CLASS_NAMES_4[ar["cls"]]
            minutes = loader(row["ticker"])
            entry_price = float(row["entry_price"])
            stop_dist = float(row["atr14_1h_pct"]) * entry_price * bt_cfg["stop_atr_multiple"]
            sim = simulate_trade(minutes, row["entry_ts"], row["exit_ts"], entry_price, float(row["exit_price"]), direction, stop_dist)
            if sim is None:
                continue
            e, x = entry_price, sim["exit_fill"]
            spy_m = loader(cfg["benchmark"])
            s_i0 = int(spy_m.index.searchsorted(pd.Timestamp(row["entry_ts"])))
            s_i1 = int(spy_m.index.searchsorted(pd.Timestamp(row["exit_ts"])))
            if 0 <= s_i0 < len(spy_m) and 0 <= s_i1 < len(spy_m):
                spy_gross = float(spy_m["close"].iloc[s_i1]) / float(spy_m["open"].iloc[s_i0]) - 1.0
            else:
                spy_gross = np.nan
            dir_sign = 1.0 if direction == "long" else -1.0
            if direction == "long":
                gross = x / e - 1.0
                net = (x * (1 - slip)) / (e * (1 + slip)) - 1.0
            else:
                gross = 1.0 - x / e
                net = 1.0 - (x * (1 + slip)) / (e * (1 - slip))
            trades.append({
                "event_id": row["event_id"], "ticker": row["ticker"], "signal": cls_name,
                "direction": direction, "severe": ar.get("severe", False) if isinstance(ar, dict) else False,
                "entry_ts": row["entry_ts"], "exit_ts": row["exit_ts"],
                "entry_fill": e, "exit_fill": x, "stopped": sim["stopped"],
                "gross_ret": gross, "net_ret": net,
                "spy_gross": spy_gross, "excess_gross": gross - dir_sign * spy_gross,
            })
        tdf = pd.DataFrame(trades)
        safe_label = label.replace(" ", "_").replace("/", "-").lower()
        tdf.to_csv(outputs_dir() / f"trades_{safe_label}.csv", index=False)
        return trade_stats(trades, label)

    champ_stats = run_backtest(fired, "champion alerts (net)")

    rng = np.random.default_rng(mcfg["seed"])
    rand_rows = []
    sample_rows = rng.choice(te_idx, size=len(fired), replace=False)
    for r0 in sample_rows:
        rand_rows.append({"random_direction": "long" if rng.random() < 0.5 else "short", "row": int(r0)})
    random_stats = run_backtest(rand_rows, "freq-matched random (net)")

    sent_vals = df["sent_score"].values
    sent_rows = []
    for r0 in te_idx:
        sv = sent_vals[r0]
        if sv > 0.5:
            sent_rows.append({"sent_direction": "long", "row": int(r0)})
        elif sv < -0.5:
            sent_rows.append({"sent_direction": "short", "row": int(r0)})
    sent_stats = run_backtest(sent_rows, "naive sentiment rule (net)")

    a("")
    a("=" * 78)
    a(f"PHASE 5 BACKTEST - HOLDOUT ONLY ({mcfg['holdout_start']} onward), 120min horizon, ATR(1x) stops, {bt_cfg['slippage_bps_per_side']}bps/side")
    a("=" * 78)
    for st in [champ_stats, random_stats, sent_stats]:
        a(stats_row(st))
    a("")
    a("notes: single-window holdout (not walk-forward across regimes);")
    a("       IEX tape noise means fills are optimistic vs consolidated market;")
    a("       severity split shown as sev/non-sev mean net per trade;")
    a("=" * 78)

    report = "\n".join(L)
    (outputs_dir() / "backtest_report.txt").write_text(report, encoding="utf-8")
    print(report)

    import pickle

    models_dir = ROOT / "models"
    models_dir.mkdir(exist_ok=True)
    with open(models_dir / "calibration.pkl", "wb") as f:
        pickle.dump({"iso_maps": iso, "class_names": CLASS_NAMES_4}, f)
    thresholds_out = {
        CLASS_NAMES_4[c]: (thresholds[c]["threshold"] if thresholds[c]["threshold"] is not None else None)
        for c in thresholds
    }
    import json

    (models_dir / "alert_thresholds.json").write_text(
        json.dumps({"calibrated_thresholds": thresholds_out, "suppressed_classes": ["Sell"], "severity": "informational_only"}, indent=2),
        encoding="utf-8",
    )
    reg.save_model(models_dir / "severity_regressor.json")
    print("[persist] calibration.pkl, alert_thresholds.json, severity_regressor.json saved for live use")


if __name__ == "__main__":
    main()
