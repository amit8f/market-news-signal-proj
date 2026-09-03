import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_config(path=None):
    load_dotenv(ROOT / ".env")
    cfg_path = Path(path) if path else ROOT / "config" / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for env_key, cfg_key in [
        ("FINNHUB_API_KEY", "finnhub_api_key"),
        ("ALPACA_API_KEY_ID", "alpaca_key_id"),
        ("ALPACA_API_SECRET_KEY", "alpaca_secret_key"),
    ]:
        val = os.environ.get(env_key)
        if not val:
            raise RuntimeError(f"Missing required environment variable: {env_key}")
        cfg[cfg_key] = val
    return cfg


def redact_secrets(text):
    """Masks any live secret value (Finnhub/Alpaca/Telegram) that might appear in an
    exception's message or URL, so it's safe to print or persist (e.g. to poll_failures)."""
    text = str(text)
    for env_key in ("FINNHUB_API_KEY", "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "TELEGRAM_BOT_TOKEN"):
        val = os.environ.get(env_key)
        if val:
            text = text.replace(val, f"***REDACTED_{env_key}***")
    return text


def raw_news_dir():
    return ROOT / "data" / "raw" / "news"


def raw_bars_dir():
    return ROOT / "data" / "raw" / "bars"


def calendar_path():
    return ROOT / "data" / "raw" / "calendar.csv"


def processed_dir():
    d = ROOT / "data" / "processed"
    d.mkdir(parents=True, exist_ok=True)
    return d


def outputs_dir():
    d = ROOT / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d
