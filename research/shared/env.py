"""Shared environment loading for research scripts that call SEC EDGAR."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def sec_headers():
    """SEC's fair-access policy requires a real contact (name + email) in the User-Agent on
    every request, or it will rate-limit/block the caller - see
    https://www.sec.gov/os/webmaster-faq#developers. Reads SEC_USER_AGENT from .env; raises
    rather than silently sending a placeholder contact."""
    load_dotenv(ROOT / ".env")
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError(
            "Missing required environment variable: SEC_USER_AGENT. Add a line like "
            'SEC_USER_AGENT="Your Name your-email@example.com" to .env before running anything '
            "that calls SEC EDGAR."
        )
    return {"User-Agent": ua}
