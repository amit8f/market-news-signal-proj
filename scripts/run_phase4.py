import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support

from news_signal.config import load_config, outputs_dir, processed_dir
from news_signal.models.features import build_feature_matrix, balanced_sample_weight
from news_signal.models.splitting import holdout_split, walk_forward_day_blocks, weekly_blocks
from news_signal.models.baselines import always_neutral, frequency_random, sentiment_rule
from news_signal.models.tune import make_model, run_optuna_search
from news_signal.labels.make_labels import apply_frozen_labels, fit_threshold_edges

CLASS_NAMES_5 = ["Strong Sell", "Sell", "Neutral", "Buy", "Strong Buy"]
CLASS_NAMES_4 = ["Sell", "Neutral", "Buy", "Strong Buy"]
MERGE_MAP = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3}


def ordinal_mae(y_true, y_pred):
    return float(np.mean(np.abs(np.asarray(y_true) - np.asarray(y_pred))))


def classification_block(y_true, y_pred, class_names):
    k = len(class_names)
    acc = accuracy_score(y_true, y_pred)
    mf1 = f1_score(y_true, y_pred, average="macro")
    p, r, f, sup = precision_recall_fscore_support(
        y_true, y_pred, labels=list(range(k)), zero_division=0
    )
    return {
        "accuracy": acc,
        "macro_f1": mf1,
        "ordinal_mae": ordinal_mae(y_true, y_pred),
        "per_class": pd.DataFrame(
            {"class": class_names, "precision": p, "recall": r, "f1": f, "support": sup}
        ).set_index("class"),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--classes", choices=["5", "4"], default="5")
    args = parser.parse_args()
    n_classes = int(args.classes)
    class_names = CLASS_NAMES_5 if n_classes == 5 else CLASS_NAMES_4
    neutral_idx = 2 if n_classes == 5 else 1

    cfg = load_config()
    mcfg = cfg["model"]
    quantiles = tuple(cfg["labels"]["quantiles"])

    df_all = pd.read_parquet(processed_dir() / "milestone_events.parquet")
    df_all = df_all.sort_values("published_utc").reset_index(drop=True)

    pre_idx, _ = holdout_split(df_all["published_utc"], mcfg["holdout_start"], mcfg["embargo_days"])
    pre_scores = (df_all["fwd_ret_2h"] / df_all["sigma_2h"]).iloc[pre_idx]
    edges = fit_threshold_edges(pre_scores, quantiles=quantiles)
    print(f"[labels] FROZEN edges from train pool only ({len(pre_idx)} events): {np.round(edges, 4)}")

    df = apply_frozen_labels(df_all, edges)
    n_dropped_unlabeled = len(df_all) - len(df)
    print(f"[labels] labeled {len(df)} | dropped unlabeled (no valid trailing sigma): {n_dropped_unlabeled}")
    if n_classes == 4:
        df["label"] = df["label"].map(MERGE_MAP).astype(int)
        print("[labels] 4-class scheme: Strong Sell merged into Sell; strength handled by regressor later")

    X, meta = build_feature_matrix(df)
    y = df["label"].values.astype(int)
    dates = df["published_utc"]

    tr_idx, te_idx = holdout_split(dates, mcfg["holdout_start"], mcfg["embargo_days"])
    X_tr_full, y_tr_full = X.iloc[tr_idx], y[tr_idx]
    X_te, y_te = X.iloc[te_idx], y[te_idx]
    print(f"[data] train pool {len(tr_idx)} | holdout {len(te_idx)} | features {X.shape[1]}")

    cv_splits = walk_forward_day_blocks(
        dates.iloc[tr_idx], n_folds=mcfg["cv_folds"], embargo_days=mcfg["embargo_days"],
        initial_train_days=mcfg["initial_train_days"],
    )
    print(f"[cv] {len(cv_splits)} purged walk-forward folds")

    study = run_optuna_search(
        X_tr_full, y_tr_full, cv_splits, n_trials=mcfg["n_optuna_trials"], seed=mcfg["seed"],
        depth_bounds=(mcfg["max_depth_min"], mcfg["max_depth_max"]), num_class=n_classes,
    )
    best_params = study.best_params
    print(f"[optuna] best macro-F1 (cv): {study.best_value:.4f}")
    print(f"[optuna] max_depth searched in [{mcfg['max_depth_min']}, {mcfg['max_depth_max']}] -> best: {best_params['max_depth']}")
    study.trials_dataframe().to_csv(outputs_dir() / "optuna_tuning_history.csv", index=False)

    champion = make_model(best_params, num_class=n_classes)
    w_full = balanced_sample_weight(y_tr_full)
    champion.fit(X_tr_full, y_tr_full, sample_weight=w_full)
    counts = np.bincount(y_tr_full, minlength=n_classes)
    wpc = (counts.sum() / (n_classes * np.maximum(counts, 1))).round(3)
    print("[weights] class weights recalculated on post-filter train pool:")
    for name, cnt, w in zip(class_names, counts, wpc):
        print(f"   {name:<12} n={cnt:>6}  weight={w}")
    models_dir = ROOT / "models"
    models_dir.mkdir(exist_ok=True)
    champion.save_model(models_dir / ("champion_xgb.json" if n_classes == 5 else "champion_xgb_4class.json"))

    pred = champion.predict(X_te)
    res = classification_block(y_te, pred, class_names)
    cm = pd.crosstab(pd.Series(y_te, name="actual"), pd.Series(pred, name="predicted"))

    base_neu = classification_block(y_te, always_neutral(y_te, neutral_idx), class_names)
    base_rand = classification_block(y_te, frequency_random(y_te, y_tr_full, mcfg["seed"], num_class=n_classes), class_names)
    sent_te = df["sent_score"].values[te_idx]
    base_sent = classification_block(y_te, sentiment_rule(sent_te, neutral_idx=neutral_idx), class_names)

    weeks = weekly_blocks(dates, mcfg["embargo_days"])
    rows = []
    for monday, wtr, wte in weeks:
        if monday < pd.Timestamp(mcfg["holdout_start"], tz="UTC") - pd.Timedelta(days=14):
            continue
        wm = make_model(best_params)
        wm.fit(X.iloc[wtr], y[wtr], sample_weight=balanced_sample_weight(y[wtr]))
        wp = wm.predict(X.iloc[wte])
        rows.append({
            "week_start": str(monday.date()),
            "n_test": len(wte),
            "train_n": len(wtr),
            "accuracy": accuracy_score(y[wte], wp),
            "macro_f1": f1_score(y[wte], wp, average="macro"),
        })
    weekly = pd.DataFrame(rows)
    weekly.to_csv(outputs_dir() / "weekly_stability.csv", index=False)

    proba = champion.predict_proba(X_te)
    conf = proba.max(axis=1)
    bins = pd.qcut(pd.Series(conf).rank(method="first"), 10, labels=False)
    cal = (
        pd.DataFrame({"conf": conf, "ok": (pred == y_te).astype(float), "bin": bins})
        .groupby("bin")
        .agg(n=("ok", "size"), mean_conf=("conf", "mean"), empirical_acc=("ok", "mean"))
    )

    shap_ok = False
    try:
        import shap

        rng = np.random.default_rng(mcfg["seed"])
        samp = rng.choice(len(X_te), min(3000, len(X_te)), replace=False)
        explainer = shap.TreeExplainer(champion)
        sv = explainer.shap_values(X_te.iloc[samp])
        arr = np.stack(sv, axis=-1) if isinstance(sv, list) else sv
        imp = np.abs(arr).mean(axis=(0, 2)) if arr.ndim == 3 else np.abs(arr).mean(axis=0)
        shap_imp = pd.Series(imp, index=X.columns).sort_values(ascending=False)
        shap_imp.to_csv(outputs_dir() / "shap_importance.csv", header=["mean_abs_shap"])
        top = shap_imp.head(20)[::-1]
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(8, 6))
            ax.barh(top.index, top.values)
            ax.set_title("Mean |SHAP| - top 20 features (holdout sample)")
            fig.tight_layout()
            fig.savefig(outputs_dir() / "shap_importance.png", dpi=150)
        except Exception as e:
            print(f"[shap] plot skipped: {e}")
        shap_ok = True
    except Exception as e:
        print(f"[shap] unavailable ({e}); using gain importance fallback")
        gain = pd.Series(champion.feature_importances_, index=X.columns).sort_values(ascending=False)
        gain.to_csv(outputs_dir() / "shap_importance.csv", header=["gain_importance"])

    L = []
    a = L.append
    scheme = "5-class" if n_classes == 5 else "4-class (Strong Sell merged into Sell)"
    a("=" * 72)
    a(f"PHASE 4 - MODEL REPORT v3 [{scheme}] depth-capped, trailing sigma, frozen labels")
    a("=" * 72)
    a(f"events with features: {len(df)} | features: {X.shape[1]} | unlabeled dropped: {n_dropped_unlabeled}")
    tier_dist = df["relevance_tier"].value_counts().sort_index()
    a("relevance tiers (modeling set): " + ", ".join(f"t{t}={n}" for t, n in tier_dist.items()))
    a("")
    a("-- FROZEN label thresholds --")
    a(f"  quantiles {quantiles} fit on train pool ONLY -> score edges: {np.round(edges, 4).tolist()}")
    med_sigma_train = float(df["sigma_2h"].iloc[tr_idx].median())
    pct_bounds = ["-inf"] + [f"{e * med_sigma_train:+.3%}" for e in edges]
    names = list(class_names)
    lo = None
    first_i_offset = 0 if n_classes == 5 else 1
    for i, name in enumerate(names):
        edge_i = i + first_i_offset
        hi = float(edges[edge_i]) if edge_i < len(edges) else None
        a(f"  {name:<12} [{pct_bounds[i] if n_classes == 5 else ('-inf' if i == 0 else pct_bounds[i])}, {pct_bounds[i+1] if (n_classes == 5 and i < 4) else (pct_bounds[min(i + 1, 4)] if n_classes == 4 and i < 3 else '+inf')})")
        lo = hi
    dist_tr = pd.Series(y_tr_full).value_counts(normalize=True).sort_index()
    dist_te = pd.Series(y_te).value_counts(normalize=True).sort_index()
    a("  class shares  train vs holdout:")
    for i, name in enumerate(names):
        a(f"    {name:<12} {dist_tr.get(i, 0):.1%} vs {dist_te.get(i, 0):.1%}")
    a("")
    a(f"holdout: >= {mcfg['holdout_start']} (n={len(te_idx)}) | embargo {mcfg['embargo_days']}d | sigma strictly trailing per event")
    a(f"cv: {len(cv_splits)} expanding folds inside train pool only | optuna trials: {mcfg['n_optuna_trials']}")
    a("")
    a("-- best hyperparameters --")
    for k, v in best_params.items():
        a(f"  {k}: {v}")
    a(f"  cv macro-F1 at best: {study.best_value:.4f}")
    a("")
    a("-- holdout results --")
    hdr = f"{'model':<22}{'acc':>7}{'macroF1':>9}{'ordMAE':>8}"
    a(hdr)
    for name, blk in [
        ("champion xgb", res),
        ("baseline: all Neutral", base_neu),
        ("baseline: freq-random", base_rand),
        ("baseline: sentiment rule", base_sent),
    ]:
        a(f"{name:<22}{blk['accuracy']:>7.3f}{blk['macro_f1']:>9.3f}{blk['ordinal_mae']:>8.3f}")
    a("")
    a("-- champion per-class (holdout) --")
    a(res["per_class"].round(3).to_string())
    a("")
    a("-- confusion matrix (rows=actual, cols=predicted) --")
    a(cm.to_string())
    if 0 in cm.index:
        row = cm.loc[0]
        total_ss = int(row.sum())
        wd = int(row.get(3, 0) + row.get(4, 0))
        a(f"  >> Strong-Sell direction error: {wd}/{total_ss} ({wd / max(total_ss, 1):.1%}) predicted Buy/Strong Buy")
    a("")
    a("-- weekly stability (retrained each week, fixed params) --")
    a(weekly.round(3).to_string(index=False))
    a("")
    a("-- calibration by predicted-confidence decile --")
    a(cal.round(3).to_string())
    a("")
    a("-- feature importance --")
    if shap_ok:
        a(shap_imp.head(20).round(5).to_string())
    else:
        a(gain.head(20).round(5).to_string())
    a("")
    a("-- leakage guards active --")
    a("  * sigma_2h strictly trailing per event (windows completed before publish)")
    a("  * label edges fit once on train pool, frozen for holdout/live")
    a("  * purged walk-forward CV with embargo; no shuffle anywhere")
    a("  * hourly indicators last COMPLETED bar; regime uses prior-day closes")
    a("  * relevance filter applied before event construction")
    a("-- residual caveats --")
    a("  * IEX-only tape; FinBERT entity noise reduced but not eliminated")
    a("  * class balance guaranteed on train pool only; holdout may drift")
    a("=" * 72)
    report = "\n".join(L)
    (outputs_dir() / "model_report.txt").write_text(report, encoding="utf-8")
    cm.to_csv(outputs_dir() / "confusion_matrix_holdout.csv")
    print(report)


if __name__ == "__main__":
    main()
