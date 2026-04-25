"""
Raw text scraper — news and social.

Outputs (HDD per §4.1, spec §5.1 data_dir_hdd is the root):
  <data_dir_hdd>/raw/news/<DATE>.json
  <data_dir_hdd>/raw/social/<DATE>.json

Spec rule: never overwrite existing files — merge new items by
deduplication key (URL for news, post_id for Reddit posts).

All writes are atomic (tmp → rename) to prevent partial-write corruption.

Reddit credentials come from environment variables only:
  REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
"""

from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path

import praw
import yfinance as yf

from algotrader.shared.config_loader import AppConfig
from algotrader.shared.logger import get_logger

log = get_logger(__name__)

# [FIX] Pre-compiled word-boundary pattern for ticker mention detection.
_TICKER_DOLLAR = re.compile(r"\$([A-Z]{1,5})\b")
_TICKER_WORD = re.compile(r"\b([A-Z]{1,5})\b")


def scrape_news(
    tickers: list[str],
    cfg: AppConfig,
    today: datetime.date,
) -> Path:
    """
    Scrape Yahoo Finance news for all *tickers* and write/merge to HDD JSON.

    Skips silently if news.enabled is False in sentiment_params.yaml.
    Returns the output path regardless (path may not exist if disabled).
    """
    sources = cfg.sentiment.sources
    news_cfg = sources.get("news") if isinstance(sources, dict) else getattr(sources, "news", None)
    enabled = (
        news_cfg.get("enabled", False)
        if isinstance(news_cfg, dict)
        else getattr(news_cfg, "enabled", False)
    )

    out_path = _dated_path(cfg.system.data_dir_hdd, "news", today)

    if not enabled:
        log.info("s2.news.disabled")
        return out_path

    existing = _load_json_safe(out_path)
    new_items: list[dict] = []

    for ticker in tickers:
        try:
            items = yf.Ticker(ticker).news or []
            for item in items:
                new_items.append(
                    {
                        "ticker": ticker,
                        "source": "yahoo_finance",
                        "date": str(_unix_to_date(item.get("providerPublishTime", 0))),
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "publisher": item.get("publisher", ""),
                    }
                )
        except Exception as exc:
            log.warning("s2.news.ticker_error", ticker=ticker, error=str(exc))

    merged = _merge_by_url(existing, new_items)
    _write_json_safe(out_path, merged)
    log.info("s2.news.written", path=str(out_path), total_items=len(merged))
    return out_path


def scrape_social(
    tickers: list[str],
    cfg: AppConfig,
    today: datetime.date,
) -> Path:
    """
    Scrape Reddit posts mentioning *tickers* and write/merge to HDD JSON.

    Twitter raises NotImplementedError when enabled — the config default
    is twitter.enabled: false and must stay that way until implemented.
    """
    sources = cfg.sentiment.sources
    reddit_cfg = sources.get("reddit") if isinstance(sources, dict) else getattr(sources, "reddit", None)
    twitter_cfg = sources.get("twitter") if isinstance(sources, dict) else getattr(sources, "twitter", None)

    twitter_enabled = (
        twitter_cfg.get("enabled", False)
        if isinstance(twitter_cfg, dict)
        else getattr(twitter_cfg, "enabled", False)
    )
    if twitter_enabled:
        raise NotImplementedError(
            "Twitter scraping is not yet implemented. "
            "Set twitter.enabled: false in sentiment_params.yaml "
            "until a real implementation exists."
        )

    out_path = _dated_path(cfg.system.data_dir_hdd, "social", today)
    reddit_enabled = (
        reddit_cfg.get("enabled", False)
        if isinstance(reddit_cfg, dict)
        else getattr(reddit_cfg, "enabled", False)
    )

    if not reddit_enabled:
        log.info("s2.social.reddit_disabled")
        return out_path

    subreddits: list[str] = (
        reddit_cfg.get("subreddits", [])
        if isinstance(reddit_cfg, dict)
        else getattr(reddit_cfg, "subreddits", [])
    )
    ticker_set = set(tickers)
    reddit = _build_reddit_client()
    existing = _load_json_safe(out_path)
    new_items: list[dict] = []

    for sub_name in subreddits:
        try:
            for post in reddit.subreddit(sub_name).new(limit=200):
                post_date = datetime.datetime.utcfromtimestamp(post.created_utc).date()
                if post_date != today:
                    continue
                for ticker in _find_mentioned_tickers(post.title, ticker_set):
                    new_items.append(
                        {
                            "ticker": ticker,
                            "source": f"reddit/{sub_name}",
                            "date": str(post_date),
                            "title": post.title,
                            "url": f"https://reddit.com{post.permalink}",
                            "post_id": post.id,
                            "score": post.score,
                            "num_comments": post.num_comments,
                        }
                    )
        except Exception as exc:
            log.warning("s2.social.subreddit_error", subreddit=sub_name, error=str(exc))

    merged = _merge_by_post_id(existing, new_items)
    _write_json_safe(out_path, merged)
    log.info("s2.social.written", path=str(out_path), total_items=len(merged))
    return out_path


# ── Private helpers ──────────────────────────────────────────────────────────

def _dated_path(base: str, subdir: str, date: datetime.date) -> Path:
    """
    [FIX] data_dir_hdd is already the root — sub-path is raw/<subdir>/, not
    data/raw/<subdir>/. The spec §4.1 shows 'HDD (data/raw/)' as the full
    absolute path value of data_dir_hdd.
    """
    p = Path(base) / "raw" / subdir
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{date.isoformat()}.json"


def _load_json_safe(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("s2.json_load_error", path=str(path), error=str(exc))
        return []


def _write_json_safe(path: Path, items: list[dict]) -> None:
    """Atomic write via tmp file + os.replace to prevent partial-write corruption."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, default=str)
    tmp.replace(path)


def _merge_by_url(existing: list[dict], new_items: list[dict]) -> list[dict]:
    seen = {item["url"] for item in existing if item.get("url")}
    merged = list(existing)
    for item in new_items:
        if item.get("url") and item["url"] not in seen:
            merged.append(item)
            seen.add(item["url"])
    return merged


def _merge_by_post_id(existing: list[dict], new_items: list[dict]) -> list[dict]:
    seen = {item["post_id"] for item in existing if item.get("post_id")}
    merged = list(existing)
    for item in new_items:
        if item.get("post_id") and item["post_id"] not in seen:
            merged.append(item)
            seen.add(item["post_id"])
    return merged


def _unix_to_date(ts: int) -> datetime.date:
    return datetime.datetime.utcfromtimestamp(ts).date()


def _find_mentioned_tickers(text: str, ticker_set: set[str]) -> list[str]:
    """
    [FIX] Use word-boundary regex so tickers at sentence start/end and
    adjacent to punctuation are detected. Both $TICKER and bare TICKER forms.
    """
    text_upper = text.upper()
    found: set[str] = set()
    for m in _TICKER_DOLLAR.finditer(text_upper):
        if m.group(1) in ticker_set:
            found.add(m.group(1))
    for m in _TICKER_WORD.finditer(text_upper):
        if m.group(1) in ticker_set:
            found.add(m.group(1))
    return list(found)


def _build_reddit_client() -> praw.Reddit:
    """Credentials from env vars only — never from config files."""
    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "algotrader-s2/1.0")
    if not client_id or not client_secret:
        raise EnvironmentError(
            "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must be set "
            "as environment variables to enable Reddit scraping."
        )
    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        read_only=True,
    )
