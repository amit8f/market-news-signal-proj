import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

MIN_ACTIVE_DAYS = 40
MIN_FIRED_SIGNALS = 300


def wilson_ci(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5) / denom
    return (center - half, center + half)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "data" / "live" / "signals.db"))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    signals = pd.read_sql("SELECT * FROM signals", conn)
    outcomes = pd.read_sql("SELECT * FROM outcomes", conn)
    print("=" * 72)
    print(f"SHADOW STATUS - {datetime.now().isoformat(timespec='seconds')}")
    print(f"db: {args.db}")
    print("=" * 72)

    if len(signals) == 0:
        print("no signals collected yet")
        return

    ts = pd.to_datetime(signals["ts_utc"], utc=True)
    et_date = ts.dt.tz_convert("America/New_York").dt.date
    fired = signals[signals["status"] == "fired"]
    fired_et_dates = set(pd.to_datetime(fired["ts_utc"], utc=True).dt.tz_convert("America/New_York").dt.date)
    active_days = len([d for d in fired_et_dates])

    print("pipeline funnel:")
    for status, n in signals["status"].value_counts().items():
        print(f"  {status:<10} {n}")
    sup = signals[signals["status"] != "fired"]
    if len(sup):
        print("  suppress reasons:", dict(sup["suppress_reason"].value_counts()))

    by_class = fired["class_name"].value_counts()
    print("\nfired longs by class:")
    for cls, n in by_class.items():
        print(f"  {cls:<12} {n}")

    proxy_share = (fired["entry_source"] != "alpaca_trade").mean() if len(fired) else float("nan")
    first_ts, last_ts = ts.min(), ts.max()
    span_days = max((last_ts - first_ts).days, 0)

    print("\nminimum-sample gates (EVALUATION_PLAN.md section 4):")
    gate_days = "PASS" if active_days >= MIN_ACTIVE_DAYS else "not yet"
    gate_sig = "PASS" if len(fired) >= MIN_FIRED_SIGNALS else "not yet"
    print(f"  active trading days : {active_days:>5} / {MIN_ACTIVE_DAYS}   [{gate_days}]")
    print(f"  fired long signals  : {len(fired):>5} / {MIN_FIRED_SIGNALS}   [{gate_sig}]")
    print(f"  collection span     : {span_days} calendar days ({first_ts.date()} .. {last_ts.date()})")
    print(f"  proxy-entry share   : {proxy_share:.1%} (gate <20%)")

    print("\nticker poll failures (from news_signal.live.run_loop's poll_failures table):")
    has_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='poll_failures'"
    ).fetchone()
    if not has_table:
        print("  poll_failures table not present in this db (pre-dates failure tracking)")
    else:
        fails = pd.read_sql(
            "SELECT ticker, COUNT(*) AS n, MIN(ts_utc) AS first_seen, MAX(ts_utc) AS last_seen "
            "FROM poll_failures GROUP BY ticker ORDER BY n DESC",
            conn,
        )
        if len(fails) == 0:
            print("  none recorded")
        else:
            for _, r in fails.iterrows():
                print(f"  {r['ticker']:<12} {int(r['n']):>4} failures   first={r['first_seen']}  last={r['last_seen']}")

    if len(outcomes):
        merged = outcomes.merge(
            fired[["signal_id", "class_name"]], on="signal_id", how="left"
        )
        print("\npaper outcomes so far (NOT the formal test - descriptive only):")
        for cls, grp in merged.groupby("class_name"):
            r = grp["ret_net"].dropna()
            k = int((r > 0).sum())
            lo, hi = wilson_ci(k, len(r))
            print(
                f"  {cls:<12} n={len(r):>4}  win={k/len(r):.1%} (Wilson {lo:.0%}-{hi:.0%})"
                f"  mean_net={r.mean():+.4%}"
                f"  stop_rate={grp['stopped'].mean():.0%}"
            )
    else:
        print("\nno outcomes filled yet")

    print("\nformal day-clustered test: only at minimum sample; see EVALUATION_PLAN.md")


if __name__ == "__main__":
    sys.exit(main())
