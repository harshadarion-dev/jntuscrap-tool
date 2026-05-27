"""
core/subject_normalizer.py — JNTUScrapTool Subject Name Normalizer
==================================================================
Cleans, normalises, and canonicalises JNTU subject names from:
  - URL slugs: "basic-civil-and-mechanical-engineering" → "Basic Civil And Mechanical Engineering"
  - Noisy titles: "Download Basic Civil..." → "Basic Civil..."
  - Abbreviations: Maps known abbreviations to full canonical names

Usage:
    from core.subject_normalizer import SubjectNormalizer
    sn = SubjectNormalizer()
    clean = sn.normalize("basic-civil-and-mechanical-engineering")
    # → "Basic Civil And Mechanical Engineering"
"""

from __future__ import annotations

import re

import config
from core.logger import get_logger

log = get_logger("subject_normalizer", config.PHASE5_LOG)

# Noise prefixes to strip (case-insensitive)
_NOISE_PREFIXES = [
    r"^download\s+",
    r"^get\s+",
    r"^view\s+",
    r"^click\s+here\s+(?:to\s+)?(?:download\s+)?",
    r"^jntuk\s+",
    r"^jntuh\s+",
    r"^jntua\s+",
    r"^jntugv?\s+",
]

# Noise suffixes / phrases inside subject names
_NOISE_PATTERNS = [
    r"\s*[-–|]\s*jntu\w*",
    r"\s*\(\s*r\d{2}\s*\)",        # (R23), (R20)
    r"\s*r\d{2}\s*",               # trailing R23
    r"\s+question\s+papers?\s*",
    r"\s+qp\s*",
    r"\s+syllabus\s*",
    r"\s+time\s+table\s*",
    r"\s+results?\s*",
    r"\s+notifications?\s*",
    r"\s+materials?\s*",
    r"\b\d{1,2}[-–]\d\s+sem\b",   # 1-1 sem
    r"\b\d{4}[-–]\d{2,4}\b",      # 2025-26
    r"\bjan(?:uary)?\b|\bfeb(?:ruary)?\b|\bmar(?:ch)?\b|\bapr(?:il)?\b",
    r"\bmay\b|\bjun(?:e)?\b|\bjul(?:y)?\b|\baug(?:ust)?\b",
    r"\bsep(?:tember)?\b|\boct(?:ober)?\b|\bnov(?:ember)?\b|\bdec(?:ember)?\b",
    r"\b20\d{2}\b",                # standalone year
    r"\bregular\b|\bsupply\b|\bsupplementary\b|\brevaluation\b",
    r"\bexam(?:ination)?s?\b",
    r"\bfor\s+the\s+a\.?y\.?\b",
]

# Known subject canonical names — maps lower-cleaned version to proper form
_SUBJECT_CANON: dict[str, str] = {
    "basic civil and mechanical engineering": "Basic Civil and Mechanical Engineering",
    "bcme": "Basic Civil and Mechanical Engineering",
    "engineering mathematics i": "Engineering Mathematics I",
    "engineering mathematics ii": "Engineering Mathematics II",
    "engineering mathematics iii": "Engineering Mathematics III",
    "engineering physics": "Engineering Physics",
    "engineering chemistry": "Engineering Chemistry",
    "engineering drawing": "Engineering Drawing",
    "engineering graphics": "Engineering Graphics",
    "computer programming": "Computer Programming",
    "programming for problem solving": "Programming For Problem Solving",
    "object oriented programming through java": "Object Oriented Programming Through Java",
    "data structures": "Data Structures",
    "database management systems": "Database Management Systems",
    "dbms": "Database Management Systems",
    "operating systems": "Operating Systems",
    "computer networks": "Computer Networks",
    "software engineering": "Software Engineering",
    "compiler design": "Compiler Design",
    "machine learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "artificial intelligence": "Artificial Intelligence",
    "digital logic design": "Digital Logic Design",
    "electronic devices and circuits": "Electronic Devices and Circuits",
    "signals and systems": "Signals and Systems",
    "electromagnetic fields": "Electromagnetic Fields",
    "control systems": "Control Systems",
    "power systems": "Power Systems",
    "microprocessors and microcontrollers": "Microprocessors and Microcontrollers",
    "fluid mechanics": "Fluid Mechanics",
    "thermodynamics": "Thermodynamics",
    "strength of materials": "Strength of Materials",
    "environmental science": "Environmental Science",
    "managerial economics and financial analysis": "Managerial Economics and Financial Analysis",
    "mefa": "Managerial Economics and Financial Analysis",
    "probability and statistics": "Probability and Statistics",
    "discrete mathematics": "Discrete Mathematics",
    "linear algebra": "Linear Algebra",
    "transform calculus": "Transform Calculus",
}


class SubjectNormalizer:
    """
    Cleans and normalises JNTU subject/title strings.

    Operations (in order):
      1. Deslug (hyphen/underscore → space)
      2. Strip noise prefixes
      3. Strip noise patterns
      4. Title-case
      5. Apply canonical name map
      6. Final whitespace cleanup
    """

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def normalize(self, text: str | None) -> str | None:
        """
        Normalise a raw subject/title string.

        Args:
            text: Raw string, e.g. 'basic-civil-and-mechanical-engineering'
                  or 'Download Basic Civil Jan 2024'

        Returns:
            Cleaned string, or None if the result is too short to be useful.
        """
        if not text:
            return None

        result = text.strip()

        # Step 1 — Deslug (keep existing case differences from real subject names)
        result = self._deslug(result)

        # Step 2 — Strip noise prefixes
        for pat in _NOISE_PREFIXES:
            result = re.sub(pat, "", result, flags=re.I).strip()

        # Step 3 — Strip embedded noise patterns
        for pat in _NOISE_PATTERNS:
            result = re.sub(pat, " ", result, flags=re.I)

        # Step 4 — Collapse whitespace and strip trailing punctuation
        result = re.sub(r"\s+", " ", result).strip(" ,.-–()")

        # Step 5 — Title case
        result = result.title()

        # Step 6 — Canonical lookup (title-cased input → proper name)
        canon_key = result.lower()
        if canon_key in _SUBJECT_CANON:
            result = _SUBJECT_CANON[canon_key]

        # Step 7 — Reject if too short or still noisy
        if len(result) < 4:
            return None
        if result.lower() in {"download", "pdf", "file", "here", "get here", "unknown"}:
            return None

        log.debug("Normalized: %r → %r", text[:40], result[:40])
        return result

    # ══════════════════════════════════════════════════════════
    # PRIVATE
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _deslug(text: str) -> str:
        """Replace URL slug separators with spaces."""
        # Only deslug if the text looks like a slug (all-lowercase/hyphens)
        if re.match(r"^[a-z0-9][a-z0-9\-_]+$", text):
            return text.replace("-", " ").replace("_", " ")
        return text
