"""
database/search_engine.py — JNTUScrapTool Academic Search Engine
================================================================
Provides query methods over the master SQLite database.

Built on top of DatabaseManager — all queries run via SQLAlchemy ORM.

Designed for FastAPI compatibility: every method returns `list[dict]`
so results can be serialised directly to JSON.

Usage:
    from database.db_manager import DatabaseManager
    from database.search_engine import SearchEngine
    db = DatabaseManager(); db.create_tables()
    se = SearchEngine(db)
    results = se.search_by_semester("1-1")
    analytics = se.get_analytics()
"""

from __future__ import annotations

from sqlalchemy import or_, select

import config
from core.logger import get_logger
from database.db_manager import DatabaseManager
from database.models import PdfRecord

log = get_logger("search_engine", config.PHASE6_LOG)


class SearchEngine:
    """
    Query interface for the master PDF database.

    All `search_*` methods return a list of plain dicts (API-ready).
    All match is case-insensitive where applicable.

    Args:
        db: An initialised DatabaseManager instance.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ══════════════════════════════════════════════════════════
    # SEARCH METHODS
    # ══════════════════════════════════════════════════════════

    def search_by_subject(self, query: str) -> list[dict]:
        """
        Full-text LIKE search on subject field.
        Returns records where subject contains `query` (case-insensitive).

        Args:
            query: Partial or full subject name.

        Returns:
            List of matching records as dicts.
        """
        return self._like_search(PdfRecord.subject, query)

    def search_by_semester(self, semester: str) -> list[dict]:
        """
        Exact match on semester (e.g. '1-1', '2-2').

        Args:
            semester: Semester string.
        """
        return self._exact_search(PdfRecord.semester, semester)

    def search_by_regulation(self, regulation: str) -> list[dict]:
        """
        Exact match on regulation (e.g. 'R23', 'R20').

        Args:
            regulation: Regulation code, case-insensitive.
        """
        return self._exact_search(PdfRecord.regulation, regulation.upper())

    def search_by_university(self, university: str) -> list[dict]:
        """
        Exact match on university code (JNTUK, JNTUH, JNTUA, JNTUGV).

        Args:
            university: University code, case-insensitive.
        """
        return self._exact_search(PdfRecord.university, university.upper())

    def search_by_category(self, category: str) -> list[dict]:
        """
        Exact match on category (e.g. 'Question Papers', 'Academic Calendars').

        Args:
            category: Category string.
        """
        return self._exact_search(PdfRecord.category, category)

    def search_by_regulation_semester(
        self, regulation: str, semester: str
    ) -> list[dict]:
        """
        Combined exact match on regulation AND semester.
        Common search pattern for students.

        Args:
            regulation: e.g. 'R23'
            semester:   e.g. '1-1'
        """
        log.debug("search_by_reg_sem: reg=%s sem=%s", regulation, semester)
        with self._db._Session() as session:
            rows = session.scalars(
                select(PdfRecord).where(
                    PdfRecord.regulation == regulation.upper(),
                    PdfRecord.semester   == semester,
                )
            ).all()
            return [r.to_dict() for r in rows]

    def full_text_search(self, query: str) -> list[dict]:
        """
        Broad LIKE search across title, subject, and filename.
        Useful for the main search bar.

        Args:
            query: Free-text search term.

        Returns:
            Union of matches on title, subject, filename.
        """
        log.debug("full_text_search: %r", query)
        pat = f"%{query}%"
        with self._db._Session() as session:
            rows = session.scalars(
                select(PdfRecord).where(
                    or_(
                        PdfRecord.title.ilike(pat),
                        PdfRecord.subject.ilike(pat),
                        PdfRecord.filename.ilike(pat),
                    )
                ).limit(200)
            ).all()
            return [r.to_dict() for r in rows]

    # ══════════════════════════════════════════════════════════
    # ANALYTICS
    # ══════════════════════════════════════════════════════════

    def get_analytics(self) -> dict:
        """
        Return comprehensive database analytics.

        Returns dict with:
            total, classified, unclassified,
            by_university, by_category, by_regulation,
            by_semester, by_degree
        """
        stats = self._db.get_stats()
        log.info("Analytics: total=%d", stats.get("total", 0))
        return stats

    # ══════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ══════════════════════════════════════════════════════════

    def _like_search(self, col, query: str) -> list[dict]:
        """LIKE search on a single column."""
        log.debug("like_search: col=%s q=%r", col.key, query)
        with self._db._Session() as session:
            rows = session.scalars(
                select(PdfRecord).where(col.ilike(f"%{query}%")).limit(500)
            ).all()
            return [r.to_dict() for r in rows]

    def _exact_search(self, col, value: str) -> list[dict]:
        """Exact-match search on a single column."""
        log.debug("exact_search: col=%s val=%r", col.key, value)
        with self._db._Session() as session:
            rows = session.scalars(
                select(PdfRecord).where(col == value).limit(500)
            ).all()
            return [r.to_dict() for r in rows]
