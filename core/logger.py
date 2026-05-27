"""
core/logger.py — JNTUScrapTool Logging Setup
=============================================
Provides a factory function to create named loggers that write to:
  - A rotating file (per-phase or per-module)
  - The console (INFO level)
  - A shared errors.log for WARNING and above

Usage:
    from core.logger import get_logger
    log = get_logger("phase1", config.PHASE1_LOG)
    log.info("Starting Phase 1...")
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config


def get_logger(name: str, log_file: Path | None = None) -> logging.Logger:
    """
    Create (or retrieve) a named logger with:
      - Console output at INFO level
      - File output at DEBUG level (rotates at 5 MB, keeps 3 backups)
      - Shared errors.log for WARNING+ messages

    Args:
        name:     Logger name (e.g. "phase1", "session_manager")
        log_file: Path to the specific log file for this logger.
                  Defaults to config.SCRAPER_LOG if not given.

    Returns:
        Configured logging.Logger instance.
    """
    # ── Return existing logger if already configured ──────────
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Shared formatter
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── 1. Console Handler (INFO+) ────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # ── 2. Per-module File Handler (DEBUG+) ───────────────────
    target_log = log_file or config.SCRAPER_LOG
    target_log.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        filename=target_log,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    # ── 3. Shared Errors Log (WARNING+) ──────────────────────
    config.ERRORS_LOG.parent.mkdir(parents=True, exist_ok=True)
    error_handler = RotatingFileHandler(
        filename=config.ERRORS_LOG,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(fmt)
    logger.addHandler(error_handler)

    # Prevent messages from propagating to the root logger twice
    logger.propagate = False

    return logger
