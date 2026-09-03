import re

SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "plc",
    "ltd", "limited", "sa", "ag", "nv", "holdings", "group",
}

TIER_PRIMARY = 1
TIER_SECONDARY = 2
TIER_PASSING = 3


def _normalize(text):
    return re.sub(r"[^a-z0-9& ]+", " ", str(text).lower()).strip()


def name_variants(name):
    norm = _normalize(name)
    tokens = [t for t in norm.split() if t not in SUFFIXES and t != "&"]
    variants = set()
    if tokens:
        variants.add(" ".join(tokens))
        if len(tokens) >= 2:
            variants.add(" ".join(tokens[:2]))
        first = tokens[0]
        if len(first) >= 6:
            variants.add(first)
    return {v for v in variants if len(v) >= 3}


def build_matchers(universe, profiles):
    matchers = {}
    for row in universe:
        ticker = row["ticker"]
        profile = profiles.get(ticker, {})
        variants = name_variants(profile.get("name") or row.get("name", ""))
        patterns = [re.compile(rf"\b{re.escape(ticker)}\b", re.IGNORECASE)]
        for v in sorted(variants, key=len, reverse=True):
            patterns.append(re.compile(rf"\b{re.escape(v)}\b", re.IGNORECASE))
        matchers[ticker] = patterns
    return matchers


def relevance_tier(ticker, headline, summary, matchers):
    text_head = str(headline or "")
    text_sum = f"{headline or ''} {summary or ''}"
    for pat in matchers.get(ticker, []):
        if pat.search(text_head):
            return TIER_PRIMARY
    for pat in matchers.get(ticker, []):
        if pat.search(text_sum):
            return TIER_SECONDARY
    return TIER_PASSING


def tag_relevance(news_df, universe, profiles, strict_sources=None):
    matchers = build_matchers(universe, profiles)
    strict = set(strict_sources or [])

    def _tier(row):
        tier = relevance_tier(row["ticker"], row["headline"], row["summary"], matchers)
        if row["source"] in strict and tier > TIER_PRIMARY:
            return TIER_PASSING
        return tier

    out = news_df.copy()
    out["relevance_tier"] = out.apply(_tier, axis=1)
    return out


def filter_relevance(news_df, drop_non_primary=True):
    df = news_df.copy()
    counts = df["relevance_tier"].value_counts().to_dict()
    if drop_non_primary:
        df = df[df["relevance_tier"] < TIER_PASSING]
    return df.reset_index(drop=True), counts
