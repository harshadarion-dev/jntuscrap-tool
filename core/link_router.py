"""
core/link_router.py — JNTUScrapTool Link Classification Engine
==============================================================
Classifies any jntufastupdates.com URL into one of these types:
  - CATEGORY       : Direct category listing (e.g. /jntuk-academic-calendars/)
  - NESTED_CATEGORY: Sub-category hub (e.g. /jntuk-1-1-question-papers/)
  - POST           : Individual post/article page
  - FILE_PAGE      : files.jntufastupdates.com download page
  - EXTERNAL       : Outside the JNTU domain — ignore
  - UNKNOWN        : Cannot classify

Also extracts metadata hints (university, category, semester, regulation, year)
from a URL slug without needing to fetch the page.

Usage:
    from core.link_router import LinkRouter, LinkType
    router = LinkRouter()
    result = router.classify("http://www.jntufastupdates.com/jntuk-1-1-r23-question-papers-2024/")
    print(result.link_type, result.university, result.semester)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse

import config
from core.logger import get_logger

log = get_logger("link_router", config.PHASE2_LOG)


class LinkType(str, Enum):
    CATEGORY        = "category"
    NESTED_CATEGORY = "nested_category"
    POST            = "post"
    FILE_PAGE       = "file_page"
    EXTERNAL        = "external"
    UNKNOWN         = "unknown"


@dataclass
class RoutedLink:
    """Result of classifying a single URL."""
    url:         str
    link_type:   LinkType
    university:  str | None = None
    category:    str | None = None
    degree:      str | None = None
    semester:    str | None = None
    regulation:  str | None = None
    year:        str | None = None
    extra_hints: dict = field(default_factory=dict)


# ── Regex patterns for slug decomposition ────────────────────────
_RE_SEMESTER   = re.compile(r"\b(\d-\d)\b")          # e.g. 1-1, 3-2
_RE_REGULATION = re.compile(r"\b(r\d{2})\b", re.I)   # e.g. R23, R20, R19
_RE_YEAR       = re.compile(r"\b(20\d{2})\b")         # e.g. 2024
_RE_DEGREE     = re.compile(
    r"\b(b[\.\- ]?tech|b[\.\- ]?pharmacy|b[\.\- ]?sc|mba|mca|m[\.\- ]?tech)\b",
    re.I,
)

# Category-page slug patterns (JNTU Fast Updates specific)
_CATEGORY_SLUGS = {
    "academic-calendar":    "Academic Calendars",
    "academic-regulation":  "Academic Regulations",
    "question-paper":       "Question Papers",
    "syllabus":             "Syllabus",
    "time-table":           "Time Tables",
    "timetable":            "Time Tables",
    "result":               "Results",
    "material":             "Materials",
    "notification":         "Notifications",
}

# Known top-level category root slugs (hub pages that contain nested links)
_HUB_SLUGS = {
    "question-papers",
    "syllabus",
    "results",
    "time-tables",
    "materials",
    "notifications",
}


class LinkRouter:
    """
    Classifies any URL and extracts metadata hints from the slug.

    The classification logic is purely regex/string-based — no HTTP requests.
    """

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def classify(self, url: str) -> RoutedLink:
        """
        Classify a URL and extract all available metadata hints.

        Args:
            url: Absolute URL string.

        Returns:
            RoutedLink with link_type and extracted metadata fields.
        """
        parsed = urlparse(url)
        host   = parsed.netloc.lower()

        # ── External / files subdomain ────────────────────
        if "jntufastupdates.com" not in host:
            return RoutedLink(url=url, link_type=LinkType.EXTERNAL)

        if host.startswith("files."):
            return RoutedLink(url=url, link_type=LinkType.FILE_PAGE)

        # ── Extract path segments + slug ──────────────────
        segments = [s for s in parsed.path.strip("/").split("/") if s]
        slug     = segments[-1] if segments else ""

        # /category/... paths are category archives
        if segments and segments[0] == "category":
            return self._make_routed(url, LinkType.CATEGORY, slug)

        # ── Homepage → not a content page ────────────────
        if not slug or slug == "":
            return RoutedLink(url=url, link_type=LinkType.UNKNOWN)

        # ── Classify by slug characteristics ─────────────
        link_type = self._classify_slug(slug)

        routed = self._make_routed(url, link_type, slug)
        return routed

    def should_recurse(self, routed: RoutedLink) -> bool:
        """
        Return True if this link should be followed for deeper scraping.
        FILE_PAGE, EXTERNAL, and UNKNOWN links should not be recursed.
        """
        return routed.link_type in (
            LinkType.CATEGORY, LinkType.NESTED_CATEGORY
        )

    def is_post(self, routed: RoutedLink) -> bool:
        """Return True if this is a leaf post page to be scraped for files."""
        return routed.link_type == LinkType.POST

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    def _classify_slug(self, slug: str) -> LinkType:
        """
        Determine link type from the URL slug alone.

        Heuristic priority:
          1. Known hub slugs → CATEGORY (top-level)
          2. Slug matches a category keyword + university keyword → CATEGORY
          3. Slug matches category keyword + semester/regulation → NESTED_CATEGORY
          4. Slug has date-like or exam-name patterns → POST
          5. Default → POST (leaf pages are posts)
        """
        lower = slug.lower()

        # Known hub (top-level category) pages — no semester in slug
        if lower in _HUB_SLUGS:
            return LinkType.CATEGORY

        has_uni      = any(k in lower for k in config.UNIVERSITY_KEYWORDS)
        has_category = any(k in lower for k in _CATEGORY_SLUGS)
        has_semester = bool(_RE_SEMESTER.search(lower))
        has_reg      = bool(_RE_REGULATION.search(lower))
        has_year     = bool(_RE_YEAR.search(lower))

        # E.g. "jntuk-academic-calendars" → category (uni + category, no semester)
        if has_uni and has_category and not has_semester and not has_year:
            return LinkType.CATEGORY

        # E.g. "jntuk-1-1-question-papers" → nested category
        if has_category and has_semester and not has_year:
            return LinkType.NESTED_CATEGORY

        # E.g. "jntuk-1-1-r23-question-papers-2024" → nested sub-category
        if has_category and (has_semester or has_reg) and has_year:
            return LinkType.NESTED_CATEGORY

        # Anything with a year + exam/subject name → post
        if has_year:
            return LinkType.POST

        # Default: treat unknown slugs as posts (safe fall-through)
        return LinkType.POST

    def _make_routed(self, url: str, link_type: LinkType, slug: str) -> RoutedLink:
        """Build a RoutedLink and populate metadata fields from slug."""
        lower = slug.lower()

        # University
        university = None
        for kw, code in config.UNIVERSITY_KEYWORDS.items():
            if kw in lower:
                university = code
                break

        # Category
        category = None
        for kw, cat in _CATEGORY_SLUGS.items():
            if kw in lower:
                category = cat
                break

        # Semester (first match e.g. "1-1")
        sem_m = _RE_SEMESTER.search(lower)
        semester = sem_m.group(1) if sem_m else None

        # Regulation (first match e.g. "r23")
        reg_m = _RE_REGULATION.search(lower)
        regulation = reg_m.group(1).upper() if reg_m else None

        # Year
        year_m = _RE_YEAR.search(lower)
        year = year_m.group(1) if year_m else None

        # Degree
        deg_m = _RE_DEGREE.search(lower)
        degree = deg_m.group(1).replace("-", ".").replace(" ", ".") if deg_m else None

        return RoutedLink(
            url=url,
            link_type=link_type,
            university=university,
            category=category,
            degree=degree,
            semester=semester,
            regulation=regulation,
            year=year,
        )
