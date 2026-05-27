"""
core/duplicate_checker.py — JNTUScrapTool Deduplication Engine
===============================================================
Tracks seen URLs and titles in memory + optional log file so that
every scraper module can avoid processing the same resource twice.

Features:
  - URL-based deduplication (canonical hash)
  - Title-based deduplication (normalised lowercase)
  - Logging of every duplicate to logs/duplicate_links.log
  - Persistence: can dump/load seen-set to/from JSON

Usage:
    from core.duplicate_checker import DuplicateChecker
    dc = DuplicateChecker()
    if dc.is_new_url(url):
        process(url)
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import config
from core.logger import get_logger

log = get_logger("duplicate_checker", config.DUPLICATE_LOG)


class DuplicateChecker:
    """
    Maintains a set of seen URL hashes and normalised titles.
    Thread-safe for single-threaded use; wrap with a lock for multi-threaded.

    Attributes:
        _seen_urls  (set[str]): MD5 hashes of canonicalised URLs.
        _seen_titles(set[str]): Normalised title strings.
    """

    def __init__(self) -> None:
        self._seen_urls:   set[str] = set()
        self._seen_titles: set[str] = set()

    # ══════════════════════════════════════════════════════════
    # URL DEDUPLICATION
    # ══════════════════════════════════════════════════════════

    def is_new_url(self, url: str) -> bool:
        """
        Return True if this URL has NOT been seen before, and register it.
        Return False (and log) if it is a duplicate.

        Args:
            url: Normalised absolute URL.

        Returns:
            True = brand-new URL, safe to process.
            False = duplicate, skip.
        """
        key = self._url_hash(url)
        if key in self._seen_urls:
            log.debug("DUPLICATE URL: %s", url)
            return False
        self._seen_urls.add(key)
        return True

    def mark_url(self, url: str) -> None:
        """Mark a URL as seen without checking (for pre-loading known URLs)."""
        self._seen_urls.add(self._url_hash(url))

    # ══════════════════════════════════════════════════════════
    # TITLE DEDUPLICATION
    # ══════════════════════════════════════════════════════════

    def is_new_title(self, title: str) -> bool:
        """
        Return True if this title (case/space normalised) hasn't been seen.

        Args:
            title: Raw post title string.

        Returns:
            True = new title, False = duplicate.
        """
        key = self._normalise_title(title)
        if not key:
            return True     # empty / junk titles are always accepted
        if key in self._seen_titles:
            log.debug("DUPLICATE TITLE: %s", title)
            return False
        self._seen_titles.add(key)
        return True

    # ══════════════════════════════════════════════════════════
    # PERSISTENCE
    # ══════════════════════════════════════════════════════════

    def dump(self, path: Path) -> None:
        """
        Save the current seen-sets to a JSON file for resumable scraping.

        Args:
            path: File path to write (e.g. exports/seen_urls.json).
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "seen_urls":   list(self._seen_urls),
            "seen_titles": list(self._seen_titles),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        log.info("DuplicateChecker state saved → %s (%d URLs, %d titles)",
                 path, len(self._seen_urls), len(self._seen_titles))

    def load(self, path: Path) -> None:
        """
        Restore a previously saved seen-set so scraping can be resumed.

        Args:
            path: JSON file previously written by dump().
        """
        if not path.exists():
            log.debug("No saved dedup state at %s — starting fresh.", path)
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._seen_urls   = set(data.get("seen_urls", []))
        self._seen_titles = set(data.get("seen_titles", []))
        log.info("DuplicateChecker state loaded — %d URLs, %d titles",
                 len(self._seen_urls), len(self._seen_titles))

    # ══════════════════════════════════════════════════════════
    # STATS
    # ══════════════════════════════════════════════════════════

    @property
    def url_count(self) -> int:
        """Number of unique URLs registered so far."""
        return len(self._seen_urls)

    @property
    def title_count(self) -> int:
        """Number of unique titles registered so far."""
        return len(self._seen_titles)

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _url_hash(url: str) -> str:
        """MD5 hash of a stripped lowercase URL."""
        return hashlib.md5(url.strip().lower().encode()).hexdigest()

    @staticmethod
    def _normalise_title(title: str) -> str:
        """Lowercase + collapse whitespace + strip punctuation from title."""
        t = title.lower().strip()
        t = re.sub(r"[^a-z0-9\s]", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t
