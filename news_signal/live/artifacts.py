import json
import pickle
from pathlib import Path

import pandas as pd
from xgboost import XGBClassifier, XGBRegressor

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = ROOT / "models"


def load_champion():
    model = XGBClassifier()
    model.load_model(MODELS_DIR / "champion_xgb_4class.json")
    return model


def load_severity_regressor():
    model = XGBRegressor()
    model.load_model(MODELS_DIR / "severity_regressor.json")
    return model


def load_calibration():
    with open(MODELS_DIR / "calibration.pkl", "rb") as f:
        blob = pickle.load(f)
    return blob["iso_maps"], blob["class_names"]


def load_thresholds():
    return json.loads((MODELS_DIR / "alert_thresholds.json").read_text(encoding="utf-8"))


def calibrate(raw_probs, iso_maps):
    import numpy as np

    cols = []
    for c in sorted(iso_maps.keys()):
        p = np.asarray(raw_probs[:, c], dtype=float)
        cols.append(iso_maps[c].predict(p))
    out = np.column_stack(cols)
    s = out.sum(axis=1, keepdims=True)
    s[s == 0] = 1.0
    return out / s
