"""
core/link_classifier.py — JNTUScrapTool Post-Page Link Classifier
=================================================================
Classifies every anchor link found on a post or file page into:
  - DOWNLOAD_BUTTON : wpdm-download-link / data-downloadurl present
  - FILE_PAGE       : files.jntufastupdates.com/download/* URL
  - DIRECT_PDF      : .pdf extension URL
  - NESTED_POST     : same domain post URL (not a category)
  - EXTERNAL_FILE   : Google Drive, Docs, Mediafire, OneDrive, etc.
  - IGNORE          : Navigation, footer, social, ad links

Used by post_scraper and file_page_scraper to decide what to do with
every anchor on the page.

Usage:
    from core.link_classifier import LinkClassifier, LinkKind
    clf = LinkClassifier()
    kind, url, text = clf.classify_anchor(a_tag, base_url)
    # classify_all now returns dict mapping LinkKind → list of (url, anchor_text) tuples
"""

from __future__ import annotations

from enum import Enum
from urllib.parse import urlparse

from bs4 import Tag

import config
from core.logger import get_logger
from core.url_manager import URLManager

log = get_logger("link_classifier", config.PHASE3_LOG)

# External file-host domains
_EXTERNAL_FILE_HOSTS = {
    "drive.google.com",
    "docs.google.com",
    "mediafire.com",
    "onedrive.live.com",
    "1drv.ms",
    "dropbox.com",
    "mega.nz",
    "bit.ly",      # Often redirect to PDFs
    "tinyurl.com",
}

# Anchor text signals for download buttons
_DOWNLOAD_TEXTS = frozenset([
    "download", "click here", "get pdf", "get here", "download here",
    "download now", "open", "view pdf", "download pdf", "get file",
    "click to download", "download file",
])

# Navigation/footer anchor text to ignore (exact match after lower-strip)
_IGNORE_TEXTS = frozenset([
    "home", "about us", "contact us", "contact", "disclaimer",
    "privacy & policy", "privacy policy", "terms and conditions",
    "sitemap", "skip to content", "cancel reply", "jfu files",
    "main menu", "next", "previous", "older posts", "newer posts",
])

# URL slug segments that indicate utility/nav pages — skip these posts entirely
NAV_SLUGS = frozenset([
    "about-us", "contact-us", "disclaimer", "privacy-policy",
    "terms-conditions", "sitemap", "advertise", "write-for-us",
    "jntu-kakinada", "jntu-hyderabad", "jntu-anantapur", "jntu-vizianagaram",
    "anu-latest-updates",
])


class LinkKind(str, Enum):
    DOWNLOAD_BUTTON = "download_button"   # Confirmed download CTA
    FILE_PAGE       = "file_page"          # files.jntufastupdates.com/download/
    DIRECT_PDF      = "direct_pdf"         # Ends in .pdf
    NESTED_POST     = "nested_post"        # Same domain, non-category post
    EXTERNAL_FILE   = "external_file"      # Google Drive / Mediafire etc.
    IGNORE          = "ignore"             # Nav, footer, ads


