"""Ad hoc tests (no pytest in this project - see CLAUDE.md) for the BarCache corporate-action
handling: splits get a full re-fetch when the cache spans across them; spin-offs (which
adjustment=split cannot correct for) suppress the ticker instead; a handled action is not
reprocessed on a later check within the lookback window.
Run: .venv\\Scripts\\python.exe scripts\\test_barcache_split_refetch.py
"""
import sys
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from news_signal.config import raw_bars_dir
from news_signal.labels.forward_returns import build_sessions
import news_signal.live.run_loop as run_loop

TICKER = "TESTSPLIT"
EX_DATE = "2026-06-29"


def _write_pre_event_cache(ticker, price_level=200.0):
    path = raw_bars_dir() / f"{ticker}_1min.csv"
    idx = pd.date_range("2026-06-20T13:30:00Z", "2026-06-26T20:00:00Z", freq="1min", tz="UTC")
    idx = idx[(idx.hour >= 13) & (idx.hour < 20)]
    price = price_level + np.linspace(0, 2, len(idx))
    df = pd.DataFrame(
        {"open": price, "high": price + 0.1, "low": price - 0.1, "close": price,
         "volume": 1000, "trade_count": 10, "vwap": price},
        index=idx,
    )
    df.to_csv(path)
    return path


def _fake_fetch_bars_smooth(ticker, timeframe, start, end, cfg):
    # include a bar right up to "now" (not just the end DATE, which loses time-of-day) so
    # BarCache.get()'s own independent staleness check doesn't trigger a second, unrelated
    # fetch on a later call within the same test - that would be a test-harness artifact,
    # not something the corporate-action fix under test is responsible for.
    idx = pd.date_range(pd.Timestamp(start), run_loop.utcnow(), freq="1min")
    idx = idx[((idx.hour >= 13) & (idx.hour < 20)) | (idx == idx[-1])]
    price = 100.0 + np.linspace(0, 5, len(idx))
    return pd.DataFrame(
        {"open": price, "high": price + 0.1, "low": price - 0.1, "close": price,
         "volume": 1000, "trade_count": 10, "vwap": price},
        index=idx,
    )


def cleanup():
    p = raw_bars_dir() / f"{TICKER}_1min.csv"
    if p.exists():
        p.unlink()
    reg = run_loop._ca_registry_path()
    if reg.exists():
        reg.unlink()


def test_split_triggers_refetch():
    print("\n=== test 1: split -> full re-fetch, no fake jump ===")
    cleanup()
    path = _write_pre_event_cache(TICKER)
    sessions = build_sessions(ROOT / "data" / "raw" / "calendar.csv")
    cache = run_loop.BarCache(sessions)

    with mock.patch.object(run_loop, "fetch_corporate_actions",
                            return_value=[{"ex_date": EX_DATE, "type": "reverse_split"}]), \
         mock.patch.object(run_loop, "_fetch_bars", side_effect=_fake_fetch_bars_smooth):
        result = cache.get(TICKER, lookback_days=75)

    assert len(result) > 0, "expected the re-fetch to populate bars"
    day_close = result["close"].groupby(result.index.normalize()).last()
    max_move = day_close.pct_change().dropna().abs().max()
    print(f"  largest single-day move after refetch: {max_move*100:.2f}%")
    assert max_move < 0.20, f"FAKE JUMP STILL PRESENT: {max_move*100:.2f}%"
    print("  [PASS] no fake jump - cache was fully re-fetched")


