"""
database/models.py — JNTUScrapTool SQLAlchemy ORM Models
=========================================================
Defines the PdfRecord table schema for the master academic database.

Table: pdf_records
  - Unique constraint on sha256 (prevents duplicate files)
  - Composite index on (university, category) for common queries
  - Individual indexes on regulation, semester, subject for search

Compatible with both SQLite (local) and PostgreSQL (production).

Usage:
    from database.models import Base, PdfRecord
    # Use via DatabaseManager — do not instantiate directly
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Index, Integer, String, Boolean, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base — all models inherit from this."""
    pass


class PdfRecord(Base):
    """
    One academic file record in the master database.

    A record is uniquely identified by its sha256 hash, which prevents
    duplicate entries even when the same file appears at different URLs.

    Fields mirror the MasterRecord dict from Phase 5 with SQL-appropriate
    types. All metadata fields are nullable to accommodate incomplete records.
    """
    __tablename__ = "pdf_records"

    # ── Primary key ───────────────────────────────────────────
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Record UUID (from Phase 5 enrichment) ─────────────────
    record_uuid = Column(String(36), nullable=True, index=True)

    # ── Academic metadata ──────────────────────────────────────
    title         = Column(Text,       nullable=True)
    university    = Column(String(20), nullable=True, index=True)
    category      = Column(String(60), nullable=True, index=True)
    degree        = Column(String(30), nullable=True)
    branch        = Column(String(30), nullable=True)
    regulation    = Column(String(10), nullable=True, index=True)
    semester      = Column(String(10), nullable=True, index=True)
    subject       = Column(Text,       nullable=True, index=True)
    exam_month    = Column(String(15), nullable=True)
    exam_year     = Column(String(6),  nullable=True)
    academic_year = Column(String(10), nullable=True)
    exam_type     = Column(String(30), nullable=True)

    # ── Source URLs ────────────────────────────────────────────
    post_url      = Column(Text, nullable=True)
    file_page_url = Column(Text, nullable=True)
    pdf_url       = Column(Text, nullable=True)   # Final download URL

    # ── File info ──────────────────────────────────────────────
    local_path     = Column(Text,       nullable=True)
    filename       = Column(Text,       nullable=True)
    file_size      = Column(Integer,    nullable=True)   # bytes
    size_human     = Column(String(20), nullable=True)   # "2.4 MB"
    sha256         = Column(String(64), nullable=True, unique=True)
    md5            = Column(String(32), nullable=True)

    # ── Status / classification ────────────────────────────────
    download_status = Column(String(20), nullable=True)  # success/failed/etc.
    classified      = Column(Boolean,    default=True)

    # ── Timestamps ────────────────────────────────────────────
    scraped_date    = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
    )
    downloaded_at   = Column(String(40), nullable=True)

    # ── Composite indexes for common search patterns ───────────
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_sha256"),
        Index("ix_uni_cat",  "university", "category"),
        Index("ix_reg_sem",  "regulation", "semester"),
    )

    def __repr__(self) -> str:
        return (
            f"<PdfRecord id={self.id} uni={self.university!r} "
            f"sem={self.semester!r} subject={self.subject!r}>"
        )

    def to_dict(self) -> dict:
        """Return all columns as a plain dict."""
        return {
            c.name: getattr(self, c.name)
            for c in self.__table__.columns
        }
