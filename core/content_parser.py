"""
core/content_parser.py — JNTUScrapTool Metadata Parser
=======================================================
Extracts structured academic metadata from post titles and page content.

Given a raw title like:
    "JNTUK B.Tech 1-1 Sem (R23) Regular Question Papers Jan 2024"

Returns:
    ContentMetadata with university, degree, semester, regulation,
    category, subject, exam_month, year, etc.

Also extracts subject names from structured content (e.g. subject-per-row tables).

Usage:
    from core.content_parser import ContentParser
    parser = ContentParser()
    meta = parser.parse_title("JNTUK B.Tech 1-1 Sem (R23) Regular Question Papers Jan 2024")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

import config
from core.logger import get_logger

log = get_logger("content_parser", config.PHASE3_LOG)

# ── Regex patterns ────────────────────────────────────────────────
_RE_SEM       = re.compile(r"\b(\d[-–]\d)\b")                       # 1-1, 3-2
_RE_REG       = re.compile(r"\b(R\d{2})\b", re.I)                   # R23, R20
_RE_YEAR      = re.compile(r"\b(20\d{2})\b")                        # 2024
_RE_AY        = re.compile(r"(?:AY|A\.Y\.?)\s*(20\d{2}[-–]\d{2,4})",re.I)  # A.Y 2025-26
_RE_MONTH     = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b",
    re.I,
)
_RE_DEGREE    = re.compile(
    r"\b(B\.?Tech|B\.?Pharmacy|B\.?Pharm|B\.?Sc|M\.?Tech|MBA|MCA|B\.?E)\b", re.I
)
_RE_BRANCH    = re.compile(
    r"\b(CSE|ECE|EEE|MECH(?:ANICAL)?|CIVIL|IT|AI(?:&?ML)?|DATA\s*SCIENCE|"
    r"CHEM(?:ICAL)?|AERO(?:NAUTICAL)?|BIOTECH(?:NOLOGY)?)\b",
    re.I,
)

# Month abbreviation → full month
_MONTH_NORM = {
    "jan": "January", "feb": "February", "mar": "March", "apr": "April",
    "may": "May", "jun": "June", "jul": "July", "aug": "August",
    "sep": "September", "oct": "October", "nov": "November", "dec": "December",
}

# Category keyword → canonical name
_CAT_KEYWORDS = {
    "question paper": "Question Papers",
    "question papers": "Question Papers",
    "academic calendar": "Academic Calendars",
    "academic regulation": "Academic Regulations",
    "regulation": "Academic Regulations",
    "syllabus": "Syllabus",
    "time table": "Time Tables",
    "timetable": "Time Tables",
    "result": "Results",
    "notification": "Notifications",
    "material": "Materials",
}


@dataclass
class ContentMetadata:
    """Structured metadata extracted from a post title or page content."""
    title:        str           = ""
    university:   Optional[str] = None
    degree:       Optional[str] = None
    branch:       Optional[str] = None
    regulation:   Optional[str] = None
    semester:     Optional[str] = None
    category:     Optional[str] = None
    subject:      Optional[str] = None
    exam_month:   Optional[str] = None
    year:         Optional[str] = None
    academic_year:Optional[str] = None
    extra:        dict          = field(default_factory=dict)


class ContentParser:
    """
    Extracts academic metadata from:
      - Post titles  (parse_title)
      - Post body HTML (parse_content)
    """

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def parse_title(self, title: str, hints: dict | None = None) -> ContentMetadata:
        """
        Parse a post title string into structured metadata.

        Args:
            title: e.g. "JNTUK B.Tech 1-1 (R23) Question Papers Jan 2024"
            hints: Optional dict of pre-known values (from Phase 2 router).

        Returns:
            ContentMetadata with all extractable fields populated.
        """
        meta          = ContentMetadata(title=title)
        hints         = hints or {}

        # ── Seed from Phase 2 hints ───────────────────────────
        meta.university  = hints.get("university")
        meta.regulation  = hints.get("regulation")
        meta.semester    = hints.get("semester")
        meta.year        = hints.get("year")
        meta.category    = hints.get("category")
        meta.degree      = hints.get("degree")

        # ── University ────────────────────────────────────────
        if not meta.university:
            lower = title.lower()
            for kw, code in config.UNIVERSITY_KEYWORDS.items():
                if kw in lower:
                    meta.university = code
                    break

        # ── Degree ────────────────────────────────────────────
        if not meta.degree:
            m = _RE_DEGREE.search(title)
            if m:
                meta.degree = m.group(1).replace(" ", ".")

        # ── Branch ────────────────────────────────────────────
        m = _RE_BRANCH.search(title)
        if m:
            meta.branch = m.group(1).upper()

        # ── Semester ──────────────────────────────────────────
        if not meta.semester:
            m = _RE_SEM.search(title)
            if m:
                meta.semester = m.group(1)

        # ── Regulation ────────────────────────────────────────
        if not meta.regulation:
            m = _RE_REG.search(title)
            if m:
                meta.regulation = m.group(1).upper()

        # ── Year ──────────────────────────────────────────────
        if not meta.year:
            m = _RE_YEAR.search(title)
            if m:
                meta.year = m.group(1)

        # ── Academic Year ─────────────────────────────────────
        m = _RE_AY.search(title)
        if m:
            meta.academic_year = m.group(1)

        # ── Exam Month ────────────────────────────────────────
        m = _RE_MONTH.search(title)
        if m:
            raw = m.group(1).lower()[:3]
            meta.exam_month = _MONTH_NORM.get(raw, m.group(1))

        # ── Category ──────────────────────────────────────────
        if not meta.category:
            lower = title.lower()
            for kw, cat in _CAT_KEYWORDS.items():
                if kw in lower:
                    meta.category = cat
                    break

        # ── Subject (residual title after removing known tokens) ─
        meta.subject = self._extract_subject(title, meta)

        log.debug("Parsed: uni=%s sem=%s reg=%s cat=%s subj=%s",
                  meta.university, meta.semester, meta.regulation,
                  meta.category, meta.subject)
        return meta

    def parse_content(self, soup: BeautifulSoup, base_meta: ContentMetadata) -> ContentMetadata:
        """
        Enrich metadata by scanning the page body for additional context.
        Tries to find subject names from inline tables or bold labels.

        Args:
            soup:      Parsed HTML of the post page.
            base_meta: Metadata already extracted from the title.

        Returns:
            Enriched ContentMetadata (mutates base_meta in-place).
        """
        content = soup.select_one(
            ".td-post-content, .entry-content, .td-pb-span8, article"
        )
        if not content:
            return base_meta

        # Try to extract subject from first <h2> or <h3> inside content
        if not base_meta.subject:
            for heading in content.find_all(["h2", "h3", "h4"], limit=2):
                txt = heading.get_text(strip=True)
                if len(txt) > 5 and not any(kw in txt.lower() for kw in
                                            ["jntuk", "jntuh", "jntua", "download", "question"]):
                    base_meta.subject = txt
                    break

        return base_meta

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _extract_subject(title: str, meta: ContentMetadata) -> Optional[str]:
        """
        Extract subject name by removing known academic tokens from the title.
        What remains is typically the subject or document name.
        """
        residual = title

        # Remove university codes
        for kw in config.UNIVERSITY_KEYWORDS:
            residual = re.sub(rf"\b{re.escape(kw)}\b", "", residual, flags=re.I)

        # Remove degree
        residual = _RE_DEGREE.sub("", residual)
        # Remove semester pattern
        residual = _RE_SEM.sub("", residual)
        # Remove regulation
        residual = _RE_REG.sub("", residual)
        # Remove years
        residual = _RE_YEAR.sub("", residual)
        # Remove academic year
        residual = _RE_AY.sub("", residual)
        # Remove month
        residual = _RE_MONTH.sub("", residual)
        # Remove category keywords
        for kw in _CAT_KEYWORDS:
            residual = re.sub(rf"\b{re.escape(kw)}\b", "", residual, flags=re.I)
        # Common noise words
        for noise in [
            "regular", "supply", "advanced supply", "revaluation", "results",
            "released", "b.tech", "sem", "exam", "examinations", "–", "-",
            "january", "february", "all results at one place",
            r"\(\s*\)", r"\|", r"r\d{2}", "revised",
        ]:
            residual = re.sub(rf"\b{re.escape(noise)}\b", "", residual, flags=re.I)

        # Collapse whitespace and strip punctuation from ends
        residual = re.sub(r"\s+", " ", residual).strip(" ,.-–()")

        return residual if len(residual) > 3 else None
