"""Alpaca corporate-actions inventory (splits, spin-offs) for a set of tickers over a date
range. Shared logic with (but independent of) the live system's BarCache fix
(news_signal/live/run_loop.py) - this module is for offline research bulk lookups, that one is
for the live loop's per-ticker daily check.
"""
import requests

CA_URL = "https://data.alpaca.markets/v1/corporate-actions"


def fetch_corporate_actions(tickers, start, end, headers, types=("forward_split", "reverse_split", "spin_off"), batch_size=20):
    """Returns a DataFrame with columns symbol, universe(caller-supplied via merge), ex_date,
    kind, new_rate, old_rate for all corporate actions of the given types among `tickers` in
    [start, end]."""
    import pandas as pd

    rows = []
    tickers = list(tickers)
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        page_token = None
        while True:
            params = {"symbols": ",".join(batch), "types": ",".join(types), "start": start, "end": end, "limit": 1000}
            if page_token:
                params["page_token"] = page_token
            r = requests.get(CA_URL, headers=headers, params=params, timeout=60)
            if r.status_code != 200:
                print(f"[corporate_actions] batch failed: {r.status_code} {r.text[:200]}")
                break
            payload = r.json()
            ca = payload.get("corporate_actions", {})
            for kind, entries in ca.items():
                action_type = kind[:-1] if kind.endswith("s") else kind
                for e in entries:
                    rows.append(dict(symbol=e.get("symbol"), ex_date=e.get("ex_date"), type=action_type,
                                      new_rate=e.get("new_rate"), old_rate=e.get("old_rate")))
            page_token = payload.get("next_page_token")
            if not page_token:
                break
    return pd.DataFrame(rows)
