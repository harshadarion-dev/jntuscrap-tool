"""
core/url_manager.py — JNTUScrapTool URL Normalisation & Utilities
==================================================================
Central utility for all URL operations across phases:
  - Convert relative → absolute URLs
  - Strip tracking parameters
  - Canonicalise URL format (trailing slash, http→https, lowercase)
  - Extract slug/path segments for classification

Usage:
    from core.url_manager import URLManager
    um = URLManager()
    clean = um.normalise("../jntuk-1-1-question-papers?utm_source=fb")
"""

from __future__ import annotations

import re
from urllib.parse import (
    urljoin, urlparse, urlunparse,
    urlencode, parse_qs, urlencode,
)

import config
from core.logger import get_logger

log = get_logger("url_manager", config.PHASE2_LOG)

# Query parameters that should always be removed (tracking noise)
_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "share",
}


class URLManager:
    """
    Provides stateless URL normalisation helpers.
    All methods are safe to call on any string — malformed input returns ''.
    """

    def __init__(self, base_url: str = config.BASE_URL) -> None:
        self.base_url = base_url

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def normalise(self, href: str) -> str:
        """
        Full normalisation pipeline:
          1. Skip empty / javascript / anchor-only hrefs
          2. Resolve relative → absolute
          3. Strip tracking params
          4. Enforce trailing slash
          5. Lowercase scheme+host

        Args:
            href: Raw href value from an <a> tag.

        Returns:
            Clean absolute URL string, or '' if invalid.
        """
        if not href:
            return ""

        href = href.strip()

        # Skip non-navigable hrefs
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            return ""

        # Resolve relative URL
        url = urljoin(self.base_url, href)

        parsed = urlparse(url)

        # Must be http or https
        if parsed.scheme not in ("http", "https"):
            return ""

        # Strip tracking query params
        clean_query = self._strip_tracking(parsed.query)

        # Rebuild with lowercase scheme+host, clean query, trailing slash on path
        path = parsed.path or "/"
        if "." not in path.split("/")[-1]:   # no file extension → add trailing slash
            path = path.rstrip("/") + "/"

        clean = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            clean_query,
            "",          # strip fragment (#anchors)
        ))

        return clean

    def is_jntu_url(self, url: str) -> bool:
        """Return True if the URL belongs to the jntufastupdates domain."""
        host = urlparse(url).netloc.lower()
        return "jntufastupdates.com" in host

    def is_file_host_url(self, url: str) -> bool:
        """Return True if the URL is on the files sub-domain (PDF host)."""
        host = urlparse(url).netloc.lower()
        return host.startswith("files.")

    def get_slug(self, url: str) -> str:
        """
        Extract the last meaningful path segment (slug) from a URL.

        Example:
            'https://www.jntufastupdates.com/jntuk-1-1-question-papers/'
            → 'jntuk-1-1-question-papers'
        """
        path = urlparse(url).path.strip("/")
        return path.split("/")[-1] if path else ""

    def get_path_segments(self, url: str) -> list[str]:
        """
        Return all non-empty path segments.

        Example:
            'https://www.jntufastupdates.com/category/jntu-h/results/'
            → ['category', 'jntu-h', 'results']
        """
        path = urlparse(url).path
        return [s for s in path.strip("/").split("/") if s]

    def paginated_url(self, base_url: str, page: int) -> str:
        """
        Build a WordPress paginated URL.

        WordPress uses /page/N/ suffix for pagination.

        Example:
            base='https://.../jntuk-academic-calendars/', page=2
            → 'https://.../jntuk-academic-calendars/page/2/'
        """
        base = base_url.rstrip("/")
        return f"{base}/page/{page}/"

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _strip_tracking(query: str) -> str:
        """Remove known tracking parameters from a query string."""
        if not query:
            return ""
        params = parse_qs(query, keep_blank_values=False)
        clean = {k: v for k, v in params.items() if k not in _STRIP_PARAMS}
        return urlencode(clean, doseq=True)
