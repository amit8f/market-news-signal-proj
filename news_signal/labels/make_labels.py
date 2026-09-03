import numpy as np
import pandas as pd

CLASS_NAMES = ["Strong Sell", "Sell", "Neutral", "Buy", "Strong Buy"]


def fit_threshold_edges(train_scores, quantiles=(0.10, 0.35, 0.65, 0.90)):
    scores = pd.Series(train_scores).dropna()
    return np.quantile(scores.values, quantiles)


def apply_frozen_labels(events, edges):
    valid = events.dropna(subset=["fwd_ret_2h", "sigma_2h"]).copy()
    valid = valid[valid["sigma_2h"] > 0]
    score = valid["fwd_ret_2h"] / valid["sigma_2h"]
    labels = np.digitize(score.values, edges)
    valid["score_vol_norm"] = score.values
    valid["label"] = labels
    valid["label_name"] = [CLASS_NAMES[i] for i in labels]
    return valid.reset_index(drop=True)
