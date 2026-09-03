import hashlib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data" / "processed" / "sentiment_cache.csv"

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline

        _pipeline = pipeline("text-classification", model="ProsusAI/finbert", top_k=None, truncation=True)
    return _pipeline


def _load_cache(cache_path):
    lookup = {}
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            next(f, None)
            for line in f:
                parts = line.strip().split(",")
                if len(parts) != 5:
                    continue
                try:
                    lookup[parts[0]] = tuple(float(x) for x in parts[1:])
                except ValueError:
                    continue
    return lookup


def _append_cache_rows(cache_path, rows):
    is_new = not cache_path.exists()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "a", encoding="utf-8") as f:
        if is_new:
            f.write("text_hash,p_pos,p_neg,p_neu,sent_score\n")
        for row in rows:
            f.write(f"{row[0]},{row[1]:.6f},{row[2]:.6f},{row[3]:.6f},{row[4]:.6f}\n")


def score_with_cache(texts, cache_path=None, batch_size=32):
    cache_path = Path(cache_path) if cache_path else CACHE_PATH
    hashes = [hashlib.md5(str(t).encode("utf-8")).hexdigest() for t in texts]
    unique = {}
    for h, t in zip(hashes, texts):
        if h not in unique:
            unique[h] = str(t)[:512]
    lookup = _load_cache(cache_path)
    missing_hashes = [h for h in unique if h not in lookup]
    print(
        f"[finbert] input={len(texts)} unique={len(unique)} cached={len(unique) - len(missing_hashes)} to_score={len(missing_hashes)}"
    )
    if missing_hashes:
        pipe = _get_pipeline()
        total = len(missing_hashes)
        done = 0
        for i in range(0, total, batch_size):
            chunk_hashes = missing_hashes[i : i + batch_size]
            chunk_texts = [unique[h] for h in chunk_hashes]
            results = pipe(chunk_texts)
            rows = []
            for h, res in zip(chunk_hashes, results):
                probs = {r["label"].lower(): float(r["score"]) for r in res}
                pos = probs.get("positive", 0.0)
                neg = probs.get("negative", 0.0)
                neu = probs.get("neutral", 0.0)
                total_p = (pos + neg + neu) or 1.0
                rows.append((h, pos / total_p, neg / total_p, neu / total_p, (pos - neg) / total_p))
            _append_cache_rows(cache_path, rows)
            for row in rows:
                lookup[row[0]] = row[1:]
            done += len(rows)
            if (i // batch_size) % 20 == 19 or done >= total:
                print(f"[finbert] {done}/{total} scored+flushed")
    vals = [lookup[h] for h in hashes]
    return pd.DataFrame(vals, columns=["p_pos", "p_neg", "p_neu", "sent_score"])
