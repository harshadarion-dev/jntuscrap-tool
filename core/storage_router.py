"""
core/storage_router.py — JNTUScrapTool File Storage Router
===========================================================
Maps a FileTarget metadata dict to the correct local storage path.

Storage hierarchy:
    storage/
    └── {UNIVERSITY}/
        └── {Category}/
            └── {Degree}/
                └── {Regulation}/     (omitted if None)
                    └── {Semester}/   (omitted if None)
                        └── filename.pdf

Examples:
    JNTUK / Question_Papers / BTech / R23 / 1-1 / Basic_Civil_Jan_2024.pdf
    JNTUK / Academic_Calendars / BTech / Unknown / 1-1 / AC_2025_26.pdf

Usage:
    from core.storage_router import StorageRouter
    sr = StorageRouter()
    path = sr.resolve(target_dict, filename)
"""

from __future__ import annotations

import re
from pathlib import Path

import config
from core.logger import get_logger

log = get_logger("storage_router", config.PHASE4_LOG)

# Maps raw category strings → safe folder names
_CATEGORY_MAP = {
    "Academic Calendars":   "Academic_Calendars",
    "Academic Regulations": "Academic_Regulations",
    "Question Papers":      "Question_Papers",
    "Syllabus":             "Syllabus",
    "Time Tables":          "Time_Tables",
    "Results":              "Results",
    "Materials":            "Materials",
    "Notifications":        "Notifications",
}

# Maps raw degree strings → safe folder names
_DEGREE_MAP = {
    "B.Tech":  "BTech",
    "B.Tech.": "BTech",
    "BTech":   "BTech",
    "btech":   "BTech",
    "b.tech":  "BTech",
    "B.Pharmacy": "BPharmacy",
    "B.Pharm":    "BPharmacy",
    "M.Tech":  "MTech",
    "m.tech":  "MTech",
    "MBA":     "MBA",
    "MCA":     "MCA",
    "B.Sc":    "BSc",
}


class StorageRouter:
    """
    Resolves the correct storage directory for a file target and
    creates all necessary parent directories on demand.

    The hierarchy is designed to make files browsable by humans and
    importable systematically by future phases.
    """

    def __init__(self, base_dir: Path = config.STORAGE_DIR) -> None:
        self.base_dir = base_dir

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def resolve(self, target: dict, filename: str) -> Path:
        """
        Compute the final storage path for one file target.

        Creates all parent directories as a side-effect.

        Args:
            target:   FileTarget dict from file_targets.json.
            filename: Safe filename string (from NamingEngine).

        Returns:
            Absolute Path where the file should be saved.
        """
        parts = self._build_parts(target)
        folder = self.base_dir.joinpath(*parts)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / filename
        log.debug("Storage path: %s", path)
        return path

    def resolve_dir(self, target: dict) -> Path:
        """
        Return (and create) the storage directory for a target without a filename.
        Useful for pre-creating the hierarchy.
        """
        parts = self._build_parts(target)
        folder = self.base_dir.joinpath(*parts)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    def _build_parts(self, target: dict) -> list[str]:
        """
        Build the ordered list of directory components for this target.
        Missing/None values fall back to 'Unknown'.
        """
        parts: list[str] = []

        # 1. University  (JNTUK / JNTUH / JNTUA / JNTUGV)
        uni = self._safe(target.get("university")) or "Unknown_University"
        parts.append(uni)

        # 2. Category  (Question_Papers / Academic_Calendars / …)
        raw_cat = (target.get("category") or "").strip()
        cat = _CATEGORY_MAP.get(raw_cat, self._safe(raw_cat) or "Uncategorised")
        parts.append(cat)

        # 3. Degree  (BTech / MTech / MBA / …)
        raw_deg = (target.get("degree") or "").strip()
        deg_key = raw_deg.lower() if raw_deg else ""
        degree = (
            _DEGREE_MAP.get(raw_deg)
            or _DEGREE_MAP.get(deg_key)
            or (self._safe(raw_deg) if raw_deg else "Unknown_Degree")
        )
        parts.append(degree)

        # 4. Regulation  (R23 / R20 / …) — omit if missing
        regulation = self._safe(target.get("regulation") or "")
        if regulation:
            parts.append(regulation)

        # 5. Semester  (1-1 / 2-2 / …) — omit if missing
        semester = self._safe(target.get("semester") or "")
        if semester:
            parts.append(semester)

        return parts

    @staticmethod
    def _safe(text: str | None) -> str:
        """Strip unsafe path characters from a folder name component."""
        if not text:
            return ""
        # Replace path separators and other unsafe chars with underscore
        clean = re.sub(r"[\\/:*?\"<>|]", "_", text.strip())
        clean = re.sub(r"\s+", "_", clean)
        return clean.strip("_") or ""
