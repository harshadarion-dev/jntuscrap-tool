"""
scraper/navbar_extractor.py — JNTUScrapTool Navbar Extraction Engine
====================================================================
Parses the navigation HTML from the homepage and produces a structured
dictionary mapping:

    University → Category → URL

Also captures "shared" sections (e.g. JNTUK Materials) that don't belong
to a single university.

Output format (saved to exports/navbar_structure.json):
{
    "JNTUK": {
        "Academic Calendars": "https://...",
        "Question Papers":    "https://...",
        ...
    },
    "JNTUH": { ... },
    "JNTUA": { ... },
    "JNTUGV": { ... },
    "General": {
        "JNTUK Materials": "https://...",
        ...
    }
}
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse
from typing import Any

from bs4 import BeautifulSoup, Tag

import config
from core.logger import get_logger

log = get_logger("navbar_extractor", config.PHASE1_LOG)


class NavbarExtractor:
    """
    Extracts the full navigation hierarchy from a parsed homepage.

    The extractor walks every top-level menu item and its dropdown children,
    normalises URLs, deduplicates links, classifies each link by university
    and category, and returns a clean nested dictionary.

    Attributes:
        base_url (str): Used to resolve relative links.
        seen_urls (set[str]): Tracks already-seen URLs to avoid duplicates.
    """

    def __init__(self, base_url: str = config.BASE_URL) -> None:
        self.base_url  = base_url
        self.seen_urls: set[str] = set()

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def extract(self, soup: BeautifulSoup) -> dict[str, dict[str, str]]:
        """
        Main entry point.  Walk entire soup, find every nav link + dropdown.

        Args:
            soup: Parsed BeautifulSoup object of the full homepage.

        Returns:
            Nested dict: {university_or_group: {category_name: url}}
        """
        structure: dict[str, dict[str, str]] = {}

        # ── Locate nav elements ───────────────────────────────
        nav_elements = self._find_nav_elements(soup)

        if not nav_elements:
            log.warning("No nav elements found. Falling back to full-page link scan.")
            nav_elements = [soup]  # Scan the entire page

        # ── Walk each nav element ─────────────────────────────
        for nav in nav_elements:
            self._walk_nav(nav, structure)

        # ── Ensure all universities exist as keys ─────────────
        for uni in config.UNIVERSITIES:
            structure.setdefault(uni, {})

        structure.setdefault("General", {})

        total_links = sum(len(v) for v in structure.values())
        log.info(
            "Extraction complete. Universities: %d | Total links: %d",
            len([k for k in structure if k != "General"]),
            total_links,
        )

        if total_links == 0:
            log.warning(
                "No links extracted. Site structure may use JavaScript rendering. "
                "Check the snapshot: %s", config.HOMEPAGE_HTML
            )

        return structure

    # ────────────────────────────────────────────────────────
    def save_json(self, data: dict[str, Any]) -> None:
        """
        Serialise the extracted structure to JSON and write to
        config.NAVBAR_JSON.

        Args:
            data: The nested dict returned by extract().
        """
        config.NAVBAR_JSON.parent.mkdir(parents=True, exist_ok=True)

        with open(config.NAVBAR_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        log.info("navbar_structure.json saved → %s", config.NAVBAR_JSON)

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    def _find_nav_elements(self, soup: BeautifulSoup) -> list[Tag]:
        """
        Try every selector in config.NAVBAR_SELECTORS and return elements
        from the **first** selector that matches.

        Stopping at the first match prevents a less-specific fallback selector
        (e.g. '.menu') from overriding the confirmed site-specific selector.
        """
        for selector in config.NAVBAR_SELECTORS:
            elements = soup.select(selector)
            if elements:
                log.info(
                    "Navbar matched via selector '%s' — found %d element(s).",
                    selector, len(elements),
                )
                # De-duplicate by object id (in case selector returns duplicates)
                seen_ids: set[int] = set()
                unique: list[Tag] = []
                for el in elements:
                    if id(el) not in seen_ids:
                        seen_ids.add(id(el))
                        unique.append(el)
                return unique

        log.warning("No nav elements matched any selector. Will fall back to full-page scan.")
        return []

    # ────────────────────────────────────────────────────────
    def _walk_nav(
        self,
        nav: Tag,
        structure: dict[str, dict[str, str]],
    ) -> None:
        """
        Walk top-level <li> items in a nav element.
        For each item, detect dropdowns and classify links.

        Args:
            nav:       A nav/ul/div Tag to walk.
            structure: Output dict that is updated in-place.
        """
        # Top-level list items (direct children of nav or nested ul)
        top_items = nav.find_all("li", recursive=True)

        log.debug("Walking nav with %d <li> elements.", len(top_items))

        for li in top_items:
            # ── Get the first anchor in this <li> ─────────────
            anchor = li.find("a", recursive=False)
            if not anchor:
                anchor = li.find("a")
            if not anchor:
                continue

            href  = anchor.get("href", "")
            label = self._clean_name(anchor.get_text())

            if not label:
                continue

            url = self._normalize_url(href)

            # ── Classify the parent link ──────────────────────
            uni  = self._classify_university(label + " " + url)
            cat  = self._classify_category(label + " " + url)

            # ── Look for dropdown children ────────────────────
            sub_ul = li.find("ul")
            if sub_ul:
                # This li has a submenu — walk its children
                self._walk_submenu(sub_ul, structure, parent_uni=uni)
            else:
                # Leaf link — add it directly
                if url and url not in self.seen_urls:
                    self.seen_urls.add(url)
                    bucket    = uni or "General"
                    link_name = cat or label
                    structure.setdefault(bucket, {})[link_name] = url
                    log.debug("[%s] %s → %s", bucket, link_name, url)

    # ────────────────────────────────────────────────────────
    def _walk_submenu(
        self,
        ul: Tag,
        structure: dict[str, dict[str, str]],
        parent_uni: str | None,
    ) -> None:
        """
        Walk a dropdown <ul> and add each child link to structure.

        Args:
            ul:         The <ul> submenu tag.
            structure:  Output dict updated in-place.
            parent_uni: University inferred from the parent <li> label, if any.
        """
        for li in ul.find_all("li", recursive=False):
            anchor = li.find("a")
            if not anchor:
                continue

            href  = anchor.get("href", "")
            label = self._clean_name(anchor.get_text())

            if not label:
                continue

            url = self._normalize_url(href)

            if not url or url in self.seen_urls:
                continue

            self.seen_urls.add(url)

            # Re-classify using the child's label + URL (may override parent)
            uni = self._classify_university(label + " " + url) or parent_uni or "General"
            cat = self._classify_category(label + " " + url) or label

            structure.setdefault(uni, {})[cat] = url
            log.debug("[%s] %s → %s", uni, cat, url)

            # Recurse one more level (nested dropdowns)
            nested_ul = li.find("ul")
            if nested_ul:
                self._walk_submenu(nested_ul, structure, parent_uni=uni)

    # ────────────────────────────────────────────────────────
    def _normalize_url(self, href: str) -> str:
        """
        Convert relative URLs to absolute, strip fragments, skip empties.

        Args:
            href: Raw href attribute value.

        Returns:
            Absolute URL string, or empty string if invalid.
        """
        if not href or href in ("#", "javascript:;", "javascript:void(0)"):
            return ""

        # Already absolute?
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https"):
            return href.rstrip("/") + "/"

        # Relative — resolve against base URL
        full = urljoin(self.base_url, href)
        return full.rstrip("/") + "/"

    # ────────────────────────────────────────────────────────
    @staticmethod
    def _clean_name(text: str) -> str:
        """
        Normalise a menu label:
          - Strip whitespace
          - Collapse internal whitespace
          - Remove non-printable characters

        Args:
            text: Raw text content.

        Returns:
            Cleaned string, or empty string.
        """
        if not text:
            return ""
        # Collapse whitespace & strip
        name = re.sub(r"\s+", " ", text).strip()
        # Remove non-printable / control characters
        name = re.sub(r"[^\x20-\x7E\u00A0-\uFFFF]", "", name)
        return name

    # ────────────────────────────────────────────────────────
    @staticmethod
    def _classify_university(text: str) -> str | None:
        """
        Detect which university a link belongs to by scanning its
        combined label+URL string against config.UNIVERSITY_KEYWORDS.

        Returns the university code (e.g. "JNTUK") or None.
        """
        lower = text.lower()
        for keyword, code in config.UNIVERSITY_KEYWORDS.items():
            if keyword in lower:
                return code
        return None

    # ────────────────────────────────────────────────────────
    @staticmethod
    def _classify_category(text: str) -> str | None:
        """
        Detect the academic category from a link's label+URL string.

        Returns the category name (e.g. "Question Papers") or None.
        """
        lower = text.lower().replace(" ", "-")
        for keyword, category in config.CATEGORY_KEYWORDS.items():
            if keyword in lower:
                return category
        return None
