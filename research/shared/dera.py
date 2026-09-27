"""SEC DERA quarterly Insider Transactions Data Set (Form 3/4/5) download and event
construction: code-P open-market purchases only, Form 4/A amendments excluded, one event per
filing (multiple P lines summed), with role/size/cluster/10b5-1 classification.
"""
import io
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from research.shared.env import sec_headers

DERA_LISTING_URL = "https://www.sec.gov/dera/data/form-345"


def list_available_quarters():
    """Scrapes the DERA data-sets page for available {year}q{n}_form345.zip links, returning
    {"2024q1": url, ...} sorted ascending."""
    r = requests.get(DERA_LISTING_URL, headers=sec_headers(), timeout=30)
    r.raise_for_status()
    links = re.findall(r'href="(/files/[^"]+?/([0-9]{4}q[1-4])_form345\.zip)"', r.text)
    out = {q: f"https://www.sec.gov{path}" for path, q in links}
    return dict(sorted(out.items()))


def quarters_between(start_quarter, end_quarter, available):
    keys = sorted(available.keys())
    return [q for q in keys if start_quarter <= q <= end_quarter]


def download_quarter(quarter, url, dest_dir):
    dest = Path(dest_dir) / f"form345_{quarter}"
    if dest.exists():
        return dest
    r = requests.get(url, headers=sec_headers(), timeout=90)
    r.raise_for_status()
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(dest)
    return dest


def load_submission(quarter_dir):
    return pd.read_csv(Path(quarter_dir) / "SUBMISSION.tsv", sep="\t", usecols=[
        "ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DOCUMENT_TYPE",
        "ISSUERCIK", "ISSUERNAME", "ISSUERTRADINGSYMBOL", "AFF10B5ONE",
    ])


def load_nonderiv_trans(quarter_dir):
    return pd.read_csv(Path(quarter_dir) / "NONDERIV_TRANS.tsv", sep="\t", usecols=[
        "ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE",
    ])


def load_reportingowner(quarter_dir):
    return pd.read_csv(Path(quarter_dir) / "REPORTINGOWNER.tsv", sep="\t", usecols=[
        "ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE",
    ])


def _classify_role(titles, relationships):
    t = " ".join(str(x).upper() for x in titles if pd.notna(x))
    r = " ".join(str(x) for x in relationships if pd.notna(x))
    if "CEO" in t or "CHIEF EXECUTIVE" in t or "CFO" in t or "CHIEF FINANCIAL" in t:
        return "CEO_CFO"
    if "Director" in r:
        return "Director"
    return "Other"


def _size_bucket(x):
    if x < 50_000:
        return "<$50k"
    if x < 500_000:
        return "$50k-$500k"
    return ">$500k"


def build_purchase_events(quarter_dirs, cik_to_ticker, universe_of=None, cluster_window_days=30):
    """Scans each quarter directory in `quarter_dirs` for code-P transactions on the target
    CIKs (keys of `cik_to_ticker`), excluding Form 4/A amendments, aggregating one event per
    filing (accession number) with dollar amount summed across P lines. `universe_of(ticker)`
    optionally tags each event's universe label (e.g. "large_40"/"small_100"). Returns a
    DataFrame with role/size_bucket/is_cluster/is_10b5_1 classification and a diagnostics
    dict of per-quarter candidate/P-line counts."""
    target_ciks = set(cik_to_ticker.keys())
    p_line_frames = []
    ro_frames = []
    diag = {}
    for q, qdir in quarter_dirs.items():
        sub = load_submission(qdir)
        sub = sub[sub["ISSUERCIK"].isin(target_ciks) & (sub["DOCUMENT_TYPE"] == "4")]
        if len(sub) == 0:
            diag[q] = dict(candidates=0, p_lines=0, filings=0)
            continue
        nd = load_nonderiv_trans(qdir)
        nd = nd[nd["ACCESSION_NUMBER"].isin(sub["ACCESSION_NUMBER"]) & (nd["TRANS_CODE"] == "P")]
        diag[q] = dict(candidates=len(sub), p_lines=len(nd), filings=nd["ACCESSION_NUMBER"].nunique())
        if len(nd) == 0:
            continue
        p_line_frames.append(nd.merge(sub, on="ACCESSION_NUMBER", how="left"))
        ro = load_reportingowner(qdir)
        ro_frames.append(ro[ro["ACCESSION_NUMBER"].isin(nd["ACCESSION_NUMBER"])])

    if not p_line_frames:
        return pd.DataFrame(), diag

    p_lines = pd.concat(p_line_frames, ignore_index=True)
    p_lines["dollar_amt"] = p_lines["TRANS_SHARES"] * p_lines["TRANS_PRICEPERSHARE"]
    ro_all = pd.concat(ro_frames, ignore_index=True) if ro_frames else pd.DataFrame(columns=["ACCESSION_NUMBER"])

    events = p_lines.groupby("ACCESSION_NUMBER").agg(
        FILING_DATE=("FILING_DATE", "first"), ISSUERCIK=("ISSUERCIK", "first"),
        AFF10B5ONE=("AFF10B5ONE", "first"), dollar_amt=("dollar_amt", "sum"),
        n_p_lines=("TRANS_CODE", "count"),
    ).reset_index()
    events["ticker"] = events["ISSUERCIK"].map(cik_to_ticker)
    events["is_10b5_1"] = events["AFF10B5ONE"].astype(str).str.lower().isin(["1", "true"])
    events["size_bucket"] = events["dollar_amt"].map(_size_bucket)
    events["FILING_DATE"] = pd.to_datetime(events["FILING_DATE"])
    if universe_of is not None:
        events["universe"] = events["ticker"].map(universe_of)

    role_map, owners_map = {}, {}
    for acc, grp in ro_all.groupby("ACCESSION_NUMBER"):
        role_map[acc] = _classify_role(grp["RPTOWNER_TITLE"], grp["RPTOWNER_RELATIONSHIP"])
        owners_map[acc] = tuple(sorted(grp["RPTOWNERCIK"].dropna().unique()))
    events["role"] = events["ACCESSION_NUMBER"].map(role_map)
    events["owner_ciks"] = events["ACCESSION_NUMBER"].map(owners_map)

    events = events.sort_values(["ISSUERCIK", "FILING_DATE"]).reset_index(drop=True)
    win = pd.Timedelta(days=cluster_window_days)
    cluster_flags = []
    for _, row in events.iterrows():
        w = events[(events["ISSUERCIK"] == row["ISSUERCIK"]) &
                   (events["FILING_DATE"] >= row["FILING_DATE"] - win) &
                   (events["FILING_DATE"] <= row["FILING_DATE"] + win)]
        distinct = set()
        for owners in w["owner_ciks"]:
            distinct.update(owners)
        cluster_flags.append(len(distinct) >= 2)
    events["is_cluster"] = cluster_flags
    return events, diag
