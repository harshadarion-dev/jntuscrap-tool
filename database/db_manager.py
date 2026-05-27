"""
database/db_manager.py — JNTUScrapTool Database Manager
========================================================
SQLAlchemy-based database manager for the master academic PDF database.

Handles:
  - Schema creation (idempotent)
  - Single-record upsert (by sha256 or record_uuid)
  - Efficient bulk insert (dedup on sha256)
  - Analytics queries (counts per field)

Usage:
    from database.db_manager import DatabaseManager
    db = DatabaseManager()
    db.create_tables()
    db.bulk_insert(records)
    stats = db.get_stats()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError

import config
from core.logger import get_logger
from database.models import Base, PdfRecord

log     = get_logger("db_manager",  config.PHASE6_LOG)
err_log = get_logger("db_errors",   config.DATABASE_ERRORS_LOG)


class DatabaseManager:
    """
    Manages the SQLite (or PostgreSQL) database for the master index.

    All operations use SQLAlchemy Core/ORM and are compatible with
    both SQLite (for local use) and PostgreSQL (for production).

    Args:
        db_path: Path to SQLite file. Defaults to config.DATABASE_PATH.
                 Pass a PostgreSQL URL string for production deployment.
    """

    def __init__(self, db_path: Path | str = config.DATABASE_PATH) -> None:
        db_str = str(db_path)
        if not db_str.startswith("postgresql"):
            # Ensure parent directory exists for SQLite
            Path(db_str).parent.mkdir(parents=True, exist_ok=True)
            db_str = f"sqlite:///{db_str}"
        self._engine  = create_engine(db_str, echo=False)
        self._Session = sessionmaker(bind=self._engine)
        log.info("Database engine: %s", db_str[:60])

    # ══════════════════════════════════════════════════════════
    # SCHEMA
    # ══════════════════════════════════════════════════════════

    def create_tables(self) -> None:
        """
        Create all tables from model definitions (idempotent).
        Safe to call on every run — existing tables are not modified.
        """
        Base.metadata.create_all(self._engine)
        log.info("Tables created (or already exist).")

    # ══════════════════════════════════════════════════════════
    # WRITE OPERATIONS
    # ══════════════════════════════════════════════════════════

    def upsert_record(self, record: dict) -> PdfRecord | None:
        """
        Insert a record or update it if a record with the same sha256 exists.

        Args:
            record: MasterRecord dict from Phase 5.

        Returns:
            The inserted or updated PdfRecord ORM object, or None on error.
        """
        with self._Session() as session:
            try:
                sha256 = (record.get("sha256") or "").strip() or None
                existing = None
                if sha256:
                    existing = session.scalar(
                        select(PdfRecord).where(PdfRecord.sha256 == sha256)
                    )

                if existing:
                    # Update existing record
                    for key, val in self._to_orm_dict(record).items():
                        if val is not None:
                            setattr(existing, key, val)
                    session.commit()
                    log.debug("Updated record sha256=%s...", sha256[:12] if sha256 else "?")
                    return existing
                else:
                    row = PdfRecord(**self._to_orm_dict(record))
                    session.add(row)
                    session.commit()
                    session.refresh(row)
                    log.debug("Inserted record id=%s", row.id)
                    return row
            except IntegrityError as e:
                session.rollback()
                err_log.warning("Integrity error (duplicate?): %s", e)
                return None
            except Exception as e:
                session.rollback()
                err_log.error("Upsert failed: %s", e)
                return None

    def bulk_insert(self, records: list[dict]) -> tuple[int, int]:
        """
        Efficiently insert many records, skipping sha256 duplicates.

        Args:
            records: List of MasterRecord dicts (from Phase 5).

        Returns:
            (inserted_count, skipped_count) tuple.
        """
        inserted = 0
        skipped  = 0

        # Pre-load existing sha256 hashes for O(1) dedup
        with self._Session() as session:
            existing_hashes: set[str] = {
                row[0] for row in session.execute(
                    select(PdfRecord.sha256).where(PdfRecord.sha256.isnot(None))
                )
            }

        to_insert: list[dict] = []
        seen_in_batch: set[str] = set()

        for rec in records:
            sha = (rec.get("sha256") or "").strip()
            if sha and (sha in existing_hashes or sha in seen_in_batch):
                skipped += 1
                continue
            if sha:
                seen_in_batch.add(sha)
            to_insert.append(self._to_orm_dict(rec))

        # Batch insert in chunks of 500
        chunk_size = 500
        with self._Session() as session:
            for i in range(0, len(to_insert), chunk_size):
                chunk = to_insert[i : i + chunk_size]
                try:
                    session.bulk_insert_mappings(PdfRecord, chunk)
                    session.commit()
                    inserted += len(chunk)
                    log.debug("Bulk inserted chunk %d/%d", i + len(chunk), len(to_insert))
                except Exception as e:
                    session.rollback()
                    err_log.error("Bulk insert chunk failed: %s", e)
                    # Fall back to individual inserts for this chunk
                    for row_dict in chunk:
                        try:
                            session.add(PdfRecord(**row_dict))
                            session.commit()
                            inserted += 1
                        except IntegrityError:
                            session.rollback()
                            skipped += 1
                        except Exception as e2:
                            session.rollback()
                            err_log.warning("Row insert failed: %s", e2)
                            skipped += 1

        log.info("Bulk insert complete: %d inserted, %d skipped.", inserted, skipped)
        return inserted, skipped

    # ══════════════════════════════════════════════════════════
    # READ / ANALYTICS
    # ══════════════════════════════════════════════════════════

    def get_stats(self) -> dict[str, Any]:
        """
        Return count analytics for the database.

        Returns:
            Dict with keys: total, by_university, by_category,
            by_regulation, by_semester, by_degree, classified_count.
        """
        with self._Session() as session:
            total = session.scalar(select(func.count(PdfRecord.id))) or 0

            def _count_by(col) -> dict:
                rows = session.execute(
                    select(col, func.count(PdfRecord.id))
                    .group_by(col)
                    .order_by(func.count(PdfRecord.id).desc())
                ).fetchall()
                return {str(k or "Unknown"): v for k, v in rows}

            classified = session.scalar(
                select(func.count(PdfRecord.id)).where(PdfRecord.classified.is_(True))
            ) or 0

        return {
            "total":          total,
            "classified":     classified,
            "unclassified":   total - classified,
            "by_university":  _count_by(PdfRecord.university),
            "by_category":    _count_by(PdfRecord.category),
            "by_regulation":  _count_by(PdfRecord.regulation),
            "by_semester":    _count_by(PdfRecord.semester),
            "by_degree":      _count_by(PdfRecord.degree),
        }

    def all_records(self) -> list[dict]:
        """Return all records as plain dicts (for export)."""
        with self._Session() as session:
            rows = session.scalars(select(PdfRecord)).all()
            return [r.to_dict() for r in rows]

    def close(self) -> None:
        """Dispose the engine and free connections."""
        self._engine.dispose()
        log.debug("Database engine disposed.")

    # ══════════════════════════════════════════════════════════
    # PRIVATE
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _to_orm_dict(record: dict) -> dict:
        """
        Convert a flat MasterRecord dict to a PdfRecord-compatible dict.
        Maps known aliases and drops unknown keys.
        """
        col_names = {c.name for c in PdfRecord.__table__.columns}
        result: dict = {}

        # Direct field copy (matching column names)
        for key, val in record.items():
            if key in col_names:
                result[key] = val

        # Aliases / special mappings
        if "id" in result:
            # 'id' from Phase 5 is a UUID string; map to record_uuid
            result["record_uuid"] = result.pop("id")

        # pdf_url from download_target
        if "pdf_url" not in result:
            result["pdf_url"] = record.get("download_target") or record.get("download_url")

        # file_size from size_bytes
        if "file_size" not in result:
            result["file_size"] = record.get("size_bytes")

        return result
