import argparse
import hashlib
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from news_signal.config import load_config, raw_bars_dir, calendar_path, redact_secrets
from news_signal.ingest.finnhub_news import fetch_company_news_window, pull_company_profiles
from news_signal.ingest.alpaca_bars import _fetch_bars, _headers as _alpaca_headers
from news_signal.labels.forward_returns import build_sessions, filter_regular_minutes
from news_signal.features.relevance import tag_relevance, filter_relevance
from news_signal.live import artifacts as art
from news_signal.live import db
from news_signal.live.pipeline import build_event_frame, decide, simulate_exit


def utcnow():
    return pd.Timestamp.now(tz="UTC")


CALENDAR_REFRESH_BUFFER_DAYS = 14
CALENDAR_FETCH_HORIZON_DAYS = 60


def _calendar_is_stale(path, buffer_days=CALENDAR_REFRESH_BUFFER_DAYS):
    """A calendar.csv that merely exists can still be exhausted - it was previously only
    ever refetched when the file was entirely missing, so it silently ran out past its
    fixed end date and every live event fell outside all known sessions (dist_from_vwap_pct
    NaN on every event, since the last completed session was always in the past). Require
    the file to still cover at least buffer_days of trading days beyond today."""
    if not path.exists():
        return True
    cal = pd.read_csv(path)
    if cal.empty:
        return True
    max_date = pd.to_datetime(cal["date"]).max()
    return max_date < (utcnow().normalize().tz_localize(None) + pd.Timedelta(days=buffer_days))


class RateLimiter:
    """Evenly paces every Finnhub call (news polls and quotes) to at most calls_per_min
    per window_sec, shared across call sites. Enforces a minimum spacing between any two
    calls rather than just a count ceiling, so calls can never burst just because the
    window has spare capacity - a count-only ceiling lets an entire under-capacity sweep
    fire back-to-back with zero throttling, which is bursty enough to trip a real
    server-side limiter even while nominally staying under it."""

    def __init__(self, calls_per_min, window_sec=60.0):
        self.min_interval = window_sec / calls_per_min
        self.last_call = None

    def acquire(self):
        now = time.monotonic()
        if self.last_call is not None:
            wait = self.min_interval - (now - self.last_call)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
        self.last_call = now


def market_is_open(cfg):
    try:
        r = requests.get(
            "https://api.alpaca.markets/v2/clock",
            headers={"APCA-API-KEY-ID": cfg["alpaca_key_id"], "APCA-API-SECRET-KEY": cfg["alpaca_secret_key"]},
            timeout=10,
        )
        r.raise_for_status()
        return bool(r.json().get("is_open"))
    except Exception as e:
        print(f"[clock] unavailable ({redact_secrets(e)}); assuming closed")
        return False


CA_LOOKBACK_DAYS = 30  # widened from 7 so a VM outage of up to ~3 weeks can't make us miss an action
CA_SUPPRESSION_TRADING_DAYS = 60  # covers the longest feature window (vol_ratio_5d_40d)


def _ca_registry_path():
    return raw_bars_dir() / "corporate_actions_handled.json"


def _load_ca_registry():
    import json

    p = _ca_registry_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_ca_registry(registry):
    import json

    _ca_registry_path().write_text(json.dumps(registry, indent=2))