class LinkClassifier:
    """
    Classifies <a> tags found on post and file pages.

    Call classify_anchor() for each anchor; the result tells the scraper
    exactly what to do with that link.

    classify_all() now returns:
        dict[LinkKind, list[tuple[str, str]]]
    where each value is a list of (url, anchor_text) tuples.
    Anchor text is the stripped text of the <a> element, useful for
    deriving subject names on Type C (multi-subject) posts.
    """

    def __init__(self) -> None:
        self.url_mgr = URLManager()

    def classify_anchor(self, a: Tag, page_url: str = "") -> tuple[LinkKind, str, str]:
        """
        Classify a single <a> tag.

        Args:
            a:        BeautifulSoup <a> Tag.
            page_url: URL of the page containing this anchor (for context).

        Returns:
            Tuple of (LinkKind, resolved_url, anchor_text).
            resolved_url is '' if the link should be ignored.
            anchor_text is the stripped display text of the anchor.
        """
        href      = a.get("href", "")
        text      = a.get_text(strip=True)
        text_low  = text.lower()
        classes   = " ".join(a.get("class", []))
        data_url  = a.get("data-downloadurl", "")

        # ── 1. WPDM download button (confirmed pattern) ──────
        if "wpdm-download-link" in classes or "download-on-click" in classes:
            target = data_url or self.url_mgr.normalise(href)
            log.debug("DOWNLOAD_BUTTON: %s", target[:80])
            return LinkKind.DOWNLOAD_BUTTON, target, text

        if data_url:
            return LinkKind.DOWNLOAD_BUTTON, data_url, text

        # ── 2. Resolve URL ────────────────────────────────────
        url = self.url_mgr.normalise(href)
        if not url:
            return LinkKind.IGNORE, "", ""

        # ── 3. Direct PDF ──────────────────────────────────────
        if url.lower().endswith(".pdf"):
            return LinkKind.DIRECT_PDF, url, text

        host = urlparse(url).netloc.lower()

        # ── 4. External file host ─────────────────────────────
        for ext_host in _EXTERNAL_FILE_HOSTS:
            if ext_host in host:
                return LinkKind.EXTERNAL_FILE, url, text

        # ── 5. File page (files subdomain) ────────────────────
        if self.url_mgr.is_file_host_url(url):
            if "/download/" in url:
                return LinkKind.FILE_PAGE, url, text
            return LinkKind.IGNORE, "", ""

        # ── 6. Download-text CTA on same domain ───────────────
        if text_low in _DOWNLOAD_TEXTS and self.url_mgr.is_jntu_url(url):
            # Could be a file page or a post — classify by URL
            return LinkKind.FILE_PAGE, url, text

        # ── 7. Ignore navigation/footer ───────────────────────
        if text_low in _IGNORE_TEXTS:
            return LinkKind.IGNORE, "", ""

        # ── 8. Skip known nav-page slug patterns ──────────────
        slug = self.url_mgr.get_slug(url)
        if slug in NAV_SLUGS:
            return LinkKind.IGNORE, "", ""

        # ── 9. Nested post (same main domain, not category) ───
        if self.url_mgr.is_jntu_url(url) and "jntufastupdates.com" in host:
            slug_parts = self.url_mgr.get_path_segments(url)
            if slug_parts and slug_parts[0] not in ("category", "tag", "author", "page"):
                return LinkKind.NESTED_POST, url, text

        return LinkKind.IGNORE, "", ""

    def classify_all(
        self,
        soup,
        page_url: str = "",
        content_area=None,
    ) -> dict[LinkKind, list[tuple[str, str]]]:
        """
        Classify all anchors in `content_area` (or full soup if None).

        Returns a dict mapping:
            LinkKind → list of (url, anchor_text) tuples

        Using the full soup as fallback is intentional: jntufastupdates.com
        wraps content in Tagdiv/VC composer divs that are separate from
        the semantic content area, so the full-page scan is needed.

        Args:
            soup:         Full page soup (used as root if content_area is None).
            page_url:     Source URL for logging.
            content_area: Narrower soup element to scan (optional).
        """
        # Strategy: scan content_area first; if it yields nothing useful,
        # fall back to the full soup. This gives us the best of both worlds.
        results = self._scan(content_area, page_url) if content_area is not None else None

        has_useful = results and any(
            results[k] for k in (LinkKind.FILE_PAGE, LinkKind.DIRECT_PDF,
                                  LinkKind.EXTERNAL_FILE, LinkKind.DOWNLOAD_BUTTON,
                                  LinkKind.NESTED_POST)
        )

        if not has_useful:
            # Fall back to full page scan
            results = self._scan(soup, page_url)

        return results  # type: ignore[return-value]

    def _scan(self, root, page_url: str) -> dict[LinkKind, list[tuple[str, str]]]:
        """Internal scanner: returns dict[LinkKind, list[tuple[url, text]]]."""
        output: dict[LinkKind, list[tuple[str, str]]] = {kind: [] for kind in LinkKind}
        seen: set[str] = set()

        for a in root.find_all("a", href=True):
            kind, url, text = self.classify_anchor(a, page_url)
            if url and url not in seen:
                seen.add(url)
                output[kind].append((url, text))

        return output
