"""
scraper/pdf_downloader.py — JNTUScrapTool PDF Download Engine
=============================================================
Downloads every Phase 3 FileTarget to local storage with:
  - Parallel execution (ThreadPoolExecutor)
  - Streamed writes (never loads full PDF into RAM)
  - Temp-file-then-atomic-move pattern (crash-safe)
  - Content-Type validation before consuming body
  - Magic-byte validation after writing
  - SHA-256 dedup (same content downloaded twice → skip)
  - Resume support (loads prior download index on start)
  - Retry and exponential backoff per file
  - Rich progress logging per thread

Download URL priority per target:
  1. download_target  — WPDM direct URL (preferred)
  2. direct_pdf_url   — Plain .pdf link
  3. external_url     — Google Drive / other host

Usage:
    from scraper.pdf_downloader import PDFDownloader
    dl = PDFDownloader(session)
    dl.run(targets, workers=4)
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests

import config
from core.logger import get_logger
from core.session_manager import SessionManager
from core.naming_engine import NamingEngine
from core.storage_router import StorageRouter
from core.hash_manager import HashManager
from core.download_tracker import DownloadTracker, DownloadRecord
from scraper.file_validator import FileValidator

log = get_logger("pdf_downloader", config.DOWNLOAD_LOG)
err_log = get_logger("download_errors", config.DOWNLOAD_ERRORS_LOG)

# Retry settings for individual downloads
_MAX_RETRIES   = 4
_RETRY_BACKOFF = 2.0   # seconds; doubled each retry


class PDFDownloader:
    """
    Orchestrates parallel PDF downloading for all Phase 3 file targets.

    Components used:
        NamingEngine    — generates safe filenames
        StorageRouter   — maps metadata to storage path
        HashManager     — SHA-256 dedup + integrity
        DownloadTracker — records and persists all download results
        FileValidator   — validates responses and on-disk files

    Thread safety:
        Each worker thread uses its OWN requests.Session (created per-thread
        from the same config) to avoid shared session state issues.
        HashManager and DownloadTracker access is protected by _lock.
    """

    def __init__(self, session: SessionManager) -> None:
        self._base_session = session       # Used for config/headers reference only
        self.naming        = NamingEngine()
        self.router        = StorageRouter()
        self.hasher        = HashManager()
        self.tracker       = DownloadTracker()
        self.validator     = FileValidator()
        self._lock         = threading.Lock()  # Guards hasher + tracker

        # Load prior state for resume support
        self.tracker.load_existing()
        self.hasher.load_registry()

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def run(
        self,
        targets:  list[dict],
        workers:  int = config.DOWNLOAD_WORKERS,
        limit:    int | None = None,
    ) -> None:
        """
        Download all targets in parallel using a thread pool.

        Args:
            targets: List of FileTarget dicts from file_targets.json.
            workers: Number of parallel download threads.
            limit:   If set, only process first N targets (testing).
        """
        if limit:
            targets = targets[:limit]

        # Pre-filter: skip targets with no usable URL
        actionable = [t for t in targets if self._pick_url(t)]
        skipped_no_url = len(targets) - len(actionable)
        if skipped_no_url:
            log.warning("Skipping %d targets with no download URL.", skipped_no_url)

        log.info(
            "Starting download of %d target(s) with %d worker(s).",
            len(actionable), workers,
        )

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dl") as pool:
            futures = {
                pool.submit(self._download_one, t): t
                for t in actionable
            }
            for future in as_completed(futures):
                target = futures[future]
                try:
                    record = future.result()
                    log.info(
                        "[%s] %s (%s)",
                        record.download_status,
                        record.filename or "?",
                        record.size_human or "?",
                    )
                except Exception as exc:
                    url = self._pick_url(target) or "unknown"
                    err_log.error("Unhandled error for %s: %s", url, exc)

        self.tracker.save()
        self.hasher.save_registry()
        log.info(
            "Phase 4 complete — success:%d  failed:%d  duplicate:%d  skipped:%d  invalid:%d",
            self.tracker.success_count,
            self.tracker.failed_count,
            self.tracker.duplicate_count,
            self.tracker.skipped_count,
            self.tracker.invalid_count,
        )

    # ══════════════════════════════════════════════════════════
    # PRIVATE — SINGLE DOWNLOAD
    # ══════════════════════════════════════════════════════════

    def _download_one(self, target: dict) -> DownloadRecord:
        """
        Download a single FileTarget. Called in a worker thread.

        Flow:
          1. Pick best URL
          2. Check resume index (skip if already downloaded)
          3. Stream GET with retry
          4. Validate Content-Type
          5. Write to temp file
          6. Validate magic bytes
          7. Hash + dedup check
          8. Move to final path
          9. Record result

        Args:
            target: FileTarget dict.

        Returns:
            DownloadRecord with final status.
        """
        url   = self._pick_url(target)
        title = target.get("title") or "Unknown"

        base_record = dict(
            title=title,
            download_url=url,
            university=target.get("university"),
            category=target.get("category"),
            semester=target.get("semester"),
            regulation=target.get("regulation"),
            subject=target.get("subject"),
            post_url=target.get("post_url"),
            file_page_url=target.get("file_page_url"),
        )

        # ── Resume check ──────────────────────────────────────
        with self._lock:
            already = self.tracker.is_already_downloaded(url)
        if already:
            log.debug("SKIP (already downloaded): %s", url[:80])
            return DownloadRecord(
                **base_record,
                download_status="skipped",
            )

        # ── Generate filename + path ───────────────────────────
        filename = self.naming.build_filename(target)
        dest_path = self.router.resolve(target, filename)

        # ── Resume: file already on disk with matching hash? ──
        if dest_path.exists():
            sha = self.hasher.sha256_file(dest_path)
            with self._lock:
                is_dup = self.hasher.is_duplicate(sha)
            if is_dup:
                log.debug("SKIP (file on disk): %s", filename)
                rec = DownloadRecord(
                    **base_record,
                    download_status="skipped",
                    local_path=str(dest_path),
                    filename=filename,
                    size_bytes=dest_path.stat().st_size,
                    sha256=sha,
                )
                with self._lock:
                    self.tracker.add(rec)
                return rec

        # ── Download with retry ───────────────────────────────
        resp = self._fetch_with_retry(url)
        if resp is None:
            rec = DownloadRecord(
                **base_record,
                download_status="failed",
                error="All retries exhausted",
            )
            with self._lock:
                self.tracker.add(rec)
            return rec

        # ── Validate response content-type ────────────────────
        vr = self.validator.validate_response(resp)
        if not vr:
            rec = DownloadRecord(
                **base_record,
                download_status="invalid",
                error=vr.reason,
            )
            with self._lock:
                self.tracker.add(rec)
            return rec

        # ── Stream to temp file ───────────────────────────────
        tmp_path = self._stream_to_temp(resp)
        if tmp_path is None:
            rec = DownloadRecord(
                **base_record,
                download_status="failed",
                error="Stream write failed",
            )
            with self._lock:
                self.tracker.add(rec)
            return rec

        try:
            # ── Validate file magic bytes ──────────────────────
            vf = self.validator.validate_file(tmp_path)
            if not vf:
                tmp_path.unlink(missing_ok=True)
                rec = DownloadRecord(
                    **base_record,
                    download_status="invalid",
                    error=vf.reason,
                )
                with self._lock:
                    self.tracker.add(rec)
                return rec

            # ── Hash + dedup check ────────────────────────────
            sha256 = self.hasher.sha256_file(tmp_path)
            md5    = self.hasher.md5_file(tmp_path)
            size   = tmp_path.stat().st_size

            with self._lock:
                is_dup = self.hasher.is_duplicate(sha256)

            if is_dup:
                existing_path = self.hasher.get_path_for_hash(sha256)
                tmp_path.unlink(missing_ok=True)
                log.debug(
                    "DUPLICATE content (sha256=%s...): %s already at %s",
                    sha256[:12], filename, existing_path,
                )
                rec = DownloadRecord(
                    **base_record,
                    download_status="duplicate",
                    sha256=sha256,
                    md5=md5,
                    size_bytes=size,
                    error=f"Duplicate of: {existing_path}",
                )
                with self._lock:
                    self.tracker.add(rec)
                return rec

            # ── Move temp → final destination ─────────────────
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_path), dest_path)

            # ── Register hash ─────────────────────────────────
            with self._lock:
                self.hasher.register(sha256, dest_path)

            rec = DownloadRecord(
                **base_record,
                download_status="success",
                local_path=str(dest_path),
                filename=filename,
                size_bytes=size,
                sha256=sha256,
                md5=md5,
            )
            with self._lock:
                self.tracker.add(rec)

            log.info("✓ %s (%d bytes) → %s", filename, size, dest_path.parent.name)
            return rec

        finally:
            # Ensure temp file is always cleaned up on exception too
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    # ══════════════════════════════════════════════════════════
    # PRIVATE — UTILITIES
    # ══════════════════════════════════════════════════════════

    def _fetch_with_retry(
        self,
        url: str,
    ) -> requests.Response | None:
        """
        Attempt to GET a URL up to _MAX_RETRIES times with exponential backoff.
        Uses a per-thread requests.Session (thread-safe, avoids shared state).

        Args:
            url: URL to download.

        Returns:
            Response object on success, None if all retries failed.
        """
        import requests as _req

        session = _req.Session()
        session.headers.update(config.DEFAULT_HEADERS)

        backoff = _RETRY_BACKOFF
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = session.get(
                    url,
                    stream=True,
                    timeout=config.DOWNLOAD_TIMEOUT,
                    allow_redirects=True,
                )
                if resp.ok:
                    return resp
                if resp.status_code in (403, 404, 410):
                    # Permanent failure — don't retry
                    err_log.warning(
                        "Permanent HTTP %d for %s", resp.status_code, url[:80]
                    )
                    return resp   # Return so caller sees status code
                err_log.warning(
                    "Attempt %d/%d: HTTP %d for %s — retrying in %.1f s",
                    attempt, _MAX_RETRIES, resp.status_code, url[:80], backoff,
                )
            except Exception as exc:
                err_log.warning(
                    "Attempt %d/%d: %s for %s — retrying in %.1f s",
                    attempt, _MAX_RETRIES, exc, url[:80], backoff,
                )

            if attempt < _MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2.0

        err_log.error("All %d retries failed for %s", _MAX_RETRIES, url[:80])
        session.close()
        return None

    def _stream_to_temp(self, resp: requests.Response) -> Path | None:
        """
        Stream the response body to a uniquely-named temp file in the
        download_cache directory. Uses a UUID suffix to avoid collisions
        between parallel threads.

        Args:
            resp: Streaming requests.Response (must not be consumed yet).

        Returns:
            Path to the temp file on success, None on write error.
        """
        tmp_name = f"dl_{uuid.uuid4().hex}.tmp"
        tmp_path = config.DOWNLOAD_CACHE_DIR / tmp_name

        try:
            config.DOWNLOAD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                    if chunk:  # Filter out keep-alive empty chunks
                        f.write(chunk)
            return tmp_path
        except Exception as exc:
            err_log.error("Stream write failed: %s", exc)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return None

    @staticmethod
    def _pick_url(target: dict) -> Optional[str]:
        """
        Select the best download URL from the target dict.

        Priority:
          1. download_target  — WPDM direct URL (confirmed working)
          2. direct_pdf_url   — bare .pdf link
          3. external_url     — Google Drive / Mediafire etc.

        Args:
            target: FileTarget dict.

        Returns:
            URL string or None if no usable URL found.
        """
        for key in ("download_target", "direct_pdf_url", "external_url"):
            val = (target.get(key) or "").strip()
            if val:
                return val
        return None
