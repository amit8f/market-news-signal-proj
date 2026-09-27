import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "live" / "signals.db"


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS seen_news (
            news_hash TEXT PRIMARY KEY,
            ticker TEXT,
            first_seen_utc TEXT
        );
        CREATE TABLE IF NOT EXISTS signals (
            signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        );
        CREATE TABLE IF NOT EXISTS outcomes (
            signal_id INTEGER PRIMARY KEY REFERENCES signals(signal_id),
            exit_ts TEXT,
            exit_price REAL,
            stopped INTEGER,
            ret_gross REAL,
            ret_net REAL,
            filled_at TEXT
        );
        """
    )
    conn.commit()


def ensure_news_source_columns(conn):
    """Migration for pre-existing signals.db files created before news_source/dedup_group_id/
    n_symbols existed (CREATE TABLE IF NOT EXISTS in init_db() only applies to brand-new tables)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(signals)").fetchall()}
    if "news_source" not in cols:
        conn.execute("ALTER TABLE signals ADD COLUMN news_source TEXT")
    if "dedup_group_id" not in cols:
        conn.execute("ALTER TABLE signals ADD COLUMN dedup_group_id TEXT")
    if "n_symbols" not in cols:
        conn.execute("ALTER TABLE signals ADD COLUMN n_symbols INTEGER")
    conn.commit()


def filter_new_hashes(conn, hashes):
    if not hashes:
        return []
    q = ",".join("?" for _ in hashes)
    rows = conn.execute(f"SELECT news_hash FROM seen_news WHERE news_hash IN ({q})", list(hashes)).fetchall()
    return [h for h in hashes if h not in {r[0] for r in rows}]


def mark_seen(conn, hashes, tickers, ts_iso):
    for h, t in zip(hashes, tickers):
        conn.execute(
            "INSERT OR IGNORE INTO seen_news VALUES (?,?,?)", (h, t, ts_iso)
        )
    conn.commit()


def insert_signal(conn, **kw):
    cur = conn.execute(
        """INSERT INTO signals (ts_utc,ticker,class_name,prob_calibrated,prob_raw,severity_score,severe,
           entry_price,entry_source,stop_price,headline,url,status,suppress_reason,news_source,dedup_group_id,n_symbols)
           VALUES (:ts_utc,:ticker,:class_name,:prob_calibrated,:prob_raw,:severity_score,:severe,
           :entry_price,:entry_source,:stop_price,:headline,:url,:status,:suppress_reason,:news_source,:dedup_group_id,:n_symbols)""",
        kw,
    )
    conn.commit()
    return cur.lastrowid


def pending_outcomes(conn, older_than_iso):
    """Every signal regardless of status (fired or silent) is eligible for outcome
    backfill once it's old enough to have resolved - not just fired ones, so real
    price-outcome evidence accumulates for the full decision distribution (including
    suppressed/below-threshold classes), not only the subset that actually fired."""
    rows = conn.execute(
        """SELECT s.signal_id,s.ticker,s.entry_price,s.stop_price,s.ts_utc FROM signals s
           LEFT JOIN outcomes o ON o.signal_id = s.signal_id
           WHERE o.signal_id IS NULL AND s.ts_utc <= ?""",
        (older_than_iso,),
    ).fetchall()
    return rows


def insert_outcome(conn, signal_id, exit_ts, exit_price, stopped, ret_gross, ret_net, filled_at):
    conn.execute(
        "INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?,?)",
        (signal_id, exit_ts, exit_price, int(stopped), ret_gross, ret_net, filled_at),
    )
    conn.commit()


def recent_headlines_before(conn, ticker, before_iso, window_hours=24):
    import pandas as pd

    cutoff = (pd.Timestamp(before_iso) - pd.Timedelta(hours=window_hours)).isoformat()
    rows = conn.execute(
        "SELECT first_seen_utc FROM seen_news WHERE ticker=? AND first_seen_utc < ? ORDER BY first_seen_utc",
        (ticker, before_iso),
    ).fetchall()
    times = pd.to_datetime([r[0] for r in rows], utc=True)
    in_window = times[times >= pd.Timestamp(cutoff)]
    prev = times[times < pd.Timestamp(before_iso)]
    hours_prev = float((pd.Timestamp(before_iso) - prev.max()).total_seconds() / 3600) if len(prev) else float("nan")
    return hours_prev, int(len(in_window))
