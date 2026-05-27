"""
scraper/post_link_extractor.py — JNTUScrapTool Post Discovery
=============================================================
Extracts all post links and metadata from a parsed category/page soup.

This module handles the Tagdiv Composer theme used by jntufastupdates.com:
  - Primary:  .td-module-title a  (confirmed working)
  - Fallback: .entry-title a
  - Fallback: article h2 a / article h3 a
  - Fallback: all intra-domain anchors (filtered by link_router)

For each post it returns a PostLink with:
  title, url, university, category, semester, regulation, year

Usage:
    extractor = PostLinkExtractor(url_manager, dupe_checker, link_router)
    posts = extractor.extract(soup, page_url="https://...")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup, Tag

import config
from core.logger import get_logger
from core.url_manager import URLManager
from core.duplicate_checker import DuplicateChecker
from core.link_router import LinkRouter, RoutedLink, LinkType

log = get_logger("post_link_extractor", config.PHASE2_LOG)

# CSS selectors tried in priority order for finding post title anchors
POST_TITLE_SELECTORS = [
    ".td-module-title a",          # Tagdiv Composer — primary (confirmed)
    ".entry-title a",              # Standard WordPress
    "h2.entry-title a",
    "h3.entry-title a",
    ".td-image-container a",       # Tagdiv image-linked title (fallback)
    "article h2 a",
    "article h3 a",
    ".post-title a",
    ".tdb-title-wrap a",
]


@dataclass
class PostLink:
    """Represents a single scraped post with metadata."""
    title:      str
    url:        str
    university: Optional[str] = None
    category:   Optional[str] = None
    semester:   Optional[str] = None
    regulation: Optional[str] = None
    year:       Optional[str] = None
    degree:     Optional[str] = None
    page_source: Optional[str] = None   # URL of the page this was found on


class PostLinkExtractor:
    """
    Extracts all post links from a BeautifulSoup page object.

    Tries multiple CSS selector strategies (Tagdiv → WordPress fallbacks
    → catch-all intra-domain scan) and deduplicates results.

    Attributes:
        url_mgr   (URLManager):      For normalising hrefs.
        dedup     (DuplicateChecker): To avoid re-processing seen URLs.
        router    (LinkRouter):       To validate and enrich each link.
    """

    def __init__(
        self,
        url_mgr:  URLManager,
        dedup:    DuplicateChecker,
        router:   LinkRouter,
    ) -> None:
        self.url_mgr = url_mgr
        self.dedup   = dedup
        self.router  = router

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def extract(
        self,
        soup: BeautifulSoup,
        page_url: str = "",
    ) -> list[PostLink]:
        """
        Extract all post links visible on this page soup.

        Strategy:
          1. Try each POST_TITLE_SELECTOR in order — use the first that yields results.
          2. If nothing found, fall back to scanning ALL anchors on the page
             and filtering through link_router for POST type.

        Args:
            soup:     Parsed HTML of the page.
            page_url: URL of the page (used for context in logs).

        Returns:
            List of unique PostLink objects found on this page.
        """
        posts: list[PostLink] = []

        # ── Strategy 1: CSS selector scan ────────────────────
        anchors = self._try_selectors(soup)

        # ── Strategy 2: Full-page anchor fallback ─────────────
        if not anchors:
            log.debug("[%s] No posts via CSS selectors — trying full scan.", page_url)
            anchors = self._full_page_scan(soup)

        # ── Process each anchor ───────────────────────────────
        for a in anchors:
            post = self._process_anchor(a, page_url)
            if post:
                posts.append(post)

        log.info("[%s] Extracted %d post(s).", page_url, len(posts))
        return posts

    def extract_category_links(
        self,
        soup: BeautifulSoup,
        page_url: str = "",
    ) -> list[RoutedLink]:
        """
        Extract links that are CATEGORY or NESTED_CATEGORY type —
        used by category_scraper to discover sub-pages to recurse into.

        Args:
            soup:     Parsed HTML.
            page_url: URL for logging context.

        Returns:
            List of RoutedLink objects with CATEGORY or NESTED_CATEGORY type.
        """
        result: list[RoutedLink] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href  = a.get("href", "")
            url   = self.url_mgr.normalise(href)
            if not url or not self.url_mgr.is_jntu_url(url):
                continue
            if url in seen:
                continue
            seen.add(url)

            routed = self.router.classify(url)
            if self.router.should_recurse(routed):
                result.append(routed)

        log.debug("[%s] Found %d category/sub-category links.", page_url, len(result))
        return result

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    def _try_selectors(self, soup: BeautifulSoup) -> list[Tag]:
        """Try each CSS selector; return anchors from the first that matches."""
        for selector in POST_TITLE_SELECTORS:
            tags = soup.select(selector)
            if tags:
                log.debug("Post anchors found via selector '%s' (%d).", selector, len(tags))
                return tags
        return []

    def _full_page_scan(self, soup: BeautifulSoup) -> list[Tag]:
        """
        Collect ALL anchors on the page and let _process_anchor
        filter via link_router (only POSTs survive).
        """
        return soup.find_all("a", href=True)

    def _process_anchor(self, a: Tag, page_url: str) -> Optional[PostLink]:
        """
        Process a single anchor tag into a PostLink, or return None if:
          - URL is invalid / external
          - URL is not a POST type
          - URL has been seen before
          - Title is empty

        Args:
            a:        BeautifulSoup <a> Tag.
            page_url: Source page URL (for logging).

        Returns:
            PostLink, or None.
        """
        href  = a.get("href", "")
        url   = self.url_mgr.normalise(href)

        if not url or not self.url_mgr.is_jntu_url(url):
            return None

        routed = self.router.classify(url)
        if routed.link_type not in (LinkType.POST, LinkType.NESTED_CATEGORY):
            return None

        # Deduplication — skip already-seen URLs
        if not self.dedup.is_new_url(url):
            return None

        # Title — from anchor text; skip if empty
        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            return None

        return PostLink(
            title=title,
            url=url,
            university=routed.university,
            category=routed.category,
            semester=routed.semester,
            regulation=routed.regulation,
            year=routed.year,
            degree=routed.degree,
            page_source=page_url,
        )
