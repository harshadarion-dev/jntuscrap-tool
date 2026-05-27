"""
scraper/pagination_scraper.py — JNTUScrapTool Pagination Engine
===============================================================
Detects and crawls all pages of a paginated WordPress category listing.

Supports multiple pagination patterns used by jntufastupdates.com:
  - WordPress standard /page/N/ URL pattern (primary)
  - Next-page anchor link (rel="next" or text "Next")
  - Tagdiv "td-pb-padding-side" pagination block
  - Numbered page links

Usage:
    pager = PaginationScraper(session, url_manager, logger)
    all_soups = pager.get_all_pages(start_url, first_soup)
"""

from __future__ import annotations

import re
import time
from typing import Iterator

from bs4 import BeautifulSoup

import config
from core.logger import get_logger
from core.session_manager import SessionManager
from core.url_manager import URLManager

log = get_logger("pagination_scraper", config.PAGINATION_ERRORS_LOG)

# CSS selectors for pagination containers (tried in order)
PAGINATION_SELECTORS = [
    # Tagdiv composer
    ".td-pb-padding-side .pages",
    ".td-pb-padding-side",
    ".td-load-more-wrap",
    ".td-ajax-pagination",
    # WordPress standard
    ".page-numbers",
    ".nav-links",
    "nav.navigation",
    ".pagination",
    # Generic
    "[class*='paginat']",
    ".wp-pagenavi",
]

# Text patterns that indicate a "Next page" link
_NEXT_TEXT = re.compile(r"^\s*(next|›|»|next\s*page)\s*$", re.I)

# Max pages to crawl per category (safety cap)
MAX_PAGES = 50


class PaginationScraper:
    """
    Crawls all paginated pages of a category URL.

    Responsible for:
      - Detecting whether a page has pagination
      - Building page URLs (WordPress /page/N/ pattern)
      - Following next-page links as fallback
      - Stopping when the last page is reached or MAX_PAGES is hit

    Attributes:
        session (SessionManager): Shared HTTP session.
        url_mgr (URLManager):     For URL normalisation and pagination URLs.
    """

    def __init__(self, session: SessionManager, url_mgr: URLManager) -> None:
        self.session = session
        self.url_mgr = url_mgr

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def get_all_pages(
        self,
        base_url: str,
        first_soup: BeautifulSoup,
    ) -> list[BeautifulSoup]:
        """
        Return BeautifulSoup objects for ALL pages of this category.

        Strategy:
          1. Check if page 1 has a pagination block → detect max page number.
          2. Build /page/N/ URLs and fetch each.
          3. If no numbered pagination, follow next-page links iteratively.
          4. Stop at MAX_PAGES or when a page yields no new posts.

        Args:
            base_url:   The base category URL (page 1).
            first_soup: Already-fetched BeautifulSoup for page 1.

        Returns:
            List of BeautifulSoup objects (page 1 is index 0).
        """
        soups = [first_soup]

        # ── Try numbered pagination first ─────────────────────
        max_page = self._detect_max_page(first_soup)

        if max_page and max_page > 1:
            log.info("[%s] Detected %d pages — crawling via /page/N/.", base_url, max_page)
            for page_num in range(2, min(max_page + 1, MAX_PAGES + 1)):
                soup = self._fetch_page(base_url, page_num)
                if soup:
                    soups.append(soup)
        else:
            # ── Fallback: follow next-page links ──────────────
            log.info("[%s] No numbered pagination — following next-page links.", base_url)
            soups.extend(self._follow_next_links(base_url, first_soup))

        log.info("[%s] Total pages crawled: %d", base_url, len(soups))
        return soups

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    def _detect_max_page(self, soup: BeautifulSoup) -> int | None:
        """
        Find the highest page number in a pagination block.

        Looks for numeric anchors like:
          <a href=".../page/5/">5</a>

        Returns:
            Max page number, or None if no numbered pagination found.
        """
        for selector in PAGINATION_SELECTORS:
            container = soup.select_one(selector)
            if not container:
                continue

            page_numbers: list[int] = []
            for a in container.find_all("a", href=True):
                text = a.get_text(strip=True)
                # Match "/page/N/" in href
                m = re.search(r"/page/(\d+)/", a["href"])
                if m:
                    page_numbers.append(int(m.group(1)))
                # Also try numeric anchor text
                elif text.isdigit():
                    page_numbers.append(int(text))

            if page_numbers:
                max_p = max(page_numbers)
                log.debug("Pagination block found — max page = %d.", max_p)
                return max_p

        return None

    def _fetch_page(self, base_url: str, page_num: int) -> BeautifulSoup | None:
        """
        Fetch a single /page/N/ URL and return parsed soup.
        Returns None on failure (already logged).

        Args:
            base_url: Category base URL.
            page_num: Page number ≥ 2.
        """
        url = self.url_mgr.paginated_url(base_url, page_num)
        try:
            response = self.session.get(url)
            # WordPress returns 404 when page exceeds total — stop there
            if response.status_code == 404:
                log.debug("Page %d returned 404 — stopping pagination.", page_num)
                return None
            response.raise_for_status()
            log.debug("Fetched page %d: %s", page_num, url)
            return BeautifulSoup(response.text, "lxml")
        except Exception as exc:
            log.warning("Failed to fetch page %d of %s: %s", page_num, base_url, exc)
            return None

    def _follow_next_links(
        self,
        base_url: str,
        first_soup: BeautifulSoup,
    ) -> list[BeautifulSoup]:
        """
        Follow 'Next' anchor links iteratively until no next-page link exists.
        Useful when the pagination block is missing but next/prev links exist.

        Args:
            base_url:   Category base URL (for de-loop protection).
            first_soup: Page 1 soup (already fetched).

        Returns:
            List of soups for pages 2, 3, ... (not including page 1).
        """
        soups: list[BeautifulSoup] = []
        current_soup = first_soup
        visited: set[str] = {base_url}
        page_count = 1

        while page_count < MAX_PAGES:
            next_url = self._find_next_link(current_soup, base_url)
            if not next_url or next_url in visited:
                break

            visited.add(next_url)
            try:
                response = self.session.get(next_url)
                if response.status_code == 404:
                    break
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "lxml")
                soups.append(soup)
                current_soup = soup
                page_count += 1
                log.debug("Next-page link: %s", next_url)
            except Exception as exc:
                log.warning("Failed to follow next-page link %s: %s", next_url, exc)
                break

        return soups

    def _find_next_link(
        self,
        soup: BeautifulSoup,
        base_url: str,
    ) -> str | None:
        """
        Locate the 'Next' or '›' pagination anchor on a page.

        Returns:
            Absolute URL of the next page, or None.
        """
        # Try rel="next" first (canonical)
        rel_next = soup.find("a", rel="next")
        if rel_next and rel_next.get("href"):
            return self.url_mgr.normalise(rel_next["href"])

        # Try text-based next links in pagination containers
        for selector in PAGINATION_SELECTORS:
            container = soup.select_one(selector)
            if not container:
                continue
            for a in container.find_all("a", href=True):
                text = a.get_text(strip=True)
                if _NEXT_TEXT.match(text):
                    url = self.url_mgr.normalise(a["href"])
                    if url:
                        return url

        return None
