"""
database/index_builder.py — JNTUScrapTool Phase 6 Orchestrator
==============================================================
Reads master_metadata.json from Phase 5, inserts all records into
the SQLite database, and triggers the export layer.

Usage:
    from database.index_builder import IndexBuilder
    ib = IndexBuilder()
    inserted, skipped = ib.build()
"""

from __future__ import annotations

import json
from pathlib import Path

import config
from core.logger import get_logger
from database.db_manager import DatabaseManager
from database.export_manager import ExportManager

log = get_logger("index_builder", config.PHASE6_LOG)


class IndexBuilder:
    """
    Phase 6 main orchestrator.

    Steps:
      1. Load master_metadata.json (from Phase 5)
      2. Create DB tables (idempotent)
      3. Bulk-insert records (SHA-256 dedup)
      4. Export master_index.json and master_index.csv

    Args:
        db_manager: Optional pre-configured DatabaseManager.
                    If None, uses config.DATABASE_PATH automatically.
    """

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db      = db_manager or DatabaseManager()
        self.exporter = ExportManager()

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def build(self) -> tuple[int, int]:
        """
        Full Phase 6 build: load → insert → export.

        Returns:
            (inserted_count, skipped_count) tuple from bulk_insert.
        """
        records = self._load_records()
        if not records:
            log.warning("No records to index — run phase5 first.")
            return 0, 0

        # Create tables (safe to re-run)
        self.db.create_tables()

        # Bulk insert with SHA-256 dedup
        log.info("Inserting %d records into database...", len(records))
        inserted, skipped = self.db.bulk_insert(records)
        log.info("DB insert: %d inserted, %d skipped.", inserted, skipped)

        # Fetch all DB records for export (includes auto-assigned IDs)
        all_records = self.db.all_records()
        log.info("Exporting %d total records...", len(all_records))

        self.exporter.to_json_flat(all_records, config.MASTER_INDEX_JSON)
        self.exporter.to_csv(all_records, config.MASTER_INDEX_CSV)

        return inserted, skipped

    # ══════════════════════════════════════════════════════════
    # PRIVATE
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _load_records() -> list[dict]:
        """Load master_metadata.json from Phase 5."""
        path = config.MASTER_METADATA_JSON
        if not path.exists():
            log.error("master_metadata.json not found at %s", path)
            return []
        with open(path, encoding="utf-8") as f:
            records = json.load(f)
        log.info("Loaded %d records from master_metadata.json.", len(records))
        return records
