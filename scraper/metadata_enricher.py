"""
scraper/metadata_enricher.py — JNTUScrapTool Phase 5 Orchestrator
=================================================================
Merges Phase 3 (file_targets.json) + Phase 4 (downloads_index.json)
into a unified master metadata list, enriches each record with
TitleAnalyzer + SubjectNormalizer, assigns a unique ID, and flags
unclassified records.

Output: list of MasterRecord dicts → fed to MetadataExporter and Phase 6.

Usage:
    from scraper.metadata_enricher import MetadataEnricher
    me = MetadataEnricher()
    records = me.enrich()
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

import config
from core.logger import get_logger
from core.title_analyzer import TitleAnalyzer
from core.subject_normalizer import SubjectNormalizer

log        = get_logger("metadata_enricher", config.PHASE5_LOG)
err_log    = get_logger("metadata_errors",   config.METADATA_ERRORS_LOG)
unclf_log  = get_logger("unclassified",      config.UNCLASSIFIED_LOG)

# Fields required for a record to be "classified" (not flagged)
_REQUIRED_FIELDS = ("university", "category", "degree", "semester")


class MetadataEnricher:
    """
    Phase 5 orchestrator — merges, enriches, and classifies all records.

    Merge strategy:
      - Load all file_targets (Phase 3): the source of metadata + URLs
      - Load all downloads (Phase 4): adds local_path, sha256, size, status
      - Join by download_target / direct_pdf_url / external_url URL key
      - For targets not downloaded (invalid/failed): include anyway, mark status
      - Apply TitleAnalyzer + SubjectNormalizer
      - Assign UUID
      - Flag unclassified
    """

    def __init__(self) -> None:
        self.analyzer   = TitleAnalyzer()
        self.normalizer = SubjectNormalizer()

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def enrich(self) -> list[dict]:
        """
        Build the master metadata list from Phase 3 + 4 outputs.

        Returns:
            List of enriched MasterRecord dicts.
        """
        file_targets = self._load_json(config.FILE_TARGETS_JSON, "file_targets")
        downloads    = self._load_json(config.DOWNLOADS_INDEX_JSON, "downloads_index")

        # Build download index keyed by URL for O(1) lookup
        dl_by_url: dict[str, dict] = {}
        for dl in downloads:
            url = dl.get("download_url", "")
            if url:
                dl_by_url[url] = dl

        records: list[dict] = []
        unclassified_count  = 0

        for ft in file_targets:
            # 1. Find matching download record
            dl = self._find_download(ft, dl_by_url)

            # 2. Merge target + download fields
            merged = self._merge(ft, dl)

            # 3. Enrich via TitleAnalyzer
            enriched = self.analyzer.analyze(merged)

            # 4. Normalise subject
            raw_subject = enriched.get("subject") or ""
            enriched["subject"] = self.normalizer.normalize(raw_subject) or raw_subject or None

            # 5. Assign unique ID
            enriched["id"] = str(uuid.uuid4())

            # 6. Classify / flag
            enriched["classified"] = self._is_classified(enriched)
            if not enriched["classified"]:
                unclassified_count += 1
                unclf_log.warning(
                    "UNCLASSIFIED | %s | %s",
                    enriched.get("title", "?")[:80],
                    {f: enriched.get(f) for f in _REQUIRED_FIELDS},
                )

            records.append(enriched)

        log.info(
            "Enrichment complete: %d records, %d unclassified.",
            len(records), unclassified_count,
        )
        return records

    # ══════════════════════════════════════════════════════════
    # PRIVATE
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _load_json(path: Path, label: str) -> list[dict]:
        """Load a JSON list from disk. Returns [] if file doesn't exist."""
        if not path.exists():
            log.warning("%s not found at %s — Phase 5 will run with partial data.", label, path)
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        log.info("Loaded %d %s records.", len(data), label)
        return data

    @staticmethod
    def _find_download(ft: dict, dl_by_url: dict[str, dict]) -> dict | None:
        """Find the matching Phase 4 download record for a Phase 3 file target."""
        for key in ("download_target", "direct_pdf_url", "external_url"):
            url = ft.get(key) or ""
            if url and url in dl_by_url:
                return dl_by_url[url]
        return None

    @staticmethod
    def _merge(ft: dict, dl: dict | None) -> dict:
        """
        Merge a FileTarget dict with an optional DownloadRecord dict.
        Phase 3 fields form the base; Phase 4 adds local_path / sha256 / size / status.
        """
        merged = dict(ft)   # Phase 3 base

        if dl:
            # Add Phase 4 fields (don't overwrite existing non-None values)
            for key in ("local_path", "sha256", "md5", "size_bytes",
                        "size_human", "download_status", "downloaded_at", "filename"):
                val = dl.get(key)
                if val is not None:
                    merged[key] = val

            # Prefer Phase 4 title if Phase 3 title is very short
            dl_title = dl.get("title") or ""
            ft_title = merged.get("title") or ""
            if len(dl_title) > len(ft_title):
                merged["title"] = dl_title
        else:
            merged["download_status"] = "not_downloaded"

        return merged

    @staticmethod
    def _is_classified(record: dict) -> bool:
        """Return True if the record has all required classification fields."""
        return all(
            record.get(f) for f in _REQUIRED_FIELDS
        )