def fetch_corporate_actions(ticker, cfg, lookback_days=CA_LOOKBACK_DAYS):
    """Returns a list of {"ex_date": "YYYY-MM-DD", "type": "forward_split"/"reverse_split"/
    "spin_off"} for `ticker` within the last `lookback_days`. Used by BarCache to detect a
    cached bar file spanning across a corporate action (splits: needs a full re-fetch;
    spin-offs: adjustment=split cannot correct for these at all, so the ticker gets
    suppressed instead - see corporate_action_suppressed_until)."""
    try:
        end = utcnow().strftime("%Y-%m-%d")
        start = (utcnow() - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        r = requests.get(
            "https://data.alpaca.markets/v1/corporate-actions",
            headers=_alpaca_headers(cfg),
            params={"symbols": ticker, "types": "forward_split,reverse_split,spin_off",
                    "start": start, "end": end, "limit": 100},
            timeout=15,
        )
        r.raise_for_status()
        ca = r.json().get("corporate_actions", {})
        out = []
        for kind, rows in ca.items():
            action_type = kind[:-1] if kind.endswith("s") else kind  # "forward_splits" -> "forward_split"
            for row in rows:
                # splits name the ticker in `symbol`; spin-offs have no `symbol` and name the parent in
                # `source_symbol` (`new_symbol` is the spun-off child, which has no pre-event cache)
                if ticker in (row.get("symbol"), row.get("source_symbol")) and row.get("ex_date"):
                    out.append({"ex_date": row["ex_date"], "type": action_type})
        return out
    except Exception as e:
        print(f"[bars] corporate-actions check failed for {ticker}: {redact_secrets(e)}")
        return []


def corporate_action_suppressed_until(ticker, sessions):
    """Returns the UTC cutoff Timestamp before which `ticker` should be suppressed with
    suppress_reason='corporate_action' due to a recent spin-off - adjustment=split does not
    correct for spin-off value adjustments (confirmed on HON's 2026-06-29 spin-off, see
    EVALUATION_PLAN.md), so a refetch cannot fix it and the safe response is to not score
    real decisions on this ticker until the affected feature windows (up to
    CA_SUPPRESSION_TRADING_DAYS trading days) have rolled past the event. Returns None if no
    unexpired spin-off is on record for this ticker."""
    registry = _load_ca_registry()
    spinoffs = [a for a in registry.get(ticker, []) if a["type"] == "spin_off"]
    if not spinoffs:
        return None
    sess_starts = sessions["sess_start"].values.astype("datetime64[ns]")
    cutoffs = []
    for a in spinoffs:
        ex = np.datetime64(a["ex_date"])
        idx = int(np.searchsorted(sess_starts, ex, side="left"))
        end_idx = min(idx + CA_SUPPRESSION_TRADING_DAYS, len(sess_starts) - 1)
        if end_idx < 0:
            continue
        cutoffs.append(pd.Timestamp(sess_starts[end_idx]).tz_localize("UTC"))
    return max(cutoffs) if cutoffs else None


class BarCache:
    def __init__(self, sessions):
        self.sessions = sessions
        self.cache = {}
        self._ca_checked = {}  # ticker -> date.date() last checked, so this runs at most once/day

    def _maybe_handle_corporate_actions(self, ticker, path):
        """A cached bar file is fetched with adjustment=split and grown by appending new
        bars, never re-adjusting old ones. Checked at most once per ticker per day.
        - forward_split / reverse_split: if the cache already spans across the ex_date, the
          whole cached file is deleted so get() re-fetches it from scratch, consistently
          adjusted, instead of appending onto stale (differently-adjusted) data.
        - spin_off: adjustment=split does not correct for spin-offs at all, so a refetch
          would still contain the fake price drop - see corporate_action_suppressed_until()
          for the suppression-based handling instead.
        Each (ticker, ex_date, type) is recorded in a small on-disk registry once handled, so
        a legitimately-pre-ex_date cache (which is expected and correct after a real refetch)
        doesn't get deleted again on every check within the lookback window."""
        today = utcnow().date()
        if self._ca_checked.get(ticker) == today:
            return
        self._ca_checked[ticker] = today
        from news_signal.config import load_config

        actions = fetch_corporate_actions(ticker, load_config())
        if not actions:
            return
        registry = _load_ca_registry()
        ticker_handled = registry.setdefault(ticker, [])
        handled_keys = {(a["ex_date"], a["type"]) for a in ticker_handled}
        changed = False
        for action in actions:
            key = (action["ex_date"], action["type"])
            if key in handled_keys:
                continue
            if action["type"] in ("forward_split", "reverse_split"):
                if path.exists():
                    try:
                        existing = pd.read_csv(path, index_col=0)
                        existing.index = pd.to_datetime(existing.index, utc=True)
                    except Exception:
                        existing = None
                    if existing is not None and len(existing) and existing.index.min() <= pd.Timestamp(action["ex_date"], tz="UTC"):
                        print(f"[bars] {ticker}: {action['type']} detected (ex_date={action['ex_date']}), cache spans across it - deleting for full re-fetch")
                        path.unlink()
            elif action["type"] == "spin_off":
                print(f"[bars] {ticker}: spin_off detected (ex_date={action['ex_date']}) - "
                      f"adjustment=split cannot correct for this; suppressing with "
                      f"suppress_reason='corporate_action' for {CA_SUPPRESSION_TRADING_DAYS} trading days instead of refetching")
            ticker_handled.append(action)
            changed = True
        if changed:
            registry[ticker] = ticker_handled
            _save_ca_registry(registry)

    def get(self, ticker, lookback_days):
        path = raw_bars_dir() / f"{ticker}_1min.csv"
        if ticker in self.cache and (utcnow() - self.cache[ticker][1]).total_seconds() < 300:
            return self.cache[ticker][0]
        self._maybe_handle_corporate_actions(ticker, path)
        if path.exists():
            dfm = pd.read_csv(path, index_col=0)
            dfm.index = pd.to_datetime(dfm.index, utc=True)
        else:
            dfm = pd.DataFrame()
        if dfm.empty:
            dfm = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "trade_count", "vwap"])
            dfm.index = pd.DatetimeIndex([], tz="UTC")
        if dfm.empty or dfm.index.max() < utcnow() - pd.Timedelta(minutes=20):
            try:
                start = (utcnow() - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
                end = utcnow().strftime("%Y-%m-%d")
                from news_signal.config import load_config

                fresh = _fetch_bars(ticker, "1Min", f"{start}T00:00:00Z", f"{end}T23:59:59Z", load_config())
                if fresh is not None and len(fresh):
                    dfm = pd.concat([dfm, fresh[~fresh.index.isin(dfm.index)]]) if len(dfm) else fresh
                    dfm = filter_regular_minutes(dfm.sort_index(), self.sessions)
                    dfm.to_csv(path)
            except Exception as e:
                print(f"[bars] {ticker} refresh failed: {redact_secrets(e)}")
        reg = filter_regular_minutes(dfm.sort_index(), self.sessions)
        self.cache[ticker] = (reg, utcnow())
        return reg


def refresh_spy_daily(cfg):
    path = raw_bars_dir() / f"{cfg['benchmark']}_1day.csv"
    need_fetch = not path.exists()
    if not need_fetch:
        try:
            existing = pd.read_csv(path, index_col=0)
            last_day = pd.to_datetime(existing.index.max()).tz_localize("UTC") if pd.to_datetime(existing.index.max()).tzinfo is None else pd.to_datetime(existing.index.max())
            need_fetch = last_day < utcnow().normalize() - pd.Timedelta(days=4)
        except Exception:
            need_fetch = True
    if need_fetch:
        try:
            start = (utcnow() - pd.Timedelta(days=cfg["dates"]["daily_lookback_days"])).strftime("%Y-%m-%d")
            end = utcnow().strftime("%Y-%m-%d")
            daily = _fetch_bars(cfg["benchmark"], "1Day", start, end, cfg)
            if len(daily):
                daily.to_csv(path)
                print(f"[spy] daily refreshed: {len(daily)} rows")
        except Exception as e:
            print(f"[spy] refresh failed: {redact_secrets(e)}")
    s = pd.read_csv(path, index_col=0)["close"]
    s.index = pd.to_datetime(s.index, utc=True).normalize()
    return s.sort_index()


def poll_news(cfg, since_utc, limiter):
    items = []
    failures = []
    for row in cfg["universe"]:
        t = row["ticker"]
        batch = None
        last_err = None
        for attempt in range(3):
            limiter.acquire()
            try:
                batch = fetch_company_news_window(
                    t,
                    (since_utc - pd.Timedelta(minutes=2)).strftime("%Y-%m-%d"),
                    since_utc.strftime("%Y-%m-%d"),
                    cfg["finnhub_api_key"],
                )
                break
            except requests.exceptions.HTTPError as e:
                last_err = e
                resp = e.response
                if resp is not None and resp.status_code == 429 and attempt < 2:
                    try:
                        wait_s = float(resp.headers.get("Retry-After"))
                    except (TypeError, ValueError):
                        wait_s = 10.0
                    wait_s = max(5.0, min(wait_s, 15.0))
                    print(f"[news] {t} 429, retrying in {wait_s:.0f}s (attempt {attempt + 1}/2)")
                    time.sleep(wait_s)
                    continue
                break
            except Exception as e:
                last_err = e
                break
        if batch is None:
            safe_err = redact_secrets(last_err)
            print(f"[news] {t} poll failed: {safe_err}")
            failures.append((t, safe_err))
            continue
        for it in batch:
            it["ticker"] = t
            items.append(it)
    return items, failures


def _ensure_poll_failure_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS poll_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT,
            ticker TEXT,
            error TEXT
        )"""
    )
    conn.commit()


def _record_poll_failures(conn, failures, ts_iso):
    for ticker, err in failures:
        conn.execute(
            "INSERT INTO poll_failures (ts_utc, ticker, error) VALUES (?, ?, ?)",
            (ts_iso, ticker, err),
        )
    conn.commit()


def _ensure_stale_rejection_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS stale_rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT,
            ticker TEXT,
            headline TEXT,
            published_utc TEXT,
            age_minutes REAL
        )"""
    )
    conn.commit()


