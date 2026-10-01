"""Weekly descriptive report on a downloaded copy of the VM's signals.db.

Implements the secondary analyses (a)-(d) registered in EVALUATION_PLAN.md Section 9
(2026-10-01, before looking). Read-only on the DB; fetches its own bars from Alpaca
(feed=sip, adjustment=all) and never touches the live path or data/raw caches.

    python scripts/weekly_report.py path/to/signals.db > reports/weekly_YYYY-MM-DD.md
"""
import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from news_signal.config import load_config, redact_secrets  # noqa: E402
from news_signal.features.regime import spy_regime_row, ticker_regime_row  # noqa: E402

BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
CALENDAR_URL = "https://api.alpaca.markets/v2/calendar"
ET = "America/New_York"
AFFECTED_UNTIL = pd.Timestamp("2026-09-09T13:07:29Z")  # Section 7 calendar-bug window
HORIZON_MIN = 120
SEED = 20261001
B_BOOT = 2000
N_DRAWS = 1000
THIN_N = 30
MIN_DAYS, MIN_FIRED = 40, 300  # Section 4
LONG = ("Buy", "Strong Buy")
CLASSES = ("Strong Buy", "Buy", "Neutral", "Sell")


def _headers(cfg):
    return {"APCA-API-KEY-ID": cfg["alpaca_key_id"], "APCA-API-SECRET-KEY": cfg["alpaca_secret_key"]}


