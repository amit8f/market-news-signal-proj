"""Entry/exit/beta/forward-return engine shared by the Form 4 studies (and reusable by a
later whole-market project). Construction: entry = close of the first bar strictly after the
anchor date; exit = N trading bars later; beta = OLS slope vs SPY over the 250 trading days
strictly before the anchor; a >15-calendar-day gap between remaining bars (after the
zero-volume filter already applied in bars.to_frames) is treated like a delisting - the
forward lookup is capped there, not jumped across.
"""
import numpy as np
import pandas as pd
from scipy import stats as st

HORIZONS = (5, 20, 60)
GAP_DAYS = 15


def compute_beta(bars_by_ticker, spy_ret, ticker, anchor_date, window=250, min_days=30):
    if ticker not in bars_by_ticker:
        return None, 0
    tb = bars_by_ticker[ticker]
    hist = tb.loc[tb.index < anchor_date].tail(window)
    if len(hist) < min_days:
        return None, len(hist)
    tr = hist["c"].pct_change()
    common = tr.index.intersection(spy_ret.index)
    tr_a, sr_a = tr.loc[common].dropna(), spy_ret.loc[common].dropna()
    c2 = tr_a.index.intersection(sr_a.index)
    if len(c2) < min_days:
        return None, len(c2)
    x, y = sr_a.loc[c2].values, tr_a.loc[c2].values
    if np.std(x) == 0:
        return None, len(c2)
    return float(np.cov(x, y)[0, 1] / np.var(x)), len(c2)


def compute_event_return(bars_by_ticker, spy, spy_ret, ticker, anchor_date, horizons=HORIZONS):
    """Returns None if there's no tradable bar after `anchor_date`. Otherwise a dict with
    entry_date/entry_price/beta/beta_n and, per horizon h: ret_{h}d, spy_ret_{h}d,
    adj_ret_{h}d, truncated_{h}d (True if the horizon ran into a delisting/halt-gap and the
    return is measured to the last available price instead)."""
    if ticker not in bars_by_ticker:
        return None
    tb = bars_by_ticker[ticker]
    after = tb.loc[tb.index > anchor_date]
    if len(after) == 0:
        return None
    entry_date = after.index[0]
    entry_idx = tb.index.get_loc(entry_date)
    entry_price = float(tb["c"].iloc[entry_idx])
    beta, beta_n = compute_beta(bars_by_ticker, spy_ret, ticker, anchor_date)

    gap_days = tb.index.to_series().diff().dt.days
    g = gap_days[(gap_days > GAP_DAYS) & (tb.index > entry_date)]
    first_gap_idx = tb.index.get_loc(g.index[0]) - 1 if len(g) else None

    out = dict(entry_date=entry_date, entry_price=entry_price, beta=beta, beta_n=beta_n)
    for h in horizons:
        target_idx = entry_idx + h
        hit_gap = first_gap_idx is not None and target_idx > first_gap_idx
        truncated = (target_idx >= len(tb)) or hit_gap
        use_idx = first_gap_idx if hit_gap else min(target_idx, len(tb) - 1)
        exit_date = tb.index[use_idx]
        exit_price = float(tb["c"].iloc[use_idx])
        stock_ret = exit_price / entry_price - 1.0
        sw = spy.loc[(spy.index >= entry_date) & (spy.index <= exit_date)]
        spy_r = np.nan if len(sw) < 2 else float(sw["c"].iloc[-1] / sw["c"].iloc[0] - 1.0)
        adj = stock_ret - beta * spy_r if (beta is not None and not np.isnan(spy_r)) else np.nan
        out[f"ret_{h}d"] = stock_ret
        out[f"spy_ret_{h}d"] = spy_r
        out[f"adj_ret_{h}d"] = adj
        out[f"truncated_{h}d"] = truncated
    return out


def score_events(events_df, bars_by_ticker, spy, spy_ret, anchor_col="FILING_DATE", horizons=HORIZONS):
    rows = []
    for _, ev in events_df.iterrows():
        r = compute_event_return(bars_by_ticker, spy, spy_ret, ev["ticker"], pd.Timestamp(ev[anchor_col]).normalize(), horizons)
        if r is None:
            continue
        r.update(ev.to_dict())
        rows.append(r)
    return pd.DataFrame(rows)