def _record_stale_rejection(conn, ticker, headline, published_iso, age_minutes, ts_iso):
    conn.execute(
        "INSERT INTO stale_rejections (ts_utc, ticker, headline, published_utc, age_minutes) VALUES (?, ?, ?, ?, ?)",
        (ts_iso, ticker, headline, published_iso, age_minutes),
    )
    conn.commit()


def poll_alpaca_news(cfg, since_utc):
    """Parallel, additive poll of Alpaca/Benzinga News for the tracked universe.
    Investigation-only: results are logged to alpaca_news_seen for a coverage/latency
    comparison against Finnhub, not fed into build_event_frame()/classify()/decide()."""
    tickers = set(row["ticker"] for row in cfg["universe"])
    items = []
    try:
        params = {
            "symbols": ",".join(sorted(tickers)),
            "start": since_utc.isoformat(),
            "limit": 50,
            "sort": "asc",
        }
        page_token = None
        while True:
            if page_token:
                params["page_token"] = page_token
            r = requests.get(
                "https://data.alpaca.markets/v1beta1/news",
                headers=_alpaca_headers(cfg),
                params=params,
                timeout=15,
            )
            r.raise_for_status()
            payload = r.json()
            for art_item in payload.get("news", []):
                n_symbols = len(art_item.get("symbols", []))
                for sym in art_item.get("symbols", []):
                    if sym in tickers:
                        items.append({
                            "alpaca_id": art_item.get("id"),
                            "ticker": sym,
                            "headline": art_item.get("headline", ""),
                            "summary": art_item.get("summary", ""),
                            "author": art_item.get("author", ""),
                            "source": art_item.get("source", ""),
                            "url": art_item.get("url", ""),
                            "created_at": art_item.get("created_at", ""),
                            "n_symbols": n_symbols,
                        })
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return items, None
    except Exception as e:
        return [], redact_secrets(e)


