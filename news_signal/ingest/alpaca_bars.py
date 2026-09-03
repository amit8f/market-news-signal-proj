import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
CALENDAR_URL = "https://api.alpaca.markets/v2/calendar"


def _headers(cfg):
    return {
        "APCA-API-KEY-ID": cfg["alpaca_key_id"],
        "APCA-API-SECRET-KEY": cfg["alpaca_secret_key"],
    }


def fetch_calendar(cfg):
    resp = requests.get(
        CALENDAR_URL,
        headers=_headers(cfg),
        params={"start": cfg["dates"]["bars_start"], "end": cfg["dates"]["bars_end"]},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    df = pd.DataFrame(rows)[["date", "open", "close"]]
    out = ROOT / "data" / "raw" / "calendar.csv"
    df.to_csv(out, index=False)
    return df


def _fetch_bars(symbol, timeframe, start, end, cfg):
    frames = []
    page_token = None
    while True:
        params = {
            "symbols": symbol,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "feed": cfg["ingestion"]["alpaca_feed"],
            "limit": cfg["ingestion"]["alpaca_page_limit"],
            "adjustment": "split",
        }
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(BARS_URL, headers=_headers(cfg), params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        bars = payload.get("bars", {}).get(symbol, [])
        if bars:
            frames.append(pd.DataFrame(bars))
        page_token = payload.get("next_page_token")
        time.sleep(0.35)
        if not page_token:
            break
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "trade_count", "vwap"])
    df = pd.concat(frames, ignore_index=True).rename(
        columns={
            "t": "ts",
            "n": "trade_count",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
            "vw": "vwap",
        }
    )
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    cols = [c for c in ["open", "high", "low", "close", "volume", "trade_count", "vwap"] if c in df.columns]
    return df[cols]


def pull_all_bars(cfg):
    bars_dir = ROOT / "data" / "raw" / "bars"
    bars_dir.mkdir(parents=True, exist_ok=True)
    tickers = [row["ticker"] for row in cfg["universe"]] + [cfg["benchmark"]]
    for sym in tickers:
        out_path = bars_dir / f"{sym}_1min.csv"
        if out_path.exists():
            print(f"[alpaca] {sym}: cached")
            continue
        df = _fetch_bars(
            sym,
            "1Min",
            f"{cfg['dates']['bars_start']}T00:00:00Z",
            f"{cfg['dates']['bars_end']}T23:59:59Z",
            cfg,
        )
        df.to_csv(out_path)
        print(f"[alpaca] {sym}: {len(df)} minute bars")
    spy_daily_path = bars_dir / f"{cfg['benchmark']}_1day.csv"
    if not spy_daily_path.exists():
        import datetime as dt
        lb_start = (
            dt.date.fromisoformat(cfg["dates"]["bars_start"]) - dt.timedelta(days=cfg["dates"]["daily_lookback_days"])
        ).isoformat()
        daily = _fetch_bars(cfg["benchmark"], "1Day", lb_start, cfg["dates"]["bars_end"], cfg)
        daily.to_csv(spy_daily_path)
        print(f"[alpaca] {cfg['benchmark']} daily: {len(daily)} rows (lookback from {lb_start})")
    else:
        print(f"[alpaca] {cfg['benchmark']} daily: cached")
