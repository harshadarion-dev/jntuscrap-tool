"""
scraper/file_validator.py — JNTUScrapTool PDF File Validator
=============================================================
Validates HTTP responses and on-disk files to ensure they contain
a real, non-corrupted PDF and not an HTML ad-redirect, empty stub,
or JavaScript disguise.

Validation strategies (in order):
  1. Content-Type header check (response level — before writing disk)
  2. Magic bytes check (first 4 bytes == b'%PDF')
  3. Minimum size threshold
  4. HTML-disguise detection (file content starts with <html or <!DOCTYPE)

Usage:
    from scraper.file_validator import FileValidator, ValidationResult
    fv = FileValidator()
    result = fv.validate_response(response)
    if result.ok:
        # safe to write to disk
    result2 = fv.validate_file(path)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

import config
from core.logger import get_logger

log = get_logger("file_validator", config.FILE_VALIDATION_LOG)

# PDF magic bytes (first 4 bytes of every valid PDF)
_PDF_MAGIC = b"%PDF"

# HTML markers that indicate an ad-redirect / fake download
_HTML_MARKERS = (
    b"<!doctype", b"<html", b"<HTML", b"<!DOCTYPE",
    b"<head", b"<HEAD",
)


@dataclass
class ValidationResult:
    """
    Result of a file validation check.

    Attributes:
        ok:     True if the file/response passed all checks.
        reason: Human-readable explanation when ok=False.
    """
    ok:     bool
    reason: Optional[str] = None

    def __bool__(self) -> bool:
        return self.ok


class FileValidator:
    """
    Multi-stage validator for PDF downloads.

    Call validate_response() before writing bytes to disk (fast, header-only).
    Call validate_file() after writing to disk (thorough, reads file header).
    """

    # ══════════════════════════════════════════════════════════
    # RESPONSE-LEVEL VALIDATION (before writing to disk)
    # ══════════════════════════════════════════════════════════

    def validate_response(self, resp: requests.Response) -> ValidationResult:
        """
        Validate a streamed HTTP response before consuming its content.

        Checks:
          1. HTTP status code (must be 2xx)
          2. Content-Type header (must not be HTML/JS)

        Args:
            resp: requests.Response object (stream not yet consumed).

        Returns:
            ValidationResult(ok=True) if safe to download.
        """
        # ── Status code ──────────────────────────────────────
        if not resp.ok:
            reason = f"HTTP {resp.status_code}"
            log.warning("Bad status %s for %s", resp.status_code, resp.url)
            return ValidationResult(ok=False, reason=reason)

        # ── Content-Type ─────────────────────────────────────
        ct = resp.headers.get("Content-Type", "").lower().split(";")[0].strip()

        if ct in config.BAD_CONTENT_TYPES:
            reason = f"Bad Content-Type: {ct}"
            log.warning("Rejected content type '%s' for %s", ct, resp.url)
            return ValidationResult(ok=False, reason=reason)

        # Allow generic binary/octet-stream — rely on magic bytes later
        log.debug("Response OK: status=%d ct='%s'", resp.status_code, ct)
        return ValidationResult(ok=True)

    # ══════════════════════════════════════════════════════════
    # FILE-LEVEL VALIDATION (after writing to disk)
    # ══════════════════════════════════════════════════════════

    def validate_file(self, path: Path) -> ValidationResult:
        """
        Validate a file that has been written to disk.

        Checks (in order):
          1. File exists and is not empty
          2. Minimum byte threshold (config.PDF_MIN_BYTES)
          3. Magic bytes = %PDF (not HTML or empty)
          4. Not an HTML-disguised redirect

        Args:
            path: Path to the downloaded file.

        Returns:
            ValidationResult(ok=True) if file is a valid PDF.
        """
        # ── Existence ────────────────────────────────────────
        if not path.exists():
            return ValidationResult(ok=False, reason="File not found on disk")

        size = path.stat().st_size

        # ── Empty file ────────────────────────────────────────
        if size == 0:
            log.warning("Empty file: %s", path.name)
            return ValidationResult(ok=False, reason="Empty file (0 bytes)")

        # ── Minimum size ──────────────────────────────────────
        if size < config.PDF_MIN_BYTES:
            reason = f"File too small: {size} bytes (min {config.PDF_MIN_BYTES})"
            log.warning("%s — %s", path.name, reason)
            return ValidationResult(ok=False, reason=reason)

        # ── Read file header ──────────────────────────────────
        with open(path, "rb") as f:
            header = f.read(512)   # enough for magic check + HTML detection

        # ── PDF magic bytes ───────────────────────────────────
        if header[:4] == _PDF_MAGIC:
            log.debug("Valid PDF magic bytes: %s (%d bytes)", path.name, size)
            return ValidationResult(ok=True)

        # ── HTML disguise detection ───────────────────────────
        header_lower = header.lower()
        for marker in _HTML_MARKERS:
            if header_lower.startswith(marker.lower()):
                reason = "File is HTML (ad-redirect or fake download)"
                log.warning("%s — %s", path.name, reason)
                return ValidationResult(ok=False, reason=reason)

        # ── Unknown binary ────────────────────────────────────
        # Could be a valid PDF with a non-standard header offset (rare)
        # Do a deeper scan of first 1024 bytes
        with open(path, "rb") as f:
            deeper = f.read(1024)
        if _PDF_MAGIC in deeper:
            log.debug("PDF magic found at offset > 0 in %s — accepting.", path.name)
            return ValidationResult(ok=True)

        reason = f"Not a PDF — first bytes: {header[:8]!r}"
        log.warning("%s — %s", path.name, reason)
        return ValidationResult(ok=False, reason=reason)

    def validate_bytes(self, data: bytes) -> ValidationResult:
        """
        Validate a bytes object (e.g. small file loaded fully in memory).

        Args:
            data: Raw file bytes.

        Returns:
            ValidationResult.
        """
        if not data:
            return ValidationResult(ok=False, reason="Empty bytes")
        if len(data) < config.PDF_MIN_BYTES:
            return ValidationResult(ok=False, reason=f"Too small: {len(data)} bytes")
        if data[:4] == _PDF_MAGIC:
            return ValidationResult(ok=True)
        if _PDF_MAGIC in data[:1024]:
            return ValidationResult(ok=True)
        header_lower = data[:64].lower()
        for marker in _HTML_MARKERS:
            if marker.lower() in header_lower:
                return ValidationResult(ok=False, reason="HTML disguise")
        return ValidationResult(ok=False, reason=f"Not a PDF: {data[:8]!r}")