def alpaca_items_to_news_shape(alpaca_items):
    """Reshapes poll_alpaca_news() output to match the Finnhub item shape process_items()
    expects (ticker, headline, summary, source, url, id, datetime as unix seconds)."""
    out = []
    for it in alpaca_items:
        try:
            ts = int(pd.Timestamp(it["created_at"]).timestamp())
        except Exception:
            continue
        out.append({
            "ticker": it["ticker"],
            "headline": it.get("headline", ""),
            "summary": it.get("summary", ""),
            "source": it.get("source", "") or "alpaca",
            "url": it.get("url", ""),
            "id": it.get("alpaca_id"),
            "datetime": ts,
            "category": "",
            "n_symbols": it.get("n_symbols"),
        })
    return out


def _ensure_alpaca_news_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS alpaca_news_seen (
            alpaca_id INTEGER,
            ticker TEXT,
            ts_utc TEXT,
            headline TEXT,
            author TEXT,
            source TEXT,
            created_at TEXT,
            lag_minutes REAL,
            PRIMARY KEY (alpaca_id, ticker)
        )"""
    )
    conn.commit()


def _record_alpaca_news(conn, items, ts_iso):
    now = pd.Timestamp(ts_iso)
    n_new = 0
    for it in items:
        try:
            lag_min = (now - pd.Timestamp(it["created_at"])).total_seconds() / 60.0
        except Exception:
            lag_min = None
        cur = conn.execute(
            """INSERT OR IGNORE INTO alpaca_news_seen
               (alpaca_id, ticker, ts_utc, headline, author, source, created_at, lag_minutes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (it["alpaca_id"], it["ticker"], ts_iso, it["headline"], it["author"],
             it["source"], it["created_at"], lag_min),
        )
        if cur.rowcount:
            n_new += 1
    conn.commit()
    return n_new


