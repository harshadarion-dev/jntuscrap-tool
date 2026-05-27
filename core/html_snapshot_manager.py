"""
core/html_snapshot_manager.py — HTML Snapshot Utility
======================================================
Saves raw HTML of any scraped page to the correct raw_data subfolder
for debugging and resume support.

Usage:
    from core.html_snapshot_manager import HTMLSnapshotManager
    mgr = HTMLSnapshotManager()
    mgr.save_post(html, "https://...post-url/")
    mgr.save_file_page(html, "https://files.../download/slug/")
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import config
from core.logger import get_logger

log = get_logger("snapshot_mgr", config.PHASE3_LOG)


class HTMLSnapshotManager:
    """
    Saves HTML strings to the appropriate raw_data subdirectory.
    Filenames are derived from URL slugs so they're human-readable.
    """

    def save_post(self, html: str, url: str) -> Path:
        """Save a post page HTML snapshot."""
        return self._save(html, url, config.RAW_POST_PAGES_DIR)

    def save_nested(self, html: str, url: str) -> Path:
        """Save a nested post page HTML snapshot."""
        return self._save(html, url, config.RAW_NESTED_PAGES_DIR)

    def save_file_page(self, html: str, url: str) -> Path:
        """Save a file/download page HTML snapshot."""
        return self._save(html, url, config.RAW_FILE_PAGES_DIR)

    # ── Private ──────────────────────────────────────────────
    @staticmethod
    def _url_to_filename(url: str) -> str:
        """Convert a URL into a safe filename using the last path segment."""
        # Extract last non-empty path segment
        parts = [p for p in url.rstrip("/").split("/") if p]
        slug  = parts[-1] if parts else "unknown"
        # Sanitise
        slug  = re.sub(r"[^\w\-]", "_", slug)[:80]
        # Hash suffix to ensure uniqueness
        h     = hashlib.md5(url.encode()).hexdigest()[:6]
        return f"{slug}_{h}.html"

    def _save(self, html: str, url: str, folder: Path) -> Path:
        """Write html to folder/filename and return the path."""
        folder.mkdir(parents=True, exist_ok=True)
        filename = self._url_to_filename(url)
        path     = folder / filename
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        log.debug("Snapshot saved → %s", path)
        return path
