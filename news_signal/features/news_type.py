import re

PATTERNS = [
    ("earnings", r"\b(earnings|results|revenue|guidance|outlook|q[1-4]\b|fiscal|profit|beats? estimates|misses? estimates|eps\b|reports?\b)"),
    ("m&a", r"\b(acquir\w*|merger|merge[ds]?|takeover|buyout|to buy|acquisition|stake in|joint venture)"),
    ("regulatory", r"\b(sec |lawsuit|sues|fda|doj|antitrust|probe|investigation|fine[sd]?|settle(s|ment)?|recall|subpoena|regulator\w*|court )"),
    ("analyst", r"\b(upgrade[ds]?|downgrade[ds]?|price target|initiates? coverage|rating|overweight|underweight|buy rating|sell rating|neutral on|raises? pt)"),
    ("dividend_buyback", r"\b(dividend|buyback|repurchase|stock split)"),
    ("macro", r"\b(fed |fomc|inflation|cpi\b|ppi\b|jobs report|payrolls|rate cut|rate hike|interest rates?|treasury yields?|gdp\b|recession)"),
    ("product_business", r"\b(launch\w*|unveils?|partnership|contract|expansion|opens?|agreement|collaboration|new product|announces?)"),
]


def classify(headline, summary=""):
    text = f"{headline} {summary}".lower()
    for name, pat in PATTERNS:
        if re.search(pat, text):
            return name
    return "other"
