"""
core/download_tracker.py — JNTUScrapTool Download Index Manager
===============================================================
Maintains a persistent record of every download attempt, enabling:
  - Resume support  (skip already-downloaded files on re-run)
  - Progress export (downloads_index.json + download_history.csv)
  - Audit trail     (per-file status, size, hash, error reason)

DownloadRecord fields:
    title           — human-readable name
    university      — JNTUK / JNTUH / etc.
    category        — Question Papers / Academic Calendars / etc.
    semester        — 1-1 / 2-2 etc.
    regulation      — R23 / R20 etc.
    subject         — specific subject name
    post_url        — original post URL from Phase 2
    file_page_url   — WPDM file page URL
    download_url    — actual URL that was fetched (may be WPDM redirect)
    local_path      — where the file was saved on disk
    filename        — just the filename (for quick inspection)
    size_bytes      — file size in bytes after download
    size_human      — e.g. "2.4 MB"
    sha256          — SHA-256 hash of the file
    md5             — MD5 hash of the file
    download_status — "success" | "failed" | "duplicate" | "skipped" | "invalid"
    error           — error message if failed
    downloaded_at   — ISO timestamp

Usage:
    from core.download_tracker import DownloadTracker, DownloadRecord
    tracker = DownloadTracker()
    tracker.load_existing()
    tracker.add(record)
    tracker.save()
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import config
from core.logger import get_logger

log = get_logger("download_tracker", config.PHASE4_LOG)


@dataclass
class DownloadRecord:
    """One download attempt record."""
    title:           str
    download_url:    str                     # URL that was actually fetched
    download_status: str                     # success / failed / duplicate / skipped / invalid
    university:      Optional[str] = None
    category:        Optional[str] = None
    semester:        Optional[str] = None
    regulation:      Optional[str] = None
    subject:         Optional[str] = None
    post_url:        Optional[str] = None
    file_page_url:   Optional[str] = None
    local_path:      Optional[str] = None
    filename:        Optional[str] = None
    size_bytes:      Optional[int] = None
    size_human:      Optional[str] = None
    sha256:          Optional[str] = None
    md5:             Optional[str] = None
    error:           Optional[str] = None
    downloaded_at:   str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _human_size(size_bytes: int | None) -> str:
    """Convert byte count to human-readable string."""
    if size_bytes is None:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0          # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"


# CSV column order (for consistent, readable output)
_CSV_FIELDS = [
    "download_status", "title", "subject", "university", "category",
    "semester", "regulation", "filename", "size_human", "sha256",
    "download_url", "local_path", "error", "downloaded_at",
]


class DownloadTracker:
    """
    Accumulates DownloadRecord objects during a Phase 4 run and persists
    them to JSON and CSV for inspection and resume support.

    Resume logic:
      Call load_existing() before starting downloads.
      is_already_downloaded(url) returns True if a 'success' record exists
      for that URL — the downloader will then skip it.
    """

    def __init__(self) -> None:
        self._records: list[DownloadRecord] = []
        # Map of download_url → record (for O(1) resume checks)
        self._url_index: dict[str, DownloadRecord] = {}

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def add(self, record: DownloadRecord) -> None:
        """
        Add a completed download record to the tracker.

        Args:
            record: DownloadRecord from a completed (or failed) download.
        """
        # Fill in human-readable size
        if record.size_bytes is not None and not record.size_human:
            record.size_human = _human_size(record.size_bytes)
        if record.local_path:
            record.filename = Path(record.local_path).name

        self._records.append(record)
        self._url_index[record.download_url] = record
        log.debug(
            "[%s] %s → %s",
            record.download_status, record.filename or "?", record.size_human
        )

    def is_already_downloaded(self, url: str) -> bool:
        """
        Return True if this URL was successfully downloaded in a previous run.
        Used for resume support.

        Args:
            url: The download URL to check.
        """
        existing = self._url_index.get(url)
        return existing is not None and existing.download_status == "success"

    @property
    def records(self) -> list[DownloadRecord]:
        """All records accumulated so far."""
        return list(self._records)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self._records if r.download_status == "success")

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self._records if r.download_status == "failed")

    @property
    def duplicate_count(self) -> int:
        return sum(1 for r in self._records if r.download_status == "duplicate")

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self._records if r.download_status == "skipped")

    @property
    def invalid_count(self) -> int:
        return sum(1 for r in self._records if r.download_status == "invalid")

    # ══════════════════════════════════════════════════════════
    # PERSISTENCE
    # ══════════════════════════════════════════════════════════

    def load_existing(
        self,
        path: Path = config.DOWNLOADS_INDEX_JSON,
    ) -> None:
        """
        Load a previously saved downloads_index.json to enable resume support.

        Args:
            path: Path to the JSON file from a previous run.
        """
        if not path.exists():
            log.debug("No existing downloads index at %s.", path)
            return
        try:
            with open(path, encoding="utf-8") as f:
                data: list[dict] = json.load(f)
            for item in data:
                rec = DownloadRecord(**{
                    k: v for k, v in item.items()
                    if k in DownloadRecord.__dataclass_fields__
                })
                self._records.append(rec)
                self._url_index[rec.download_url] = rec
            log.info(
                "Loaded %d existing download records (%d successful).",
                len(self._records), self.success_count,
            )
        except Exception as exc:
            log.warning("Failed to load existing download index: %s", exc)

    def save(
        self,
        json_path: Path = config.DOWNLOADS_INDEX_JSON,
        csv_path:  Path = config.DOWNLOAD_HISTORY_CSV,
    ) -> None:
        """
        Persist all records to JSON and CSV.

        Args:
            json_path: Destination for downloads_index.json.
            csv_path:  Destination for download_history.csv.
        """
        self._save_json(json_path)
        self._save_csv(csv_path)

    def _save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(r) for r in self._records]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info("downloads_index.json → %d records", len(data))

    def _save_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=_CSV_FIELDS,
                extrasaction="ignore",
            )
            writer.writeheader()
            for rec in self._records:
                writer.writerow(asdict(rec))
        log.info("download_history.csv → %d rows", len(self._records))
