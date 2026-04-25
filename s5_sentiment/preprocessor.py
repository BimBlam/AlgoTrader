"""
Text preprocessor for S5.

Cleans raw news/social items before they are handed to the scorer.
Normalisation order matters: strip URLs first so ticker regex does not
accidentally match URL path segments.
"""

import re
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Compiled once at import time — re-use is critical when processing thousands
# of items per run.
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_NON_ASCII_RE = re.compile(r"[^\x00-\x7F]+")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")

# Cashtag prefix is optional; word boundaries prevent APPS matching APP etc.
def _build_ticker_pattern(ticker: str) -> re.Pattern:
    return re.compile(r"(?i)(?:\$)?\b" + re.escape(ticker) + r"\b")


def build_ticker_patterns(tickers: list[str]) -> dict[str, re.Pattern]:
    """
    Pre-compile one regex per ticker.

    Compiling outside the hot loop avoids re-compiling on every document.
    Patterns match bare tickers (AAPL) and cashtag forms ($AAPL).
    """
    return {t: _build_ticker_pattern(t) for t in tickers}


def clean_text(raw: str) -> str:
    """
    Strip URLs, remove non-ASCII noise, and collapse whitespace.

    Returns empty string if input is not a string — callers should skip
    empty results rather than passing them to the model.
    """
    if not isinstance(raw, str):
        return ""
    text = _URL_RE.sub(" ", raw)
    text = _NON_ASCII_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


def extract_ticker_mentions(
    text: str,
    ticker_patterns: dict[str, re.Pattern],
) -> list[str]:
    """
    Return the list of tickers mentioned in *text* (may contain duplicates).

    Duplicates are intentional: a document mentioning AAPL three times
    contributes three counts to raw_mentions, which feeds abn_attention.
    """
    mentions: list[str] = []
    for ticker, pattern in ticker_patterns.items():
        hits = pattern.findall(text)
        mentions.extend([ticker] * len(hits))
    return mentions


def preprocess_item(
    item: dict[str, Any],
    ticker_patterns: dict[str, re.Pattern],
) -> tuple[str, list[str]]:
    """
    Clean a single raw scrape record and identify the tickers it mentions.

    *item* is a dict produced by S2 scraper with at minimum a ``text`` key.
    Returns (cleaned_text, [mentioned_tickers]).
    """
    raw_text = item.get("text", "") or item.get("title", "") or ""
    # Combine title + body when both present; separator ensures the model
    # sees them as distinct segments rather than a run-on sentence.
    if "title" in item and "text" in item and item["title"] and item["text"]:
        raw_text = f"{item['title']}. {item['text']}"

    cleaned = clean_text(raw_text)
    tickers = extract_ticker_mentions(cleaned, ticker_patterns)
    return cleaned, tickers
