import datetime as dt
import json
import time
from pathlib import Path

import requests

from news_signal.config import redact_secrets

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://finnhub.io/api/v1"


def fetch_company_news_window(ticker, start_date, end_date, api_key):
    try:
        resp = requests.get(
            f"{BASE_URL}/company-news",
            params={"symbol": ticker, "from": start_date, "to": end_date, "token": api_key},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        # The request URL (and thus the token query param) ends up in str(e) for
        # connection/timeout/HTTP errors alike - scrub it in place before it can
        # propagate to a print, log, or persisted poll_failures row.
        e.args = (redact_secrets(str(e)),)
        raise
    return resp.json()


def _week_windows(start_date, end_date):
    cur = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)
    while cur <= end:
        yield cur.isoformat(), min(cur + dt.timedelta(days=6), end).isoformat()
        cur += dt.timedelta(days=7)


def fetch_company_news_chunked(ticker, start_date, end_date, api_key):
    by_id = {}
    for frm, to in _week_windows(start_date, end_date):
        items = fetch_company_news_window(ticker, frm, to, api_key)
        for it in items:
            key = it.get("id")
            if key is None:
                key = f"{it.get('datetime')}_{hash(it.get('headline', ''))}"
            if key not in by_id:
                by_id[key] = it
        time.sleep(60.0 / 55.0)
    return list(by_id.values())


def pull_all_news(cfg, force=False):
    out_dir = ROOT / "data" / "raw" / "news"
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for row in cfg["universe"]:
        ticker = row["ticker"]
        out_path = out_dir / f"{ticker}.json"
        if out_path.exists() and not force:
            counts[ticker] = len(json.loads(out_path.read_text(encoding="utf-8")))
            print(f"[finnhub] {ticker}: cached ({counts[ticker]} items)")
            continue
        items = fetch_company_news_chunked(
            ticker, cfg["dates"]["news_start"], cfg["dates"]["news_end"], cfg["finnhub_api_key"]
        )
        out_path.write_text(json.dumps(items), encoding="utf-8")
        counts[ticker] = len(items)
        print(f"[finnhub] {ticker}: {len(items)} items ({cfg['dates']['news_start']} .. {cfg['dates']['news_end']}, weekly chunks)")
    return counts


def pull_company_profiles(cfg):
    out_path = ROOT / "data" / "raw" / "profiles.json"
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))
    profiles = {}
    for row in cfg["universe"]:
        ticker = row["ticker"]
        try:
            resp = requests.get(
                f"{BASE_URL}/stock/profile2",
                params={"symbol": ticker, "token": cfg["finnhub_api_key"]},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            e.args = (redact_secrets(str(e)),)
            raise
        profiles[ticker] = resp.json() or {}
        time.sleep(60.0 / 55.0)
    out_path.write_text(json.dumps(profiles), encoding="utf-8")
    print(f"[finnhub] company profiles saved: {len(profiles)}")
    return profiles
