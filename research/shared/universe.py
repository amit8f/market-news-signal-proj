"""IWM N-PORT snapshot parsing, ticker resolution, and liquidity filtering.

Resolution order (fixed after the v1 bug where OpenFIGI silently fell back to a foreign
listing when no genuine US-exchange row existed): N-PORT `identifiers` (always empty for a US
security - documented, not a bug, just adds nothing over the CUSIP itself), then DERA
quarterly-filing name match (same-period, so it still resolves companies later delisted or
acquired), then OpenFIGI restricted to `exchCode=US` in the request itself - never falls back
to a non-US row.
"""
import re
import time
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import requests

from research.shared.env import sec_headers

_NS = {"n": "http://www.sec.gov/edgar/nport"}

_SUFFIXES = [
    r"\bINC\b\.?", r"\bINCORPORATED\b", r"\bCORP\b\.?", r"\bCORPORATION\b", r"\bCO\b\.?",
    r"\bCOMPANY\b", r"\bLTD\b\.?", r"\bLIMITED\b", r"\bLLC\b", r"\bLP\b\.?", r"\bPLC\b",
    r"\bTHE\b", r"/DE/", r"/MD/", r"/NEW/", r"/VA/",
]


def normalize_name(s):
    s = str(s).upper()
    s = re.sub(r"[.,'&]", " ", s)
    for pat in _SUFFIXES:
        s = re.sub(pat, " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def find_fund_cik_series(ticker, mf_tickers_url="https://www.sec.gov/files/company_tickers_mf.json"):
    """Looks up a fund/ETF ticker (e.g. 'IWM') in EDGAR's mutual-fund tickers file, returning
    (cik, series_id, class_id). Fund tickers are not in company_tickers.json (equity issuers
    only)."""
    r = requests.get(mf_tickers_url, headers=sec_headers(), timeout=30)
    r.raise_for_status()
    d = r.json()
    for row in d["data"]:
        cik, series_id, class_id, symbol = row
        if symbol == ticker:
            return cik, series_id, class_id
    return None, None, None


def find_nport_filing(cik, series_id, as_of_date):
    """Returns the most recent N-PORT-P filing for `series_id` that was public (filed) on or
    before `as_of_date`, as {"accession": ..., "filing_date": ..., "index_url": ...}. Browsing
    by series ID (not CIK) filters to the one fund within a large umbrella registrant."""
    r = requests.get(
        "https://www.sec.gov/cgi-bin/browse-edgar",
        headers=sec_headers(),
        params={"action": "getcompany", "CIK": series_id, "type": "NPORT-P", "dateb": "",
                "owner": "include", "count": "100", "output": "atom"},
        timeout=40,
    )
    r.raise_for_status()
    entries = re.findall(
        r"<filing-date>(.*?)</filing-date>.*?<filing-href>(.*?)</filing-href>.*?<filing-type>(.*?)</filing-type>",
        r.text, re.S,
    )
    as_of = pd.Timestamp(as_of_date)
    candidates = [(d, href) for d, href, ftype in entries if ftype == "NPORT-P" and pd.Timestamp(d) <= as_of]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    filing_date, index_url = candidates[0]
    accession = index_url.rstrip("/").split("/")[-1].replace("-index.htm", "")
    cik_num = re.search(r"/data/(\d+)/", index_url).group(1)
    xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession.replace('-', '')}/primary_doc.xml"
    return {"accession": accession, "filing_date": filing_date, "xml_url": xml_url}


