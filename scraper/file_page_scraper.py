"""
scraper/file_page_scraper.py — JNTUScrapTool File Page Extractor
================================================================
Visits a files.jntufastupdates.com/download/* page and extracts
the actual download URL from the `data-downloadurl` attribute on
the WPDM download button.

Confirmed page structure (from live inspection):
  <a class="wpdm-download-link download-on-click btn btn-primary"
     data-downloadurl="https://files.jntufastupdates.com/download/.../?wpdmdl=XXXX&..."
     href="#">Download</a>

Strategy order:
  1. WPDM data-downloadurl attribute (most reliable)
  2. Script-tag JSON scan (fallback for dynamically injected URLs)
  3. Full link classifier scan (catches non-WPDM patterns)
  4. Form action scan (rare fallback)

Also detects:
  - Direct .pdf links in page content
  - Google Drive / external file links
  - Multiple download entries (for multi-file pages)

Usage:
    fp = FilePageScraper(session, snapshot_mgr)
    result = fp.extract(file_page_url)
    print(result.download_url)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

import config
from core.logger import get_logger
from core.session_manager import SessionManager
from core.link_classifier import LinkClassifier, LinkKind
from core.html_snapshot_manager import HTMLSnapshotManager

log = get_logger("file_page_scraper", config.FILE_PAGE_ERRORS_LOG)


@dataclass
class FilePageResult:
    """Result extracted from one files.jntufastupdates.com page."""
    file_page_url:   str
    download_url:    Optional[str]   = None   # Primary WPDM direct download URL
    direct_pdf_url:  Optional[str]   = None   # .pdf anchor if found
    external_url:    Optional[str]   = None   # Google Drive / Mediafire
    title:           Optional[str]   = None   # Page H1/H2 title
    filename_hint:   Optional[str]   = None   # Derived from URL slug
    all_downloads:   list[str]       = field(default_factory=list)  # All WPDM URLs found
    error:           Optional[str]   = None


# CSS selectors for the WPDM download link (confirmed)
_WPDM_SELECTORS = [
    "a.wpdm-download-link",
    "a.download-on-click",
    "[data-downloadurl]",
]

# Content area selectors
_CONTENT_SELECTORS = [
    ".entry-content",
    ".post-content",
    "article",
    "main",
]

# Regex patterns to find download URLs in <script> tags
_JS_URL_PATTERNS = [
    re.compile(r'"downloadurl"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'"download_url"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'"fileurl"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'"file_url"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'wpdmurl\s*=\s*"([^"]+)"', re.I),
    re.compile(r"wpdmurl\s*=\s*'([^']+)'", re.I),
    re.compile(r'href\s*=\s*"(https://files\.jntufastupdates\.com/[^"]+)"', re.I),
]


class FilePageScraper:
    """
    Extracts the actual download URL from a WPDM file page.

    The site uses the WordPress Download Manager (WPDM) plugin.
    Download URLs are stored in data-downloadurl= on the button anchor
    and may include authentication tokens — we capture them as-is.
    """

    def __init__(
        self,
        session:     SessionManager,
        snapshot_mgr: HTMLSnapshotManager,
    ) -> None:
        self.session      = session
        self.snapshot_mgr = snapshot_mgr
        self.classifier   = LinkClassifier()

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def extract(self, file_page_url: str) -> FilePageResult:
        """
        Fetch a file page and extract download URL(s).

        Args:
            file_page_url: e.g. 'https://files.jntufastupdates.com/download/slug/'

        Returns:
            FilePageResult with download_url populated (or error set).
        """
        result = FilePageResult(file_page_url=file_page_url)

        # ── Fetch ─────────────────────────────────────────────
        try:
            resp = self.session.get(file_page_url)
            if resp.status_code == 404:
                result.error = "404_not_found"
                log.warning("404: %s", file_page_url)
                return result
            resp.raise_for_status()
        except Exception as exc:
            result.error = str(exc)
            log.error("Fetch failed for %s: %s", file_page_url, exc)
            return result

        # ── Save snapshot ─────────────────────────────────────
        self.snapshot_mgr.save_file_page(resp.text, file_page_url)

        soup = BeautifulSoup(resp.text, "lxml")

        # ── Extract title ─────────────────────────────────────
        title_el = soup.find("h1") or soup.find("h2")
        result.title = title_el.get_text(strip=True) if title_el else None

        # ── Filename hint from URL slug ───────────────────────
        parts = [p for p in file_page_url.rstrip("/").split("/") if p]
        result.filename_hint = parts[-1] if parts else None

        # ── Strategy 1: WPDM download button (primary) ────────
        wpdm_urls = self._extract_wpdm_urls(soup)
        if wpdm_urls:
            result.download_url   = wpdm_urls[0]
            result.all_downloads  = wpdm_urls
            log.info("WPDM download URL found: %s", result.download_url[:80])
            return result

        # ── Strategy 2: Script-tag JSON scan ──────────────────
        js_url = self._scan_scripts(soup)
        if js_url:
            result.download_url  = js_url
            result.all_downloads = [js_url]
            log.info("Script-tag URL found: %s", js_url[:80])
            return result

        # ── Strategy 3: Full link classifier scan (fallback) ──
        content_el = None
        for sel in _CONTENT_SELECTORS:
            content_el = soup.select_one(sel)
            if content_el:
                break

        classified = self.classifier.classify_all(soup, file_page_url, content_el)

        if classified[LinkKind.DOWNLOAD_BUTTON]:
            url, _ = classified[LinkKind.DOWNLOAD_BUTTON][0]
            result.download_url  = url
            result.all_downloads = [u for u, _ in classified[LinkKind.DOWNLOAD_BUTTON]]
            log.info("Download via classifier: %s", result.download_url[:80])

        if classified[LinkKind.DIRECT_PDF]:
            result.direct_pdf_url = classified[LinkKind.DIRECT_PDF][0][0]
            log.info("Direct PDF found: %s", result.direct_pdf_url[:80])

        if classified[LinkKind.EXTERNAL_FILE]:
            result.external_url = classified[LinkKind.EXTERNAL_FILE][0][0]
            log.info("External file: %s", result.external_url[:80])

        # ── Strategy 4: Form-action scan ──────────────────────
        if not result.download_url:
            form_url = self._scan_forms(soup)
            if form_url:
                result.download_url  = form_url
                result.all_downloads = [form_url]
                log.info("Form-action URL found: %s", form_url[:80])

        if not result.download_url and not result.direct_pdf_url and not result.external_url:
            result.error = "js_only"
            log.warning(
                "No download URL found on: %s — may require JS rendering.",
                file_page_url
            )

        return result

    # ══════════════════════════════════════════════════════════
    # PRIVATE
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _extract_wpdm_urls(soup: BeautifulSoup) -> list[str]:
        """
        Find all WPDM download links via CSS selectors and data-downloadurl.
        Returns list of resolved download URLs (may include multiple per page).
        """
        urls: list[str] = []
        seen: set[str]  = set()

        for selector in _WPDM_SELECTORS:
            for a in soup.select(selector):
                url = a.get("data-downloadurl", "").strip()
                if not url:
                    # Some sites put the URL directly in href (non-JS fallback)
                    url = a.get("href", "").strip()
                if url and url != "#" and url not in seen:
                    seen.add(url)
                    urls.append(url)

        return urls

    @staticmethod
    def _scan_scripts(soup: BeautifulSoup) -> str | None:
        """
        Scan all <script> tag contents for embedded download URL patterns.
        Handles JSON config objects and variable assignments used by WPDM.

        Returns the first URL found, or None.
        """
        for script in soup.find_all("script"):
            content = script.string or ""
            if not content:
                continue
            for pattern in _JS_URL_PATTERNS:
                m = pattern.search(content)
                if m:
                    url = m.group(1).replace("\\/", "/")
                    if url.startswith("http"):
                        log.debug("Script URL match: %s", url[:80])
                        return url
            # Also try JSON parsing for structured config objects
            # Look for {...} blocks that might contain download URLs
            for json_block in re.findall(r'\{[^{}]{10,}\}', content):
                try:
                    data = json.loads(json_block)
                    for key in ("downloadurl", "download_url", "fileurl", "file_url", "link"):
                        if isinstance(data.get(key), str) and data[key].startswith("http"):
                            return data[key]
                except (json.JSONDecodeError, TypeError):
                    pass
        return None

    @staticmethod
    def _scan_forms(soup: BeautifulSoup) -> str | None:
        """
        Check if the page uses a form POST to initiate a download.
        Returns the form action URL if it looks like a download endpoint.
        """
        for form in soup.find_all("form"):
            action = form.get("action", "").strip()
            if action and action.startswith("http") and (
                "download" in action.lower() or "wpdm" in action.lower()
            ):
                return action
        return None
