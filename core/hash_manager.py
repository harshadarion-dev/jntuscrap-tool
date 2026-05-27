"""
core/hash_manager.py — JNTUScrapTool File Hash & Dedup Manager
==============================================================
Computes SHA-256 and MD5 hashes of downloaded files for:
  - Duplicate detection (same content, different URL)
  - Integrity verification (re-check after download)
  - Re-download prevention (skip if hash already in registry)

Usage:
    from core.hash_manager import HashManager
    hm = HashManager()
    hm.load_registry()
    sha = hm.sha256_file(path)
    if hm.is_duplicate(sha):
        skip()
    else:
        hm.register(sha, path)
        hm.save_registry()
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import config
from core.logger import get_logger

log = get_logger("hash_manager", config.PHASE4_LOG)

# Read chunk size for hashing on-disk files
_HASH_CHUNK = 8 * 1024   # 8 KB


class HashManager:
    """
    Maintains a registry of SHA-256 hashes for all downloaded files.

    Registry format (JSON):
        { "<sha256_hex>": "<absolute_path_as_string>", ... }

    Thread-safety: NOT thread-safe. For parallel downloads, either:
      - Use a threading.Lock around register/is_duplicate, or
      - Let each thread accumulate its own set and merge at end.
    """

    def __init__(self) -> None:
        # sha256 → local path string
        self._registry: dict[str, str] = {}

    # ══════════════════════════════════════════════════════════
    # HASHING
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def sha256_file(path: Path) -> str:
        """
        Compute SHA-256 hash of a file on disk.

        Args:
            path: Path to the file.

        Returns:
            Hex string of the SHA-256 digest.

        Raises:
            FileNotFoundError: if the path doesn't exist.
        """
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(_HASH_CHUNK):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def md5_file(path: Path) -> str:
        """
        Compute MD5 hash of a file on disk (secondary integrity check).

        Args:
            path: Path to the file.

        Returns:
            Hex string of the MD5 digest.
        """
        h = hashlib.md5()
        with open(path, "rb") as f:
            while chunk := f.read(_HASH_CHUNK):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        """Compute SHA-256 of an in-memory bytes object (for small files)."""
        return hashlib.sha256(data).hexdigest()

    # ══════════════════════════════════════════════════════════
    # REGISTRY
    # ══════════════════════════════════════════════════════════

    def is_duplicate(self, sha256: str) -> bool:
        """
        Return True if this SHA-256 hash is already registered.

        Args:
            sha256: Hex string of the file's SHA-256 hash.

        Returns:
            True = already downloaded (duplicate), False = new file.
        """
        return sha256 in self._registry

    def register(self, sha256: str, path: Path) -> None:
        """
        Add a hash → path mapping to the in-memory registry.

        Args:
            sha256: SHA-256 hex digest.
            path:   Local path where the file was saved.
        """
        self._registry[sha256] = str(path)
        log.debug("Registered hash %s... → %s", sha256[:12], path.name)

    def get_path_for_hash(self, sha256: str) -> str | None:
        """Return the path of the file with this hash, or None."""
        return self._registry.get(sha256)

    @property
    def count(self) -> int:
        """Number of unique hashes registered."""
        return len(self._registry)

    # ══════════════════════════════════════════════════════════
    # PERSISTENCE
    # ══════════════════════════════════════════════════════════

    def load_registry(self, path: Path = config.HASH_REGISTRY_JSON) -> None:
        """
        Load the hash registry from disk (for resume support).

        Args:
            path: JSON file previously saved by save_registry().
        """
        if not path.exists():
            log.debug("No hash registry at %s — starting fresh.", path)
            return
        try:
            with open(path, encoding="utf-8") as f:
                self._registry = json.load(f)
            log.info("Hash registry loaded: %d hashes.", len(self._registry))
        except Exception as exc:
            log.warning("Failed to load hash registry: %s", exc)
            self._registry = {}

    def save_registry(self, path: Path = config.HASH_REGISTRY_JSON) -> None:
        """
        Persist the current registry to disk.

        Args:
            path: Destination JSON file path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._registry, f, indent=2, ensure_ascii=False)
        log.info("Hash registry saved: %d hashes → %s", len(self._registry), path)