def parse_nport_holdings(xml_bytes_or_path):
    """Parses an N-PORT-P primary_doc.xml into a DataFrame of holdings with columns: name,
    cusip, valUSD, balance, pctVal, assetCat, price (=valUSD/balance). Also returns
    (report_period_date, filed_report_end) from genInfo."""
    tree = ET.parse(xml_bytes_or_path) if isinstance(xml_bytes_or_path, str) else ET.ElementTree(ET.fromstring(xml_bytes_or_path))
    root = tree.getroot()
    gen = root.find(".//n:genInfo", _NS)
    rep_pd_date = gen.findtext("n:repPdDate", namespaces=_NS) if gen is not None else None
    rows = []
    for inv in root.findall(".//n:invstOrSec", _NS):
        d = {}
        for child in inv:
            tag = child.tag.split("}")[-1]
            if tag in ("name", "cusip", "valUSD", "pctVal", "assetCat", "balance"):
                d[tag] = child.text
        rows.append(d)
    df = pd.DataFrame(rows)
    for c in ("valUSD", "pctVal", "balance"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["price"] = df["valUSD"] / df["balance"]
    return df, rep_pd_date


def load_dera_name_lookup(dera_submission_frames):
    """`dera_submission_frames`: list of SUBMISSION DataFrames (one per quarter) each with
    ISSUERCIK/ISSUERNAME/ISSUERTRADINGSYMBOL. Returns a normalized-name -> (cik, ticker) lookup,
    deduped, tickers with exchange prefixes (e.g. 'NYSE/TRN') and comma-joined dual tickers
    cleaned to the primary symbol."""
    dera = pd.concat(dera_submission_frames, ignore_index=True).drop_duplicates(subset=["ISSUERCIK"])
    dera = dera[dera["ISSUERTRADINGSYMBOL"].notna() & (dera["ISSUERTRADINGSYMBOL"] != "NONE")].copy()
    dera["name_norm"] = dera["ISSUERNAME"].map(normalize_name)

    def clean_ticker(s):
        s = str(s).strip()
        m = re.match(r"^(NYSE|NASDAQ|NYSEAMERICAN|NYSE AMERICAN|OTC|OTCMKTS)\s*[:/]\s*(.+)$", s, re.IGNORECASE)
        if m:
            s = m.group(2).strip()
        return s.split(",")[0].strip()

    dera["ticker_clean"] = dera["ISSUERTRADINGSYMBOL"].map(clean_ticker)
    dera = dera[~dera["ticker_clean"].str.contains("/", na=False)]  # drop genuinely ambiguous (e.g. "MOGA/MOGB")
    return dera.drop_duplicates(subset="name_norm").set_index("name_norm")


def resolve_via_openfigi(cusips, batch_size=10, pace_sec=2.5, session=None):
    """OpenFIGI CUSIP mapping restricted to exchCode=US in the REQUEST itself (never falls
    back to a non-US row on a miss - a CUSIP with no genuine US listing returns 'No identifier
    found', which is the correct, honest answer). Returns {cusip: ticker or None}."""
    s = session or requests
    out = {}
    for i in range(0, len(cusips), batch_size):
        batch = cusips[i:i + batch_size]
        payload = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch]
        for attempt in range(4):
            r = s.post("https://api.openfigi.com/v3/mapping", json=payload,
                       headers={"Content-Type": "application/json"}, timeout=30)
            if r.status_code == 429:
                time.sleep(15)
                continue
            r.raise_for_status()
            resp = r.json()
            break
        else:
            resp = [{} for _ in batch]
        for cusip, item in zip(batch, resp):
            data = item.get("data", [])
            eqrows = [d for d in data if d.get("marketSector") == "Equity"]
            out[cusip] = (eqrows[0] if eqrows else (data[0] if data else {})).get("ticker")
        time.sleep(pace_sec)
    return out


def resolve_tickers(holdings_df, dera_lookup):
    """Resolution order: (1) N-PORT identifiers - skipped (documented no-op for US securities,
    ISIN is CUSIP-derived); (2) DERA name match; (3) OpenFIGI exchCode=US only, for whatever
    DERA didn't resolve. Returns holdings_df with resolved_ticker, method, cik columns; prints
    the funnel. Unresolved rows are left with resolved_ticker=NaN - dropped by the caller, not
    guessed at.
    """
    df = holdings_df.copy()
    df["name_norm"] = df["name"].map(normalize_name)
    df["dera_ticker"] = df["name_norm"].map(dera_lookup["ticker_clean"])
    df["dera_cik"] = df["name_norm"].map(dera_lookup["ISSUERCIK"])

    remaining = df[df["dera_ticker"].isna() & df["cusip"].notna()]
    figi_map = resolve_via_openfigi(remaining["cusip"].dropna().unique().tolist()) if len(remaining) else {}
    df["figi_ticker"] = df["cusip"].map(figi_map)

    df["resolved_ticker"] = df["dera_ticker"].fillna(df["figi_ticker"])
    df["method"] = np.where(df["dera_ticker"].notna(), "dera_name",
                    np.where(df["figi_ticker"].notna(), "openfigi_us", None))
    n_total = len(df)
    n_resolved = df["resolved_ticker"].notna().sum()
    print(f"[universe] resolved {n_resolved}/{n_total} equity holdings "
          f"(dera_name={int((df['method']=='dera_name').sum())}, openfigi_us={int((df['method']=='openfigi_us').sum())}, "
          f"unresolved={n_total - n_resolved})")
    return df


def apply_liquidity_filters(df, adv_by_ticker, min_price=1.0, min_adv=1_000_000):
    """Drops sub-`min_price` and sub-`min_adv` (SIP ADV, must be pre-computed and passed in via
    `adv_by_ticker`), then dedupes dual share classes down to one row per resolved ticker."""
    df = df[df["resolved_ticker"].notna()].copy()
    n0 = len(df)
    df["ticker_primary"] = df["resolved_ticker"].str.replace("/", ".", regex=False)
    df = df[df["price"] >= min_price]
    n1 = len(df)
    df["adv_usd"] = df["ticker_primary"].map(adv_by_ticker)
    df = df[df["adv_usd"].notna() & (df["adv_usd"] >= min_adv)]
    n2 = len(df)
    df = df.drop_duplicates(subset="ticker_primary", keep="first")
    n3 = len(df)
    print(f"[universe] price>={min_price}: {n1}/{n0} | ADV>={min_adv}: {n2}/{n1} | dual-class deduped: {n3}/{n2}")
    return df.reset_index(drop=True)
