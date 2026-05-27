"""
database/export_manager.py — JNTUScrapTool Master Index Exporter
================================================================
Converts the master database records to:
  - master_index.json  (flat array — API-ready)
  - master_index.csv   (spreadsheet-ready)
  - Hierarchical JSON  (optional — university → category → semester tree)

Usage:
    from database.export_manager import ExportManager
    em = ExportManager()
    em.to_json_flat(records, path)
    em.to_csv(records, path)
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from core.logger import get_logger

log = get_logger("export_manager", config.PHASE6_LOG)

# CSV column order for master_index.csv
_MASTER_CSV_FIELDS = [
    "id", "record_uuid", "title", "university", "category", "degree",
    "branch", "regulation", "semester", "subject",
    "exam_month", "exam_year", "academic_year", "exam_type",
    "download_status", "classified",
    "filename", "size_human", "local_path",
    "sha256", "pdf_url", "file_page_url", "post_url",
    "scraped_date", "downloaded_at",
]


class ExportManager:
    """
    Handles all export formats for Phase 6 master index data.
    """

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def to_json_flat(
        self,
        records: list[dict],
        path: Path = config.MASTER_INDEX_JSON,
    ) -> None:
        """
        Export as a flat JSON array with an ISO timestamp wrapper.

        Output shape:
            {
              "generated_at": "2026-04-28T...",
              "total": 42,
              "records": [ {...}, ... ]
            }

        Args:
            records: List of PdfRecord dicts (from db_manager.all_records()).
            path:    Destination JSON path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total": len(records),
            "records": [self._serialise(r) for r in records],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
        log.info("master_index.json → %d records", len(records))

    def to_csv(
        self,
        records: list[dict],
        path: Path = config.MASTER_INDEX_CSV,
    ) -> None:
        """
        Export as a flat CSV file.

        Args:
            records: List of PdfRecord dicts.
            path:    Destination CSV path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=_MASTER_CSV_FIELDS,
                extrasaction="ignore",
            )
            writer.writeheader()
            for rec in records:
                writer.writerow(self._serialise(rec))
        log.info("master_index.csv → %d rows", len(records))

    def to_json_hierarchical(
        self,
        records: list[dict],
        path: Path | None = None,
    ) -> dict:
        """
        Build a hierarchical JSON tree:
            university → category → semester → [records]

        Useful for building a browsable academic navigator.

        Args:
            records: List of PdfRecord dicts.
            path:    If given, also write to this file.

        Returns:
            The hierarchical dict object.
        """
        tree: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

        for rec in records:
            uni = rec.get("university") or "Unknown"
            cat = rec.get("category")  or "Uncategorised"
            sem = rec.get("semester")  or "Unknown"
            tree[uni][cat][sem].append(self._serialise(rec))

        # Convert defaultdicts to regular dicts for JSON serialisation
        result: dict = {
            uni: {
                cat: dict(sems)
                for cat, sems in cats.items()
            }
            for uni, cats in tree.items()
        }

        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False, default=str)
            log.info("Hierarchical JSON → %s", path.name)

        return result

    # ══════════════════════════════════════════════════════════
    # PRIVATE
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _serialise(rec: dict) -> dict:
        """Convert any non-JSON-serialisable values (datetime, Path) to strings."""
        result: dict = {}
        for k, v in rec.items():
            if isinstance(v, datetime):
                result[k] = v.isoformat()
            elif isinstance(v, Path):
                result[k] = str(v)
            else:
                result[k] = v
        return result