def test_split_not_reprocessed_on_second_run():
    """Isolates _maybe_handle_corporate_actions() directly (rather than the full get(), which
    has its own ordinary, real-time/session-hours-dependent staleness refresh unrelated to
    this fix) to test issue 2 precisely: once an action is recorded as handled, a later check
    within the lookback window must not delete the cache again."""
    print("\n=== test 2: a handled split is not reprocessed (deleted again) on a later check ===")
    cleanup()
    path = _write_pre_event_cache(TICKER)  # still spans pre-ex_date, as a real post-refetch cache would NOT
    sessions = build_sessions(ROOT / "data" / "raw" / "calendar.csv")
    action = {"ex_date": EX_DATE, "type": "reverse_split"}

    with mock.patch.object(run_loop, "fetch_corporate_actions", return_value=[action]):
        cache1 = run_loop.BarCache(sessions)
        cache1._maybe_handle_corporate_actions(TICKER, path)
        assert not path.exists(), "expected the first check to delete the cache (spans across ex_date)"
        print("  run 1: cache deleted (correct - first time this action is seen)")

        # rewrite the cache (simulating get()'s own refetch immediately following the deletion) -
        # a real post-refetch cache legitimately spans across ex_date again, correctly this time
        _write_pre_event_cache(TICKER)

        # a fresh BarCache instance, as main() creates once per process start - simulates the
        # next day's process, same action still inside the (now 30-day) lookback window
        cache2 = run_loop.BarCache(sessions)
        cache2._maybe_handle_corporate_actions(TICKER, path)

    assert path.exists(), "the already-handled action triggered a repeat deletion"
    print("  run 2: cache NOT deleted (correct - action already recorded as handled)")
    print("  [PASS] no repeat refetch for an already-handled action")


def test_spinoff_suppresses_then_lifts():
    print("\n=== test 3: spin-off -> suppression active in-window, lifted after ===")
    cleanup()
    sessions = build_sessions(ROOT / "data" / "raw" / "calendar.csv")
    ticker = "TESTSPINOFF"
    action = {"ex_date": EX_DATE, "type": "spin_off"}

    with mock.patch.object(run_loop, "fetch_corporate_actions", return_value=[action]):
        cache = run_loop.BarCache(sessions)
        cache._maybe_handle_corporate_actions(ticker, raw_bars_dir() / f"{ticker}_1min.csv")

    cutoff = run_loop.corporate_action_suppressed_until(ticker, sessions)
    assert cutoff is not None, "expected a suppression cutoff to be recorded for the spin-off"
    print(f"  suppression cutoff: {cutoff}")

    sess_starts = sessions["sess_start"].values.astype("datetime64[ns]")
    ex_idx = int(np.searchsorted(sess_starts, np.datetime64(EX_DATE), side="left"))

    ts_inside = pd.Timestamp(sess_starts[ex_idx + 5]).tz_localize("UTC")  # 5 trading days after ex_date
    ts_after = pd.Timestamp(sess_starts[min(ex_idx + 61, len(sess_starts) - 1)]).tz_localize("UTC")  # 61 trading days after

    assert ts_inside < cutoff, "expected suppression to be ACTIVE 5 trading days after the spin-off"
    print(f"  {ts_inside.date()} (5 trading days after ex_date): suppressed = True  [correct]")
    assert not (ts_after < cutoff), "expected suppression to be LIFTED 61 trading days after the spin-off"
    print(f"  {ts_after.date()} (61 trading days after ex_date): suppressed = False  [correct]")

    reg = run_loop._load_ca_registry()
    assert reg.get(ticker) == [action], "expected the spin-off to be recorded in the registry"
    print("  [PASS] suppression window matches CA_SUPPRESSION_TRADING_DAYS, action recorded in registry")

    # spin-offs must never trigger a deletion/refetch of the ticker's own cache (there usually
    # isn't one for a brand-new ticker, but confirm no fetch_bars call is attempted either)
    p = raw_bars_dir() / f"{ticker}_1min.csv"
    assert not p.exists(), "spin-off handling should not have written/refetched a bar file"
    cleanup()
    if p.exists():
        p.unlink()
    reg_path = run_loop._ca_registry_path()
    if reg_path.exists():
        reg_path.unlink()


if __name__ == "__main__":
    try:
        test_split_triggers_refetch()
        test_split_not_reprocessed_on_second_run()
        test_spinoff_suppresses_then_lifts()
        print("\nALL TESTS PASSED")
    finally:
        cleanup()
