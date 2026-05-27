"""
core/naming_engine.py — JNTUScrapTool Safe Filename Engine
==========================================================
Converts academic metadata into safe, descriptive OS filenames.

Given a FileTarget dict like:
    subject="Basic Civil and Mechanical Engineering"
    exam_month="Jan", year="2024"

Produces:
    Basic_Civil_and_Mechanical_Engineering_Jan_2024.pdf

Rules:
  - Spaces → underscores
  - All punctuation/special chars stripped (except hyphens kept as _)
  - Max 120 chars (before extension)
  - Title_Case_With_Underscores
  - Always ends with .pdf

Usage:
    from core.naming_engine import NamingEngine
    ne = NamingEngine()
    filename = ne.build_filename(target_dict)
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import config
from core.logger import get_logger

log = get_logger("naming_engine", config.PHASE4_LOG)

# Max length of filename stem (without extension)
_MAX_STEM_LEN = 120


class NamingEngine:
    """
    Generates safe, descriptive filenames from FileTarget metadata.

    Priority for name source:
      1. subject   — most specific (e.g. "Basic Civil and Mechanical Engineering")
      2. title     — file-page or post title
      3. URL slug  — last resort, derived from download_target or file_page_url
    """

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def build_filename(self, target: dict) -> str:
        """
        Build a safe .pdf filename for a FileTarget record.

        Args:
            target: FileTarget dict from file_targets.json.

        Returns:
            Safe filename string, e.g. 'Basic_Civil_Jan_2024.pdf'
        """
        stem = self._choose_stem(target)
        stem = self._append_suffix(stem, target)
        stem = self.safe_name(stem, max_len=_MAX_STEM_LEN)
        filename = f"{stem}.pdf"
        log.debug("Filename: %s", filename)
        return filename

    @staticmethod
    def safe_name(text: str, max_len: int = _MAX_STEM_LEN) -> str:
        """
        Convert any string into a safe OS filename stem.

          1. Normalise unicode → ASCII
          2. Replace spaces/hyphens with underscores
          3. Strip all remaining non-alphanumeric/underscore chars
          4. Collapse multiple underscores
          5. Strip leading/trailing underscores
          6. Truncate to max_len
          7. Ensure non-empty (fallback: "unknown_file")

        Args:
            text:    Input string to sanitise.
            max_len: Maximum allowed length.

        Returns:
            Safe filename stem string.
        """
        if not text:
            return "unknown_file"

        # Normalise unicode (é → e, etc.)
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")

        # Replace space/hyphen/dot with underscore
        text = re.sub(r"[\s\-\.\(\)\[\]/\\]+", "_", text)

        # Remove anything that's not alphanumeric or underscore
        text = re.sub(r"[^\w]", "", text)

        # Collapse multiple underscores
        text = re.sub(r"_+", "_", text)

        # Strip leading/trailing underscores
        text = text.strip("_")

        # Truncate
        if len(text) > max_len:
            text = text[:max_len].rstrip("_")

        return text if text else "unknown_file"

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    def _choose_stem(self, target: dict) -> str:
        """
        Pick the best available name source from the target dict.
        Returns the raw (not yet sanitised) name string.
        """
        # 1. Subject (e.g. "Basic Civil and Mechanical Engineering")
        subject = (target.get("subject") or "").strip()
        # Reject subjects that are just noise phrases
        if subject and not self._is_noise(subject):
            return subject

        # 2. Title from file page or post
        title = (target.get("title") or "").strip()
        if title and not self._is_noise(title):
            return title

        # 3. URL slug from file_page_url or download_target
        for key in ("file_page_url", "download_target", "direct_pdf_url"):
            url = target.get(key) or ""
            if url:
                slug = self._slug_from_url(url)
                if slug:
                    return slug

        return "unknown_file"

    def _append_suffix(self, stem: str, target: dict) -> str:
        """
        Optionally append year/month suffix to make the name more specific.
        Only appended if the suffix isn't already present in the stem.
        """
        parts: list[str] = []

        month = (target.get("exam_month") or "")[:3]   # "Jan", "Feb", etc.
        year  = target.get("year") or ""

        if month and month.lower() not in stem.lower():
            parts.append(month)
        if year and year not in stem:
            parts.append(year)

        if parts:
            return stem + " " + " ".join(parts)
        return stem

    @staticmethod
    def _is_noise(text: str) -> bool:
        """Return True if the text is too generic to make a good filename."""
        noise_phrases = {
            "download", "click here", "get here", "get pdf", "pdf",
            "download here", "download now", "unknown",
        }
        clean = text.strip().lower()
        return clean in noise_phrases or len(clean) < 4

    @staticmethod
    def _slug_from_url(url: str) -> str:
        """Extract the last non-empty path segment from a URL."""
        try:
            parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
            return parts[-1].replace("-", " ").replace("_", " ") if parts else ""
        except Exception:
            return ""
