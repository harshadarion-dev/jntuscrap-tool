"""
scraper/metadata_exporter.py — JNTUScrapTool Phase 5 Exporter
=============================================================
Saves the master metadata list produced by MetadataEnricher to:
  - exports/master_metadata.json   (flat array, Phase 6 input)
  - exports/master_metadata.csv    (spreadsheet-ready)

Usage:
    from scraper.metadata_exporter import MetadataExporter
    me = MetadataExporter()
    me.save(records)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import config
from core.logger import get_logger

log = get_logger("metadata_exporter", config.PHASE5_LOG)

# CSV column order (meaningful, human-readable sequence)
_CSV_FIELDS = [
    "id", "title", "university", "category", "degree", "branch",
    "regulation", "semester", "subject", "exam_month", "exam_year",
    "academic_year", "exam_type", "classified",
    "download_status", "local_path", "filename", "size_human",
    "sha256", "post_url", "file_page_url", "download_target",
]


class MetadataExporter:
    """
    Saves enriched MasterRecord dicts to JSON and CSV.
    """

    def save(
        self,
        records:    list[dict],
        json_path:  Path = config.MASTER_METADATA_JSON,
        csv_path:   Path = config.MASTER_METADATA_CSV,
    ) -> None:
        """
        Write records to JSON and CSV.

        Args:
            records:   List of enriched MasterRecord dicts.
            json_path: Destination for master_metadata.json.
            csv_path:  Destination for master_metadata.csv.
        """
        self._save_json(records, json_path)
        self._save_csv(records, csv_path)

    @staticmethod
    def _save_json(records: list[dict], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        log.info("master_metadata.json → %d records", len(records))

    @staticmethod
    def _save_csv(records: list[dict], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Build effective field list (all CSV_FIELDS + any extra keys in records)
        extra_keys = []
        if records:
            for key in records[0]:
                if key not in _CSV_FIELDS and key not in extra_keys:
                    extra_keys.append(key)
        fieldnames = _CSV_FIELDS + extra_keys

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(records)
        log.info("master_metadata.csv → %d rows", len(records))
