"""
scraper/nested_post_scraper.py — JNTUScrapTool Nested Post Resolver
===================================================================
Follows internal article links from a post page when the post doesn't
directly contain a file page URL. Recurses until a file page link or
download button is found.

Example flow:
  Post: /jntuk-1-1-1-2-academic-calendar-2025-26/
    ↓ Contains link to same-domain post:
  Nested: /some-nested-article/
    ↓ Contains files.jntufastupdates.com/download/ link

Usage:
    from scraper.nested_post_scraper import NestedPostScraper
    ns = NestedPostScraper(session, classifier, snapshot_mgr)
    triples = ns.resolve(nested_post_url, depth=1)
    # Returns list of (nested_url, file_page_url, anchor_text)
"""

from __future__ import annotations

from bs4 import BeautifulSoup

import config
from core.logger import get_logger
from core.session_manager import SessionManager
from core.link_classifier import LinkClassifier, LinkKind
from core.html_snapshot_manager import HTMLSnapshotManager
from core.url_manager import URLManager

log = get_logger("nested_post_scraper", config.NESTED_ERRORS_LOG)

# Maximum nesting depth (prevent infinite loops)
MAX_NESTED_DEPTH = 3

# Content area selectors
_CONTENT_SELECTORS = [
    ".td-pb-span8", ".td-post-content", ".entry-content",
    ".post-content", "article",
]


class NestedPostScraper:
    """
    Follows internal links from a post when no file page is found at the top level.

    This handles Type B posts:
      Main Post → Nested informational article → File page link

    Each resolved entry is a (nested_url, file_page_url, anchor_text) triple.
    anchor_text is the display text of the link that led to the file page,
    which often IS the subject name for Type C posts inside a nested article.
    """

    def __init__(
        self,
        session:      SessionManager,
        classifier:   LinkClassifier,
        snapshot_mgr: HTMLSnapshotManager,
        dedup:        set | None = None,
    ) -> None:
        self.session      = session
        self.classifier   = classifier
        self.snapshot_mgr = snapshot_mgr
        self.url_mgr      = URLManager()
        self._visited: set[str] = dedup if dedup is not None else set()

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def resolve(
        self,
        url:   str,
        depth: int = 1,
    ) -> list[tuple[str, str, str]]:
        """
        Follow a nested post URL and return all resolved triples.

        Args:
            url:   URL of a nested post page to visit.
            depth: Current recursion depth (stops at MAX_NESTED_DEPTH).

        Returns:
            List of (nested_url, file_page_url, anchor_text) tuples.
            anchor_text is the display text of the file-page anchor,
            useful for subject identification on Type C nested posts.
        """
        if depth > MAX_NESTED_DEPTH:
            log.debug("Max nested depth at %s — stopping.", url)
            return []

        if url in self._visited:
            return []
        self._visited.add(url)

        # ── Fetch ─────────────────────────────────────────────
        soup = self._fetch(url)
        if soup is None:
            return []

        # Save snapshot
        self.snapshot_mgr.save_nested(soup.prettify(), url)

        # ── Find content area ─────────────────────────────────
        content_el = None
        for sel in _CONTENT_SELECTORS:
            content_el = soup.select_one(sel)
            if content_el:
                break

        classified = self.classifier.classify_all(soup, url, content_el)

        results: list[tuple[str, str, str]] = []

        # ── Collect file page links ────────────────────────────
        for file_url, anchor_text in classified[LinkKind.FILE_PAGE]:
            if file_url not in self._visited:
                results.append((url, file_url, anchor_text))
                log.info("[depth=%d] Found file page: %s", depth, file_url)

        # ── Collect direct PDFs ───────────────────────────────
        for pdf_url, anchor_text in classified[LinkKind.DIRECT_PDF]:
            results.append((url, pdf_url, anchor_text))

        # ── Collect external files ────────────────────────────
        for ext_url, anchor_text in classified[LinkKind.EXTERNAL_FILE]:
            results.append((url, ext_url, anchor_text))

        # ── Recurse into nested posts if still no file found ──
        if not results:
            for nested_url, _ in classified[LinkKind.NESTED_POST]:
                sub_results = self.resolve(nested_url, depth=depth + 1)
                results.extend(sub_results)

        return results

    # ══════════════════════════════════════════════════════════
    # PRIVATE
    # ══════════════════════════════════════════════════════════

    def _fetch(self, url: str) -> BeautifulSoup | None:
        try:
            resp = self.session.get(url)
            if resp.status_code == 404:
                log.warning("404: %s", url)
                return None
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            log.error("Fetch error at %s: %s", url, exc)
            return None