def _ensure_retrieval_lag_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS retrieval_lag (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT,
            ticker TEXT,
            headline TEXT,
            published_utc TEXT,
            lag_minutes REAL,
            rejected_stale INTEGER
        )"""
    )
    conn.commit()


def _record_retrieval_lag(conn, ticker, headline, published_iso, lag_minutes, rejected_stale, ts_iso):
    conn.execute(
        "INSERT INTO retrieval_lag (ts_utc, ticker, headline, published_utc, lag_minutes, rejected_stale) VALUES (?, ?, ?, ?, ?, ?)",
        (ts_iso, ticker, headline, published_iso, lag_minutes, int(rejected_stale)),
    )
    conn.commit()


def _ensure_signal_insert_log_table(conn):
    """Durable, per-call record of every argument passed to db.insert_signal() - independent
    of the signals table itself, so a bug that corrupts the insert (e.g. a field silently
    landing NULL) can be caught with full context at the moment it happens, rather than
    reconstructed after the fact from an ambiguous signals row."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS signal_insert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at_utc TEXT,
            ts_utc TEXT,
            ticker TEXT,
            class_name TEXT,
            prob_calibrated REAL,
            prob_raw REAL,
            severity_score REAL,
            severe INTEGER,
            entry_price REAL,
            entry_source TEXT,
            stop_price REAL,
            headline TEXT,
            url TEXT,
            status TEXT,
            suppress_reason TEXT,
            news_source TEXT,
            dedup_group_id TEXT,
            n_symbols INTEGER
        )"""
    )
    conn.commit()


def _record_signal_insert(conn, kw, ts_iso):
    conn.execute(
        """INSERT INTO signal_insert_log
           (logged_at_utc,ts_utc,ticker,class_name,prob_calibrated,prob_raw,severity_score,severe,
            entry_price,entry_source,stop_price,headline,url,status,suppress_reason,news_source,
            dedup_group_id,n_symbols)
           VALUES (:logged_at_utc,:ts_utc,:ticker,:class_name,:prob_calibrated,:prob_raw,:severity_score,:severe,
            :entry_price,:entry_source,:stop_price,:headline,:url,:status,:suppress_reason,:news_source,
            :dedup_group_id,:n_symbols)""",
        {**kw, "logged_at_utc": ts_iso},
    )
    conn.commit()


_sessions_holder = {"sessions": None}


def csv_peer_minutes(ticker):
    path = raw_bars_dir() / f"{ticker}_1min.csv"
    if not path.exists():
        return None
    m = pd.read_csv(path, index_col=0)
    m.index = pd.to_datetime(m.index, utc=True)
    return filter_regular_minutes(m, _sessions_holder["sessions"])


def fetch_quote(cfg, ticker):
    try:
        r = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{ticker}/trades/latest",
            headers=_alpaca_headers(cfg),
            params={"feed": cfg["ingestion"]["alpaca_feed"]},
            timeout=10,
        )
        p = float((r.json().get("trade") or {}).get("p") or 0)
        if p > 0:
            return p, "alpaca_trade"
    except Exception:
        pass
    return None, "unavailable"


def process_items(items, ctx, news_source="finnhub"):
    cfg = ctx["cfg"]
    conn = ctx["conn"]
    clf = ctx["clf"]
    severity = ctx["severity"]
    iso_maps = ctx["iso_maps"]
    class_names = ctx["class_names"]
    thresholds = ctx["thresholds"]
    bars = ctx["bars"]
    live_cfg = cfg.get("live", {})
    suppressed = tuple(live_cfg.get("suppress_classes", ["Sell"]))
    horizon = cfg["labels"]["horizon_minutes"]

    if not items:
        print("[cycle] polled 0 candidate items, nothing to tag")
        return 0

    ndf = pd.DataFrame(items)
    ndf["news_hash"] = [
        hashlib.md5(f"{news_source}|{r['ticker']}|{r['headline']}|{r['datetime']}".encode()).hexdigest()
        for _, r in ndf.iterrows()
    ]
    new_hashes = set(db.filter_new_hashes(conn, ndf["news_hash"].tolist()))
    ndf = ndf[ndf["news_hash"].isin(new_hashes)].drop_duplicates(subset=["news_hash"])
    print(f"[cycle] {len(ndf)} new items since last seen")
    if len(ndf) == 0:
        return 0
    db.mark_seen(conn, ndf["news_hash"].tolist(), ndf["ticker"].tolist(), utcnow().isoformat())

    ndf = tag_relevance(ndf, cfg["universe"], ctx["profiles"], strict_sources=[])
    ndf, _ = filter_relevance(ndf, drop_non_primary=True)
    if len(ndf) == 0:
        print("[cycle] no relevant items after relevance filter")
        return 0
    print(f"[cycle] {len(ndf)} new relevant items")

    max_delay_min = live_cfg["max_retrieval_lag_minutes"]
    dedup_window_min = live_cfg.get("dedup_window_minutes", 15)
    fired_count = 0
    for _, ev in ndf.iterrows():
        published = pd.Timestamp(ev["datetime"], unit="s", tz="UTC")
        age_min = (utcnow() - published).total_seconds() / 60.0
        is_stale = age_min > max_delay_min
        _record_retrieval_lag(conn, ev["ticker"], ev["headline"], published.isoformat(), age_min, is_stale, utcnow().isoformat())
        if is_stale:
            _record_stale_rejection(conn, ev["ticker"], ev["headline"], published.isoformat(), age_min, utcnow().isoformat())
            print(f"[stale] {ev['ticker']} rejected, age={age_min:.1f}min > {max_delay_min}min: {ev['headline'][:60]}")
            continue
        minutes = bars.get(ev["ticker"], live_cfg.get("bar_cache_days", 75))
        recency, prior24 = db.recent_headlines_before(conn, ev["ticker"], published.isoformat())
        X, info = build_event_frame(
            ev["ticker"], ev["headline"], str(ev.get("summary", "") or ""), ev.get("source", ""),
            published, ctx["profiles"], cfg["universe"], {ev["ticker"]: minutes}, ctx["sessions"],
            ctx["spy_close"], cfg, recency, prior24,
            expected_columns=ctx["expected_columns"], peer_loader=csv_peer_minutes,
        )
        if X is None:
            continue
        raw = clf.predict_proba(X)[0]
        cal = art.calibrate(raw.reshape(1, -1), iso_maps)[0]
        decision = decide(cal, thresholds, class_names, suppressed=suppressed)
        sev_score = float(severity.predict(X)[0])
        severe_buy_edge, severe_sell_edge = 1.48, -1.4308
        severe = int((decision["class"] == "Sell" and sev_score <= severe_sell_edge) or (decision["class"] in ("Buy", "Strong Buy") and sev_score >= severe_buy_edge))
        status = decision["status"]
        reason = "" if status == "fired" else ("sell_side_suppressed" if decision["class"] == "Sell" and "Sell" in suppressed else "below_threshold")
        ca_cutoff = corporate_action_suppressed_until(ev["ticker"], ctx["sessions"])
        if ca_cutoff is not None and published < ca_cutoff:
            status, reason = "silent", "corporate_action"
        entry_price, entry_source = fetch_quote(cfg, ev["ticker"])
        if entry_price is None:
            if len(minutes) == 0:
                continue
            entry_price = float(minutes["close"].iloc[-1])
            entry_source = "last_regular_close_proxy"
        stop_price = entry_price * (1 - cfg["backtest"]["stop_atr_multiple"] * float(X["atr14_1h_pct"].iloc[0])) if decision["class"] in ("Buy", "Strong Buy") else np.nan
        bucket_start = published.floor(f"{dedup_window_min}min")
        dedup_group_id = hashlib.md5(f"{ev['ticker']}|{bucket_start.isoformat()}".encode()).hexdigest()[:12]
        insert_kw = dict(
            ts_utc=published.isoformat(),
            ticker=ev["ticker"],
            class_name=decision["class"],
            prob_calibrated=float(decision["prob_calibrated"]),
            prob_raw=float(raw.max()),
            severity_score=sev_score,
            severe=severe,
            entry_price=entry_price,
            entry_source=entry_source,
            stop_price=stop_price,
            headline=ev["headline"],
            url=ev.get("url", ""),
            status=status,
            suppress_reason=reason,
            news_source=news_source,
            dedup_group_id=dedup_group_id,
            n_symbols=(int(ev["n_symbols"]) if ev.get("n_symbols") is not None and not pd.isna(ev.get("n_symbols")) else None),
        )
        _record_signal_insert(conn, insert_kw, utcnow().isoformat())
        sid = db.insert_signal(conn, **insert_kw)
        line = f"[signal] {ev['ticker']} {decision['class']} p_cal={decision['prob_calibrated']:.3f} sev={sev_score:+.2f} status={status}"
        if status == "fired" and decision["class"] != "Sell":
            fired_count += 1
            notify(cfg, f"{line}\n{ev['headline']}\nentry={entry_price:.2f} stop={stop_price:.2f}\n{ev.get('url','')}")
        print(line + (f" ({reason})" if reason else ""))
    return fired_count


def backfill_outcomes(ctx):
    cfg, conn = ctx["cfg"], ctx["conn"]
    horizon_min = cfg["labels"]["horizon_minutes"]
    cutoff = (utcnow() - pd.Timedelta(minutes=horizon_min + 5)).isoformat()
    pending = db.pending_outcomes(conn, cutoff)
    bars = ctx["bars"]
    slip = cfg["backtest"]["slippage_bps_per_side"] / 1e4
    for signal_id, ticker, entry_px, stop_px, ts_iso in pending:
        minutes = bars.get(ticker, cfg.get("live", {}).get("bar_cache_days", 75))
        exit_target = pd.Timestamp(ts_iso) + pd.Timedelta(minutes=horizon_min)
        # stop_price is NULL/None for every non-Buy/Strong-Buy signal (silent Sell/Neutral/
        # below-threshold) - simulate_exit() already treats a NaN stop as "never stops,
        # exit at horizon close", exactly the right behavior for a signal that was never
        # actually entered; float(None) would raise, so convert explicitly.
        stop_val = float(stop_px) if stop_px is not None else float("nan")
        res = simulate_exit(minutes, ts_iso, exit_target.isoformat(), float(entry_px), stop_val)
        if res is None:
            continue
        net = (res["exit_price"] * (1 - slip)) / (float(entry_px) * (1 + slip)) - 1.0
        gross = res["exit_price"] / float(entry_px) - 1.0
        db.insert_outcome(conn, signal_id, res["exit_ts"], res["exit_price"], res["stopped"], gross, net, utcnow().isoformat())
        print(f"[outcome] signal {signal_id} {ticker}: {'STOP' if res['stopped'] else 'exit'} {gross:+.3%} gross / {net:+.3%} net")


def notify(cfg, text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (cfg.get("live", {}).get("notify_enabled") and token and chat):
        print("[notify] shadow/log-only:", text.splitlines()[0])
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat, "text": text}, timeout=10)
    except Exception as e:
        print(f"[notify] telegram failed: {redact_secrets(e)}")


import os


def run_cycle(cfg, ctx):
    lookback = cfg.get("live", {}).get("news_lookback_minutes", 10)
    since = utcnow() - pd.Timedelta(minutes=lookback)
    items, poll_failures = poll_news(cfg, since, ctx["rate_limiter"])
    n_universe = len(cfg["universe"])
    tickers_failed = ", ".join(t for t, _ in poll_failures)
    print(f"[cycle] {len(poll_failures)}/{n_universe} ticker polls failed" + (f": {tickers_failed}" if poll_failures else ""))
    if poll_failures:
        _record_poll_failures(ctx["conn"], poll_failures, utcnow().isoformat())
    print(f"[cycle] polled {len(items)} candidate items")
    n_fired = process_items(items, ctx, news_source="finnhub")

    # Alpaca News: same live decision path as Finnhub, tagged news_source="alpaca" so
    # fire rate / class distribution / behavior can be compared by source. Both sources
    # are scored independently (no suppression) - see dedup_group_id for correlated items.
    alpaca_items, alpaca_err = poll_alpaca_news(cfg, since)
    if alpaca_err:
        print(f"[alpaca-news] poll failed: {alpaca_err}")
    else:
        n_new = _record_alpaca_news(ctx["conn"], alpaca_items, utcnow().isoformat())
        print(f"[alpaca-news] polled {len(alpaca_items)} ticker-tagged items, {n_new} new")
        alpaca_shaped = alpaca_items_to_news_shape(alpaca_items)
        n_fired += process_items(alpaca_shaped, ctx, news_source="alpaca")

    backfill_outcomes(ctx)
    return n_fired


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--inject-demo", action="store_true")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    conn = db.connect()
    db.init_db(conn)
    db.ensure_news_source_columns(conn)
    _ensure_poll_failure_table(conn)
    _ensure_stale_rejection_table(conn)
    _ensure_retrieval_lag_table(conn)
    _ensure_alpaca_news_table(conn)
    _ensure_signal_insert_log_table(conn)
    if _calendar_is_stale(calendar_path()):
        from news_signal.ingest.alpaca_bars import fetch_calendar

        print("[setup] calendar.csv missing or stale - refreshing trading calendar")
        fetch_calendar(
            cfg,
            start=cfg["dates"]["bars_start"],
            end=(utcnow().normalize() + pd.Timedelta(days=CALENDAR_FETCH_HORIZON_DAYS)).strftime("%Y-%m-%d"),
        )
    sessions = build_sessions(calendar_path())
    _sessions_holder["sessions"] = sessions
    profiles = pull_company_profiles(cfg)
    clf = art.load_champion()
    severity = art.load_severity_regressor()
    iso_maps, class_names = art.load_calibration()
    thr_blob = art.load_thresholds()
    thresholds = thr_blob["calibrated_thresholds"]
    suppressed_extra = tuple(thr_blob.get("suppressed_classes", []))
    bars = BarCache(sessions)
    spy_close = refresh_spy_daily(cfg)
    rate_limiter = RateLimiter(cfg["ingestion"]["finnhub_rate_limit_per_min"])
    ctx = {
        "cfg": cfg, "conn": conn, "clf": clf, "severity": severity, "iso_maps": iso_maps,
        "class_names": class_names, "thresholds": thresholds, "bars": bars, "sessions": sessions,
        "profiles": profiles, "spy_close": spy_close,
        "expected_columns": clf.get_booster().feature_names,
        "rate_limiter": rate_limiter,
    }

    if args.inject_demo:
        demo = [{
            "datetime": int(datetime.now(timezone.utc).timestamp()),
            "headline": "NVIDIA announces record quarterly results and raises full-year guidance",
            "summary": "The company said demand for its data-center products remains very strong.",
            "source": "demo", "url": "", "id": 999999001, "category": "demo",
        }]
        demo[0]["ticker"] = "NVDA"
        process_items(demo, ctx)
        return

    if args.once or not args.loop:
        if not market_is_open(cfg):
            print("[run] market closed - cycle skipped (shadow mode stays armed)")
            if args.once:
                return
        run_cycle(cfg, ctx)
        return

    interval = cfg.get("live", {}).get("poll_interval_sec", 120)
    print(f"[run] entering loop every {interval}s (SHADOW MODE - log only)")
    while True:
        try:
            if market_is_open(cfg):
                run_cycle(cfg, ctx)
            else:
                print("[run] market closed; idling")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[run] cycle error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