def build_eligible_population(tickers, bars_by_ticker, spy, spy_ret, event_dates_by_ticker,
                               window_start, window_end, exclusion_days=30, horizons=HORIZONS):
    """Every ticker-day's forward return (all horizons), for `tickers`, restricted to
    [window_start, window_end], with an `eligible` flag marking days outside +/-`exclusion_days`
    of any purchase-filing date for that ticker (event_dates_by_ticker: {ticker: [dates]}).
    Vectorised (per ticker) rather than looping compute_event_return row by row - validate
    against compute_event_return on a sample before trusting at scale."""
    frames = []
    for t in tickers:
        if t not in bars_by_ticker:
            continue
        c = bars_by_ticker[t]["c"]
        idx = c.index
        pos = pd.Series(idx, index=idx)
        gap = idx.to_series().diff().dt.days
        row = {"ticker": t, "date": idx}
        for h in horizons:
            entry, exit_ = pos.shift(-1), pos.shift(-(h + 1))
            ret = c.shift(-(h + 1)) / c.shift(-1) - 1
            spy_h = pd.Series(
                spy["c"].reindex(exit_.values).values / spy["c"].reindex(entry.values).values - 1, index=idx
            )
            dr = c.pct_change()
            sr = spy_ret.reindex(idx)
            beta = (dr.rolling(250, min_periods=100).cov(sr) / sr.rolling(250, min_periods=100).var()).shift(1)
            adj = ret - beta * spy_h
            bad = (gap.rolling(h + 1).max().shift(-(h + 1)) > GAP_DAYS).fillna(False)
            adj = adj.where(~bad)
            row[f"adj_ret_{h}d"] = adj.values
        frames.append(pd.DataFrame(row))
    pop = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(pop) == 0:
        return pop
    pop = pop[(pop["date"] >= pd.Timestamp(window_start)) & (pop["date"] <= pd.Timestamp(window_end))]
    excl = pd.Timedelta(days=exclusion_days)
    pop["eligible"] = True
    for t, dates in event_dates_by_ticker.items():
        mask = pop["ticker"] == t
        ok = np.ones(mask.sum(), dtype=bool)
        sub_dates = pop.loc[mask, "date"].values
        for d in pd.to_datetime(dates):
            ok &= ~((sub_dates >= (d - excl).to_datetime64()) & (sub_dates <= (d + excl).to_datetime64()))
        pop.loc[mask, "eligible"] = ok
    return pop.dropna(subset=[f"adj_ret_{horizons[0]}d"]).reset_index(drop=True)


def vs_zero(df, col, month_col="month", n_boot=10000, seed=42):
    d = df.dropna(subset=[col])
    n = len(d)
    if n == 0:
        return dict(n=0)
    mm = d.groupby(month_col)[col].mean()
    M = len(mm)
    t = mm.mean() / (mm.std(ddof=1) / np.sqrt(M)) if M > 1 and mm.std(ddof=1) > 0 else np.nan
    rng = np.random.default_rng(seed)
    g = d.groupby(month_col)[col].agg(["sum", "count"])
    idx = rng.integers(0, M, size=(n_boot, M))
    s, c = g["sum"].values[idx].sum(axis=1), g["count"].values[idx].sum(axis=1)
    bm = s / c
    return dict(n=n, n_months=M, mean=d[col].mean(), median=d[col].median(), win=(d[col] > 0).mean(),
                t=t, lo=float(np.percentile(bm, 2.5)), hi=float(np.percentile(bm, 97.5)))


def month_clustered_diff_test(E_y, E_month, P_y, P_month, P_weight=None, n_boot=10000, seed=7):
    """Weighted least squares of y on an event indicator, standard errors clustered by
    calendar month (CR1 small-sample correction), plus a bootstrap 95% CI resampling calendar
    months. `P_weight` lets the population side be ticker-mix-matched (each ticker's eligible
    days weighted so they sum to that ticker's event count) - pass None for equal weight."""
    E_y, P_y = np.asarray(E_y, dtype=float), np.asarray(P_y, dtype=float)
    E_w = np.ones(len(E_y))
    P_w = np.ones(len(P_y)) if P_weight is None else np.asarray(P_weight, dtype=float)
    y = np.concatenate([E_y, P_y])
    D = np.concatenate([np.ones(len(E_y)), np.zeros(len(P_y))])
    w = np.concatenate([E_w, P_w])
    cl = np.concatenate([np.asarray(E_month), np.asarray(P_month)])
    X = np.column_stack([np.ones_like(D), D])
    XtWX_i = np.linalg.inv(X.T @ (X * w[:, None]))
    beta = XtWX_i @ (X.T @ (w * y))
    u = y - X @ beta
    groups = np.unique(cl)
    meat = np.zeros((2, 2))
    for g in groups:
        m = cl == g
        s = X[m].T @ (w[m] * u[m])
        meat += np.outer(s, s)
    G = len(groups)
    V = (G / (G - 1)) * XtWX_i @ meat @ XtWX_i
    se = float(np.sqrt(V[1, 1]))
    t = float(beta[1] / se)
    p = float(2 * (1 - st.t.cdf(abs(t), df=G - 1)))

    months = np.array(sorted(set(E_month) | set(P_month)))
    e = pd.DataFrame({"m": E_month, "y": E_y}).groupby("m")["y"].agg(["sum", "count"]).reindex(months).fillna(0)
    p_df = pd.DataFrame({"m": P_month, "wy": P_w * P_y, "w": P_w}).groupby("m")[["wy", "w"]].sum().reindex(months).fillna(0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(months), size=(n_boot, len(months)))
    es, ec = e["sum"].values[idx].sum(1), e["count"].values[idx].sum(1)
    pw, pwt = p_df["wy"].values[idx].sum(1), p_df["w"].values[idx].sum(1)
    ok = (ec > 0) & (pwt > 0)
    diffs = es[ok] / ec[ok] - pw[ok] / pwt[ok]
    return dict(nE=len(E_y), nP=len(P_y), G=G, meanE=float(E_y.mean()),
                meanP=float(np.average(P_y, weights=P_w)), diff=float(beta[1]), se=se, t=t, p=p,
                lo=float(np.percentile(diffs, 2.5)), hi=float(np.percentile(diffs, 97.5)))
