"""
core/title_analyzer.py — JNTUScrapTool Extended Title & URL Analyzer
====================================================================
Extends ContentParser with additional signal detection for:
  - Exam type (Regular / Supply / Advanced Supply / Revaluation)
  - Extended branch aliases (AIDS, CSM, AIML, DS, CSBS)
  - URL-slug enrichment (parse regulation/semester from file_page_url when title is thin)
  - Degree normalisation to canonical forms

Used by Phase 5 MetadataEnricher to produce fully-enriched records.

Usage:
    from core.title_analyzer import TitleAnalyzer
    ta = TitleAnalyzer()
    enriched = ta.analyze(record_dict)   # returns a copy with added fields
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import config
from core.logger import get_logger
from core.content_parser import ContentParser, ContentMetadata

log = get_logger("title_analyzer", config.PHASE5_LOG)

# Exam type keywords → canonical label
_EXAM_TYPE_MAP: dict[str, str] = {
    "regular":          "Regular",
    "supply":           "Supplementary",
    "supplementary":    "Supplementary",
    "advanced supply":  "Advanced Supplementary",
    "revaluation":      "Revaluation",
    "backlog":          "Supplementary",
    "improvement":      "Improvement",
}

# Extended branch aliases → canonical name
_BRANCH_ALIASES: dict[str, str] = {
    "cse":      "CSE",
    "ece":      "ECE",
    "eee":      "EEE",
    "mech":     "MECH",
    "mechanical": "MECH",
    "civil":    "CIVIL",
    "it":       "IT",
    "aids":     "AIDS",
    "ai&ds":    "AIDS",
    "aiml":     "AI&ML",
    "ai&ml":    "AI&ML",
    "csm":      "CSM",
    "csbs":     "CSBS",
    "ds":       "DS",
    "data science": "DS",
    "chem":     "CHEM",
    "chemical": "CHEM",
    "aero":     "AERO",
    "bio":      "BIO",
    "biotech":  "BIO",
    "mining":   "MINING",
    "metallurgy": "METALLURGY",
    "petroleum": "PETROLEUM",
}

# Degree normalisation map
_DEGREE_NORM: dict[str, str] = {
    "btech":     "B.Tech",
    "b.tech":    "B.Tech",
    "b.tech.":   "B.Tech",
    "b.e":       "B.E",
    "bpharmacy": "B.Pharmacy",
    "b.pharmacy":"B.Pharmacy",
    "b.pharm":   "B.Pharmacy",
    "mtech":     "M.Tech",
    "m.tech":    "M.Tech",
    "mba":       "MBA",
    "mca":       "MCA",
    "b.sc":      "B.Sc",
}

# Regex for regulation in URL slugs (e.g. "r23", "r20")
_RE_REG_SLUG = re.compile(r"(?:^|[-_/])r(\d{2})(?:[-_/]|$)", re.I)
# Regex for semester in URL slugs (e.g. "1-1", "2-2", "1-year")
_RE_SEM_SLUG = re.compile(r"(?:^|[-_/])(\d[-–]\d)(?:[-_/]|$)")
_RE_YEAR_SLUG = re.compile(r"(?:^|[-_/])(\d{4})(?:[-_/]|$)")


class TitleAnalyzer:
    """
    Extended metadata analyzer that enriches a flat FileTarget / DownloadRecord dict.

    Builds on top of ContentParser — runs a full parse_title() pass first,
    then applies additional signals not covered by the base parser.
    """

    def __init__(self) -> None:
        self._parser = ContentParser()

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def analyze(self, record: dict) -> dict:
        """
        Enrich a flat record dict with all available metadata.

        All existing fields are preserved; detected values are added
        where the existing value is None or empty.

        Args:
            record: Flat dict (FileTarget or merged Phase 4/3 record).

        Returns:
            New dict with all original keys + additional enrichments.
        """
        result = dict(record)   # shallow copy — never mutate input

        title = (record.get("title") or "").strip()
        hints = {
            k: record.get(k)
            for k in ("university", "category", "semester", "regulation",
                      "year", "degree", "branch", "subject", "exam_month",
                      "academic_year")
        }

        # ── Base parse via ContentParser ────────────────────────
        meta: ContentMetadata = self._parser.parse_title(title, hints)

        # ── Merge: only fill in where result field is empty ─────
        field_map = {
            "university":    meta.university,
            "degree":        meta.degree,
            "branch":        meta.branch,
            "semester":      meta.semester,
            "regulation":    meta.regulation,
            "year":          meta.year,
            "academic_year": meta.academic_year,
            "exam_month":    meta.exam_month,
            "category":      meta.category,
            "subject":       meta.subject,
        }
        for key, val in field_map.items():
            if not result.get(key) and val:
                result[key] = val

        # ── Normalise degree ────────────────────────────────────
        if result.get("degree"):
            result["degree"] = self._norm_degree(result["degree"])

        # ── Extended branch detection ───────────────────────────
        if not result.get("branch") and title:
            result["branch"] = self._detect_branch(title)

        # ── Exam type ───────────────────────────────────────────
        result["exam_type"] = self._detect_exam_type(title)

        # ── URL-slug enrichment (fill gaps from URL) ────────────
        for url_key in ("file_page_url", "download_target", "post_url"):
            url = record.get(url_key) or ""
            if url:
                self._enrich_from_url(url, result)
                break   # One URL is enough

        # ── exam_year = year when exam month present ────────────
        if not result.get("exam_year") and result.get("year"):
            result["exam_year"] = result["year"]

        log.debug(
            "Analyzed: uni=%s deg=%s sem=%s reg=%s cat=%s",
            result.get("university"), result.get("degree"),
            result.get("semester"), result.get("regulation"),
            result.get("category"),
        )
        return result

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _norm_degree(raw: str) -> str:
        """Normalise degree string to a canonical form."""
        key = raw.lower().replace(" ", "")
        return _DEGREE_NORM.get(key, raw)

    @staticmethod
    def _detect_branch(text: str) -> str | None:
        """Return canonical branch code from title text, or None."""
        lower = text.lower()
        # Try longest matches first (e.g. "ai&ds" before "ai")
        for alias in sorted(_BRANCH_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", lower):
                return _BRANCH_ALIASES[alias]
        return None

    @staticmethod
    def _detect_exam_type(text: str) -> str | None:
        """Detect exam type (Regular / Supplementary / Revaluation)."""
        lower = text.lower()
        # Check longest phrases first
        for phrase in sorted(_EXAM_TYPE_MAP, key=len, reverse=True):
            if phrase in lower:
                return _EXAM_TYPE_MAP[phrase]
        return None

    @staticmethod
    def _enrich_from_url(url: str, result: dict) -> None:
        """
        Extract regulation / semester / year from a URL slug
        to fill any gaps in the result dict.
        """
        try:
            path = urlparse(url).path.lower()
        except Exception:
            return

        if not result.get("regulation"):
            m = _RE_REG_SLUG.search(path)
            if m:
                result["regulation"] = f"R{m.group(1).upper()}"

        if not result.get("semester"):
            m = _RE_SEM_SLUG.search(path)
            if m:
                result["semester"] = m.group(1)

        if not result.get("year"):
            m = _RE_YEAR_SLUG.search(path)
            if m:
                result["year"] = m.group(1)
