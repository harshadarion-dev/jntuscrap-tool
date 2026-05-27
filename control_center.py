"""
control_center.py — JNTUScrapTool Phase 7 Control Center
=========================================================
Orchestrates all 6 scraping phases, streams live progress to the
FastAPI WebSocket layer, and supports pause / resume / stop.

Architecture:
  - Each phase is launched as subprocess.Popen(["python", "main.py", "phaseN"])
  - stdout/stderr lines are read and forwarded as LogEvent objects
  - Progress % is heuristically derived from log pattern matching
  - A shared ProgressState object is updated in real-time
  - WebSocket clients poll this state 4× per second

Usage (from FastAPI):
    cc = ControlCenter()
    asyncio.get_event_loop().run_in_executor(None, cc.run_full_scrape)
    state = cc.state   # Read from WebSocket handler
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

# ── Log pattern matchers for progress inference ──────────────────────
_PAT_PHASE2_PAGES = re.compile(r"Category scraped.*?(\d+)\s+post", re.I)
_PAT_PHASE3_TARGETS = re.compile(r"Targets.*?(\d+)", re.I)
_PAT_PHASE4_DL = re.compile(r"success:(\d+).*?failed:(\d+)", re.I)
_PAT_PHASE5_RECORDS = re.compile(r"Total:\s*(\d+)", re.I)
_PAT_PHASE6_INSERT = re.compile(r"inserted=(\d+)", re.I)
_PAT_CURRENT_URL = re.compile(r"https?://\S+")

# Phase weight in overall completion (must sum to 100)
_PHASE_WEIGHTS = {1: 5, 2: 20, 3: 25, 4: 30, 5: 10, 6: 10}
# Cumulative start percentages
_PHASE_STARTS  = {1: 0, 2: 5, 3: 25, 4: 50, 5: 80, 6: 90}


@dataclass
class PhaseProgress:
    """Per-phase progress info."""
    phase:    int
    label:    str
    status:   str   = "idle"     # idle / running / done / failed / skipped
    percent:  float = 0.0        # 0–100
    message:  str   = ""


@dataclass
class ProgressState:
    """
    Global shared state read by the WebSocket handler.
    All fields written by the background thread, read by async handlers.
    """
    overall_pct:   float = 0.0
    current_phase: int   = 0
    system_status: str   = "idle"    # idle / running / paused / stopped / done / error

    # Per-phase progress
    phases: dict[int, PhaseProgress] = field(default_factory=lambda: {
        i: PhaseProgress(phase=i, label=f"Phase {i}", status="idle")
        for i in range(1, 8)
    })

    # Live counters
    links_found:    int = 0
    categories:     int = 0
    posts_found:    int = 0
    file_pages:     int = 0
    pdfs_found:     int = 0
    pdfs_downloaded:int = 0
    pdfs_failed:    int = 0
    pdfs_duplicate: int = 0
    storage_bytes:  int = 0
    current_file:   str = ""
    current_url:    str = ""
    speed_mbps:     float = 0.0
    eta_seconds:    int   = 0

    # Log ring buffer (last 200 lines)
    log_lines:     list[str] = field(default_factory=list)

    # Timestamps
    started_at:    Optional[str] = None
    finished_at:   Optional[str] = None
    elapsed_sec:   float = 0.0

    def add_log(self, line: str) -> None:
        self.log_lines.append(line)
        if len(self.log_lines) > 200:
            self.log_lines = self.log_lines[-200:]

    def to_dict(self) -> dict:
        return {
            "overall_pct":     round(self.overall_pct, 1),
            "current_phase":   self.current_phase,
            "system_status":   self.system_status,
            "phases": {
                str(k): {
                    "phase":   v.phase,
                    "label":   v.label,
                    "status":  v.status,
                    "percent": round(v.percent, 1),
                    "message": v.message,
                }
                for k, v in self.phases.items()
            },
            "counters": {
                "links_found":     self.links_found,
                "categories":      self.categories,
                "posts_found":     self.posts_found,
                "file_pages":      self.file_pages,
                "pdfs_found":      self.pdfs_found,
                "pdfs_downloaded": self.pdfs_downloaded,
                "pdfs_failed":     self.pdfs_failed,
                "pdfs_duplicate":  self.pdfs_duplicate,
                "storage_bytes":   self.storage_bytes,
                "current_file":    self.current_file,
                "current_url":     self.current_url,
                "speed_mbps":      round(self.speed_mbps, 2),
                "eta_seconds":     self.eta_seconds,
            },
            "log_lines":   self.log_lines[-50:],   # Last 50 for WS payload
            "started_at":  self.started_at,
            "elapsed_sec": round(self.elapsed_sec, 1),
        }


class ControlCenter:
    """
    Orchestrates all phases, streams progress to ProgressState.

    Thread safety:
      - ProgressState is written by ONE background thread only.
      - FastAPI WebSocket handlers only READ state (no lock needed for reads).
      - _pause_event / _stop_event are threading.Event objects.
    """

    PHASE_LABELS = {
        1: "Homepage + Navbar",
        2: "Category Crawl",
        3: "Post + File Extraction",
        4: "PDF Download",
        5: "Metadata Engine",
        6: "Database Builder",
        7: "Search Portal",
    }

    def __init__(self) -> None:
        self.state       = ProgressState()
        self._pause_evt  = threading.Event()
        self._stop_evt   = threading.Event()
        self._run_lock   = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._start_time: float = 0.0

        # Initialise phase labels
        for i, lbl in self.PHASE_LABELS.items():
            if i in self.state.phases:
                self.state.phases[i].label = lbl

    # ══════════════════════════════════════════════════════════
    # PUBLIC CONTROL API
    # ══════════════════════════════════════════════════════════

    def run_full_scrape(self) -> None:
        """Start the full 6-phase scrape in a background thread."""
        self._launch(phases=[1, 2, 3, 4, 5, 6])

    def run_phase(self, phase: int) -> None:
        """Start a single phase in a background thread."""
        if phase not in range(1, 7):
            return
        self._launch(phases=[phase])

    def pause(self) -> None:
        """Signal the running phase to pause after current line."""
        self._pause_evt.set()
        self.state.system_status = "paused"

    def resume(self) -> None:
        """Resume a paused run."""
        self._pause_evt.clear()
        self.state.system_status = "running"

    def stop(self) -> None:
        """Terminate the running phase process."""
        self._stop_evt.set()
        self._pause_evt.clear()   # unblock any pause wait
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self.state.system_status = "stopped"

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ══════════════════════════════════════════════════════════
    # STATS + STORAGE
    # ══════════════════════════════════════════════════════════

    def get_storage_stats(self) -> dict:
        """Compute storage breakdown by university / category."""
        storage = config.STORAGE_DIR
        if not storage.exists():
            return {"total_files": 0, "total_bytes": 0, "tree": {}}

        total_files = 0
        total_bytes = 0
        tree: dict[str, dict[str, int]] = {}

        for pdf in storage.rglob("*.pdf"):
            try:
                size = pdf.stat().st_size
            except OSError:
                continue
            total_files += 1
            total_bytes += size
            parts = pdf.relative_to(storage).parts
            uni = parts[0] if len(parts) > 0 else "Unknown"
            cat = parts[1] if len(parts) > 1 else "Unknown"
            tree.setdefault(uni, {}).setdefault(cat, 0)
            tree[uni][cat] += 1

        self.state.storage_bytes = total_bytes
        return {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "total_human": self._human(total_bytes),
            "tree": tree,
        }

    def get_stats(self) -> dict:
        """Return combined progress + storage + DB stats."""
        import json

        stats = {
            "state":   self.state.to_dict(),
            "storage": self.get_storage_stats(),
        }

        # Downloads index counts
        dl_path = config.DOWNLOADS_INDEX_JSON
        if dl_path.exists():
            try:
                data = json.loads(dl_path.read_text(encoding="utf-8"))
                status_counts: dict[str, int] = {}
                for rec in data:
                    s = rec.get("download_status", "unknown")
                    status_counts[s] = status_counts.get(s, 0) + 1
                stats["download_counts"] = status_counts
            except Exception:
                pass

        # DB record count
        db_path = config.DATABASE_PATH
        if db_path.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(db_path))
                cnt = conn.execute("SELECT COUNT(*) FROM pdf_records").fetchone()[0]
                conn.close()
                stats["db_records"] = cnt
            except Exception:
                stats["db_records"] = 0

        return stats

    def get_log_tail(self, phase: str, lines: int = 100) -> list[str]:
        """Return the last N lines of a phase log file."""
        log_map = {
            "1": config.PHASE1_LOG,
            "2": config.PHASE2_LOG,
            "3": config.PHASE3_LOG,
            "4": config.PHASE4_LOG,
            "5": config.PHASE5_LOG,
            "6": config.PHASE6_LOG,
            "master": config.ERRORS_LOG,
            "download": config.DOWNLOAD_LOG,
        }
        path = log_map.get(str(phase))
        if not path or not path.exists():
            return []
        try:
            text   = path.read_text(encoding="utf-8", errors="replace")
            all_ln = text.splitlines()
            return all_ln[-lines:]
        except Exception:
            return []

    # ══════════════════════════════════════════════════════════
    # PRIVATE — THREAD MANAGEMENT
    # ══════════════════════════════════════════════════════════

    def _launch(self, phases: list[int]) -> None:
        """Launch phase sequence in a daemon thread."""
        if self.is_running:
            return  # Already running — ignore

        self._stop_evt.clear()
        self._pause_evt.clear()
        self._reset_state(phases)

        self._thread = threading.Thread(
            target=self._run_phases,
            args=(phases,),
            daemon=True,
        )
        self._thread.start()

    def _reset_state(self, phases: list[int]) -> None:
        """Reset relevant state fields before a new run."""
        s = self.state
        s.overall_pct   = 0.0
        s.current_phase = phases[0] if phases else 0
        s.system_status = "running"
        s.started_at    = datetime.now().isoformat()
        s.finished_at   = None
        s.log_lines     = []
        s.pdfs_downloaded = 0
        s.pdfs_failed   = 0
        s.pdfs_duplicate = 0

        for ph in phases:
            if ph in s.phases:
                s.phases[ph].status  = "idle"
                s.phases[ph].percent = 0.0
                s.phases[ph].message = ""
        self._start_time = time.time()

    _proc: Optional[subprocess.Popen] = None  # type: ignore[assignment]

    def _run_phases(self, phases: list[int]) -> None:
        """Background thread: iterate phases, run each via subprocess."""
        try:
            for ph in phases:
                if self._stop_evt.is_set():
                    break
                self._run_single_phase(ph)
                if self._stop_evt.is_set():
                    break

            if self._stop_evt.is_set():
                self.state.system_status = "stopped"
            else:
                self.state.system_status = "done"
                self.state.overall_pct   = 100.0
                self.state.finished_at   = datetime.now().isoformat()
                self.state.add_log("✓ All phases complete.")

        except Exception as exc:
            self.state.system_status = "error"
            self.state.add_log(f"ERROR: {exc}")

    def _run_single_phase(self, phase: int) -> None:
        """Launch one phase subprocess, capture output, update state."""
        pp = self.state.phases[phase]
        pp.status  = "running"
        pp.percent = 0.0
        self.state.current_phase = phase
        self.state.add_log(f"▶ Starting Phase {phase}: {pp.label}")

        cmd  = [sys.executable, str(Path(__file__).parent / "main.py"), f"phase{phase}"]
        env  = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=str(Path(__file__).parent),
            )
            self._proc = proc

            for raw_line in proc.stdout:           # type: ignore[union-attr]
                line = raw_line.rstrip()
                if not line:
                    continue

                # Handle pause
                while self._pause_evt.is_set() and not self._stop_evt.is_set():
                    time.sleep(0.2)

                if self._stop_evt.is_set():
                    proc.terminate()
                    break

                # Forward to log buffer
                self.state.add_log(line)

                # Update counters from log patterns
                self._parse_line(phase, line)

                # Update elapsed
                self.state.elapsed_sec = time.time() - self._start_time

            proc.wait(timeout=10)
            ok = proc.returncode == 0

        except Exception as exc:
            self.state.add_log(f"Phase {phase} error: {exc}")
            ok = False
            pp.status  = "failed"
            pp.message = str(exc)
            return

        if ok:
            pp.status  = "done"
            pp.percent = 100.0
            pp.message = "Complete"
            self.state.add_log(f"✓ Phase {phase} done.")
        else:
            pp.status  = "failed"
            pp.message = f"Exit code {getattr(self._proc, 'returncode', '?')}"
            self.state.add_log(f"✗ Phase {phase} failed.")

        # Update overall %
        self._update_overall()

    # ══════════════════════════════════════════════════════════
    # PRIVATE — LOG LINE PARSING
    # ══════════════════════════════════════════════════════════

    def _parse_line(self, phase: int, line: str) -> None:
        """Extract progress signals from log output lines."""
        pp = self.state.phases[phase]

        # Extract any URL
        m = _PAT_CURRENT_URL.search(line)
        if m:
            self.state.current_url = m.group(0)[:120]

        if phase == 2:
            if "Post links saved" in line or "post_links" in line:
                pp.percent = min(pp.percent + 5, 95)
            m2 = re.search(r"(\d+)\s+post", line, re.I)
            if m2:
                self.state.posts_found = max(self.state.posts_found, int(m2.group(1)))

        elif phase == 3:
            if "file_targets" in line:
                m2 = re.search(r"(\d+)\s+target", line, re.I)
                if m2:
                    self.state.file_pages = int(m2.group(1))
                    pp.percent = min(pp.percent + 10, 95)
            if "Resolved" in line or "target" in line.lower():
                pp.percent = min(pp.percent + 3, 95)

        elif phase == 4:
            # success:2  failed:0  dup:0
            m2 = _PAT_PHASE4_DL.search(line)
            if m2:
                self.state.pdfs_downloaded = int(m2.group(1))
                self.state.pdfs_failed     = int(m2.group(2))
            # ✓ filename.pdf
            fn_match = re.search(r"✓\s+(\S+\.pdf)", line)
            if fn_match:
                self.state.current_file = fn_match.group(1)
                self.state.pdfs_downloaded += 1
                pp.percent = min(pp.percent + 2, 95)

        elif phase == 5:
            m2 = re.search(r"(\d+)\s+records", line, re.I)
            if m2:
                pp.percent = min(80, float(m2.group(1)) * 5)
                pp.message = f"{m2.group(1)} records enriched"

        elif phase == 6:
            m2 = re.search(r"inserted=(\d+)", line)
            if m2:
                pp.percent = 90.0
                pp.message = f"{m2.group(1)} records in DB"

    def _update_overall(self) -> None:
        """Recompute overall % from completed phases."""
        total = 0.0
        for ph, weight in _PHASE_WEIGHTS.items():
            pp = self.state.phases.get(ph)
            if pp:
                total += (pp.percent / 100.0) * weight
        self.state.overall_pct = min(total, 100.0)

    @staticmethod
    def _human(size_bytes: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes //= 1024
        return f"{size_bytes:.1f} TB"