def _get(url, cfg, params):
    try:
        r = requests.get(url, headers=_headers(cfg), params=params, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise RuntimeError(redact_secrets(e)) from None


def fetch_bars(symbol, timeframe, start, end, cfg):
    frames, token = [], None
    while True:
        params = {"symbols": symbol, "timeframe": timeframe, "start": start, "end": end,
                  "feed": "sip", "adjustment": "all", "limit": 10000}
        if token:
            params["page_token"] = token
        payload = _get(BARS_URL, cfg, params)
        rows = payload.get("bars", {}).get(symbol, [])
        if rows:
            frames.append(pd.DataFrame(rows))
        token = payload.get("next_page_token")
        time.sleep(0.35)
        if not token:
            break
    if not frames:
        return pd.DataFrame(columns=["o", "c", "v"])
    df = pd.concat(frames, ignore_index=True)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df.set_index("t").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df[df["v"] > 0][["o", "c", "v"]]


def fetch_sessions(start_date, end_date, cfg):
    cal = pd.DataFrame(_get(CALENDAR_URL, cfg, {"start": start_date, "end": end_date}))
    cal["open_utc"] = pd.to_datetime(cal["date"] + " " + cal["open"]).dt.tz_localize(ET).dt.tz_convert("UTC")
    cal["close_utc"] = pd.to_datetime(cal["date"] + " " + cal["close"]).dt.tz_localize(ET).dt.tz_convert("UTC")
    return cal[["date", "open_utc", "close_utc"]].sort_values("open_utc").reset_index(drop=True)


def load_db(db_path):
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    sig = pd.read_sql("SELECT * FROM signals ORDER BY signal_id", conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    log = (pd.read_sql("SELECT id, logged_at_utc, ts_utc, ticker, url, headline FROM signal_insert_log ORDER BY id", conn)
           if "signal_insert_log" in tables else pd.DataFrame(columns=["id", "logged_at_utc", "ts_utc", "ticker", "url", "headline"]))
    conn.close()
    return sig, log


def attach_decision_time(sig, log):
    key = ["ts_utc", "ticker", "url", "headline"]
    s, g = sig.copy(), log.copy()
    for df in (s, g):
        for k in key:
            df[k] = df[k].fillna("")
        df["_k"] = df.groupby(key).cumcount()
    m = s.merge(g[key + ["_k", "logged_at_utc"]], on=key + ["_k"], how="left")
    m["t0"] = pd.to_datetime(m["logged_at_utc"], utc=True, format="ISO8601")
    return m.drop(columns="_k")


def window_returns(bars, t0, t1):
    """P0 = open of first bar starting at/after t0; P1 = close of last bar starting before t1."""
    out = np.full(len(t0), np.nan)
    if len(bars) == 0:
        return out
    ts = bars.index.values.astype("datetime64[ns]").astype(np.int64)
    i0 = np.searchsorted(ts, t0, side="left")
    i1 = np.searchsorted(ts, t1, side="left") - 1
    ok = (i0 < len(ts)) & (i1 >= i0)
    o, c = bars["o"].values, bars["c"].values
    out[ok] = c[i1[ok]] / o[i0[ok]] - 1.0
    return out


def day_weights(days):
    codes, uniq = pd.factorize(days)
    counts = np.bincount(codes)
    return 1.0 / (len(uniq) * counts[codes]), codes, len(uniq)


def summarize(x, days, rng):
    x, days = np.asarray(x, float), np.asarray(days)
    keep = ~np.isnan(x)
    x, days = x[keep], days[keep]
    if len(x) == 0:
        return dict(n=0, d=0, dmean=np.nan, pooled=np.nan, lo=np.nan, hi=np.nan, neg=np.nan)
    _, codes, nd = day_weights(days)
    day_means = np.bincount(codes, weights=x) / np.bincount(codes)
    boots = day_means[rng.integers(0, nd, size=(B_BOOT, nd))].mean(axis=1)
    return dict(n=len(x), d=nd, dmean=day_means.mean(), pooled=x.mean(),
                lo=np.percentile(boots, 2.5), hi=np.percentile(boots, 97.5), neg=(x < 0).mean())


def pct(v):
    return "n/a" if np.isnan(v) else f"{v * 100:+.3f}%"


def row(label, s, thin_note=True):
    flag = " THIN (n<30)" if thin_note and s["n"] < THIN_N else ""
    return (f"| {label} | {s['n']} | {s['d']} | {pct(s['dmean'])} | [{pct(s['lo'])}, {pct(s['hi'])}] | "
            f"{pct(s['pooled'])} |{flag} |")


HDR = ("| group | n signals | n days | day-clustered mean | 95% CI (day bootstrap) | pooled mean | note |\n"
       "|---|---|---|---|---|---|---|")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="path to a downloaded copy of signals.db (opened read-only)")
    args = ap.parse_args()
    cfg = load_config()
    universe = [u["ticker"] for u in cfg["universe"]]
    bench = cfg["benchmark"]
    rng = np.random.default_rng(SEED)

    sig, log = load_db(args.db)
    p = print
    p(f"# Weekly descriptive report\n")
    p(f"- DB: `{Path(args.db).name}`; generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    p(f"- Analyses registered in EVALUATION_PLAN.md Section 9 (2026-10-01, before looking). SECONDARY/DESCRIPTIVE ONLY: "
      f"not the Section 3 primary endpoint, no Section 5 decision.")
    p(f"- Returns are gross (no costs), bars `feed=sip`, `adjustment=all`. Section 4a per-day validity gates are NOT applied.\n")

    # ---------------- counts ----------------
    p("## Counts (all rows in `signals`)\n")
    if len(sig) == 0:
        p("No signals in this DB.")
        return
    p(f"- Total signals: {len(sig)} (`ts_utc` {sig['ts_utc'].min()} .. {sig['ts_utc'].max()})")
    p(f"- By class: " + ", ".join(f"{c} {int((sig['class_name'] == c).sum())}" for c in CLASSES))
    p(f"- By status: " + ", ".join(f"{k} {v}" for k, v in sig["status"].value_counts().items()))
    sr = sig.loc[sig["status"] != "fired", "suppress_reason"].fillna("(none)").value_counts()
    p(f"- Not fired, by suppress_reason: " + ", ".join(f"{k} {v}" for k, v in sr.items())
      + f"; corporate_action {int((sig['suppress_reason'] == 'corporate_action').sum())}")
    p(f"- Fired Buy/Strong Buy: {int(((sig['status'] == 'fired') & sig['class_name'].isin(LONG)).sum())}")
    by_t = sig.groupby("ticker")["class_name"].value_counts().unstack(fill_value=0).reindex(columns=list(CLASSES), fill_value=0)
    by_t["total"] = by_t.sum(axis=1)
    p("\n| ticker | " + " | ".join(by_t.columns) + " |\n|---|" + "---|" * len(by_t.columns))
    for t, r in by_t.sort_values("total", ascending=False).iterrows():
        p(f"| {t} | " + " | ".join(str(int(v)) for v in r.values) + " |")

    # ---------------- funnel ----------------
    p("\n## Funnel (registered exclusions)\n")
    df = attach_decision_time(sig, log)
    funnel = [("all signals", len(df))]
    df = df[pd.to_datetime(df["ts_utc"], utc=True, format="ISO8601") >= AFFECTED_UNTIL]
    funnel.append(("ts_utc >= 2026-09-09T13:07:29Z (Section 7 affected window removed)", len(df)))
    df = df[df["suppress_reason"].fillna("") != "corporate_action"]
    funnel.append(("not suppress_reason='corporate_action'", len(df)))
    df = df[df["t0"].notna()]
    funnel.append(("matched to signal_insert_log (decision time known)", len(df)))
    if len(df) == 0:
        for k, v in funnel:
            p(f"- {k}: {v}")
        p("\nNo analyzable signals.")
        return
    first = df["t0"].min().tz_convert(ET).date() - pd.Timedelta(days=5)
    last = df["t0"].max().tz_convert(ET).date() + pd.Timedelta(days=5)
    sess = fetch_sessions(str(first), str(last), cfg)
    t0_ns = df["t0"].values.astype("datetime64[ns]").astype(np.int64)
    opens = sess["open_utc"].values.astype("datetime64[ns]").astype(np.int64)
    closes = sess["close_utc"].values.astype("datetime64[ns]").astype(np.int64)
    si = np.searchsorted(opens, t0_ns, side="right") - 1
    in_sess = (si >= 0) & (t0_ns < closes[np.clip(si, 0, None)])
    df, t0_ns, si = df[in_sess].copy(), t0_ns[in_sess], si[in_sess]
    funnel.append(("decision time inside a regular session", len(df)))
    t1_ns = np.minimum(t0_ns + HORIZON_MIN * 60 * 10**9, closes[si])
    df["day"] = sess["date"].values[si]
    since_open = (t0_ns - opens[si]) / 6e10
    to_close = (closes[si] - t0_ns) / 6e10
    df["tod"] = np.where(since_open < 60, "first hour", np.where(to_close <= 120, "last 2h", "midday"))

    # only the span the windows need, and never the latest 15 min (free-tier SIP refuses it)
    latest_ok = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=16)
    start = pd.Timestamp(t0_ns.min(), tz="UTC").floor("min").strftime("%Y-%m-%dT%H:%M:%SZ")
    end = min(pd.Timestamp(t1_ns.max(), tz="UTC"), latest_ok).strftime("%Y-%m-%dT%H:%M:%SZ")
    rets = {}
    for sym in universe + [bench]:
        # t0 is inside a session and t1 <= its close, so only regular-session bars can be selected
        rets[sym] = window_returns(fetch_bars(sym, "1Min", start, end, cfg), t0_ns, t1_ns)
    R = pd.DataFrame(rets, index=df.index)
    adj_all = R[universe].sub(R[bench], axis=0)  # market-adjusted return of every ticker over each signal's window
    df["raw"] = [R.at[i, t] if t in R.columns else np.nan for i, t in zip(df.index, df["ticker"])]
    df["adj"] = [adj_all.at[i, t] if t in adj_all.columns else np.nan for i, t in zip(df.index, df["ticker"])]
    df = df[df["adj"].notna()]
    funnel.append(("usable stock and SPY bars in the window (analyzed sample)", len(df)))
    for k, v in funnel:
        p(f"- {k}: {v}")
    df["fired_long"] = (df["status"] == "fired") & df["class_name"].isin(LONG)

    groups = [("all signals", df.index)] + [(c, df.index[df["class_name"] == c]) for c in CLASSES] \
        + [("fired Buy/Strong Buy", df.index[df["fired_long"]])]

    # ---------------- sample-size status ----------------
    fired = df[df["fired_long"]]
    n_fired_days = fired["day"].nunique()
    enough = n_fired_days >= MIN_DAYS and len(fired) >= MIN_FIRED
    p("\n## Sample-size status (Section 4 / Section 6)\n")
    p(f"- Trading days with >= 1 fired long signal: {n_fired_days} (need >= {MIN_DAYS}; 4a gates not applied, so an upper bound)")
    p(f"- Fired Buy/Strong Buy signals: {len(fired)} (need >= {MIN_FIRED})")
    p(f"- Analyzed trading days (any signal): {df['day'].nunique()}")
    p("- **Verdict: " + ("minimum sample reached for descriptive reading" if enough else
                          "TOO SMALL TO CONCLUDE ANYTHING. Every number below is descriptive only.") + "**")
    p(f"- Cells with fewer than {THIN_N} signals are flagged THIN.")

    # ---------------- (a) ----------------
    p("\n## (a) 2h returns: raw vs market-adjusted (stock minus SPY, same window)\n")
    p("Raw return:\n\n" + HDR)
    for name, idx in groups:
        p(row(name, summarize(df.loc[idx, "raw"], df.loc[idx, "day"], rng)))
    p("\nMarket-adjusted return:\n\n" + HDR)
    real = {}
    for name, idx in groups:
        s = summarize(df.loc[idx, "adj"], df.loc[idx, "day"], rng)
        real[name] = s
        p(row(name, s))

    # ---------------- (b) ----------------
    p(f"\n## (b) Random-ticker control ({N_DRAWS} draws, seed {SEED})\n")
    p("Each signal's return is replaced by the market-adjusted return of a ticker drawn uniformly from the other "
      "universe tickers with a valid return over the identical window. Percentile = share of draw means below "
      "the real day-clustered mean (ties half).\n")
    p("| group | n signals | n days | real mean | control median | control 2.5%..97.5% | real percentile | note |\n"
      "|---|---|---|---|---|---|---|---|")
    tick_pos = {t: j for j, t in enumerate(universe)}
    A = adj_all.loc[df.index, universe].values
    for name in ("all signals", "fired Buy/Strong Buy"):
        idx = dict(groups)[name]
        s = real[name]
        if s["n"] == 0:
            p(f"| {name} | 0 | 0 | n/a | n/a | n/a | n/a | |")
            continue
        rows_ = df.index.get_indexer(idx)
        own = np.array([tick_pos.get(t, -1) for t in df.loc[idx, "ticker"]])
        sub = A[rows_].copy()
        valid = ~np.isnan(sub)
        valid[np.arange(len(own)), own] = False  # never draw the signal's own ticker
        nvalid = valid.sum(axis=1)
        ok = nvalid > 0
        sub, valid, nvalid = sub[ok], valid[ok], nvalid[ok]
        order = np.argsort(~valid, axis=1, kind="stable")  # valid tickers first, per row
        w, _, _ = day_weights(df.loc[idx, "day"].values[ok])
        pick = np.floor(rng.random((N_DRAWS, len(nvalid))) * nvalid).astype(int)
        cols = order[np.arange(len(nvalid)), pick]
        draws = sub[np.arange(len(nvalid)), cols] @ w
        pctile = ((draws < s["dmean"]).sum() + 0.5 * (draws == s["dmean"]).sum()) / N_DRAWS
        flag = " THIN (n<30)" if s["n"] < THIN_N else ""
        p(f"| {name} | {s['n']} | {s['d']} | {pct(s['dmean'])} | {pct(np.median(draws))} | "
          f"{pct(np.percentile(draws, 2.5))}..{pct(np.percentile(draws, 97.5))} | {pctile * 100:.1f}th |{flag} |")
    p("\nThe fired Buy/Strong Buy percentile is the registered headline number for this section (descriptive, not a decision test).")

    # ---------------- (c) ----------------
    p("\n## (c) Breakdowns of market-adjusted return - EXPLORATORY\n")
    dstart = (pd.Timestamp(first) - pd.Timedelta(days=420)).strftime("%Y-%m-%d")
    dend = end  # regime uses strictly prior-day closes, so nothing past the last window is needed
    daily = {}
    for sym in sorted(set(df["ticker"])) + [bench]:
        b = fetch_bars(sym, "1Day", dstart, dend, cfg)
        b.index = b.index.tz_convert(ET).tz_localize(None).normalize()
        daily[sym] = b["c"]
    fcfg = cfg["features"]
    spy_up, vratio, mom = [], [], []
    for t, d in zip(df["ticker"], df["day"]):
        day = pd.Timestamp(d)
        sr_ = spy_regime_row(daily[bench], day, fcfg["sma_fast"], min(fcfg["sma_slow"], 200)) or {}
        tr_ = ticker_regime_row(daily[t], day, fcfg["vol_regime_short_days"], fcfg["vol_regime_long_days"]) or {}
        spy_up.append(sr_.get("spy_above_sma200", np.nan))
        vratio.append(tr_.get("vol_ratio_5d_40d", np.nan))
        mom.append(tr_.get("mom_5d", np.nan))
    df["reg_spy"] = pd.Series(spy_up, index=df.index).map({1: "SPY above SMA200", 0: "SPY below SMA200"}).fillna("SPY regime missing")
    vr = pd.Series(vratio, index=df.index)
    df["reg_vol"] = np.where(vr.isna(), "vol ratio missing", np.where(vr > 1, "vol expanding (ratio > 1)", "vol contracting (ratio <= 1)"))
    mm = pd.Series(mom, index=df.index)
    df["reg_mom"] = np.where(mm.isna(), "mom_5d missing", np.where(mm > 0, "mom_5d > 0", "mom_5d <= 0"))
    for gname in ("all signals", "fired Buy/Strong Buy"):
        gidx = dict(groups)[gname]
        p(f"\n### {gname}\n\n" + HDR)
        for col in ("reg_spy", "reg_vol", "reg_mom", "tod"):
            sub = df.loc[gidx]
            for val in sorted(sub[col].unique()):
                m = sub[sub[col] == val]
                p(row(val, summarize(m["adj"], m["day"], rng)))
    p("\nTime of day is of the decision time t0; last-2h windows are clipped at the close (shorter than 2h).")

    # ---------------- (d) ----------------
    p("\n## (d) Silent-Sell check - EXPLORATORY ONLY\n")
    p("Sell-class signals (logged, never acted on). Descriptive only: no short strategy, Sell suppression unchanged, no clock reset.\n")
    sell = df[df["class_name"] == "Sell"]
    s = summarize(sell["adj"], sell["day"], rng)
    p(HDR)
    p(row("Sell (all statuses)", s))
    neg = "n/a" if np.isnan(s["neg"]) else f"{s['neg'] * 100:.1f}%"
    p(f"\nShare of Sell signals with negative market-adjusted 2h return: {neg} (n={s['n']}, {s['d']} days)")

    p("\n## Reading notes\n")
    p("- Dozens of cells are shown; some will look 'significant' by chance. Any such cell is a hypothesis for a "
      "future pre-registered test on independent data, not a finding.")
    p("- Signals within the same ticker/15-min dedup group share overlapping windows; day-clustered CIs absorb "
      "within-day correlation but n signals overstates independent information.")


if __name__ == "__main__":
    main()
