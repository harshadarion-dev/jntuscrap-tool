"""
api/dashboard_api.py — JNTUScrapTool FastAPI Dashboard Backend
==============================================================
Serves the dashboard HTML, streams live progress over WebSocket,
and provides REST endpoints for control and search.

Endpoints:
    GET  /                    → index.html (main dashboard)
    GET  /search              → search.html (search portal)
    WS   /ws/progress         → streams ProgressState JSON ~4/s
    POST /run/{phase}         → trigger phase (1-6 or "full")
    POST /control/{action}    → pause | resume | stop
    GET  /api/stats           → full stats JSON
    GET  /api/logs/{phase}    → last 100 lines of phase log
    GET  /api/search          → SearchEngine query proxy

Usage:
    import uvicorn
    from api.dashboard_api import app
    uvicorn.run(app, host="127.0.0.1", port=8000)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

import config
from control_center import ControlCenter

# ── Singletons ────────────────────────────────────────────────────────
BASE = Path(__file__).parent.parent
cc   = ControlCenter()

app  = FastAPI(title="JNTUScrapTool Dashboard", docs_url=None, redoc_url=None)

# Static files
app.mount(
    "/static",
    StaticFiles(directory=str(BASE / "dashboard" / "static")),
    name="static",
)
# Expose storage directory so downloaded PDFs can be opened in browser
if (BASE / "storage").exists():
    app.mount(
        "/storage",
        StaticFiles(directory=str(BASE / "storage")),
        name="storage",
    )

templates = Jinja2Templates(directory=str(BASE / "dashboard" / "templates"))


# ══════════════════════════════════════════════════════════════════════
# PAGE ROUTES
# ══════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main control dashboard."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    """Serve the academic search portal."""
    return templates.TemplateResponse("search.html", {"request": request})


# ══════════════════════════════════════════════════════════════════════
# WEBSOCKET — LIVE PROGRESS STREAM
# ══════════════════════════════════════════════════════════════════════

@app.websocket("/ws/progress")
async def ws_progress(websocket: WebSocket):
    """
    Stream ProgressState to connected browser clients.
    Sends a JSON snapshot every 250 ms.
    New log lines are included in each snapshot (last 50).
    """
    await websocket.accept()
    try:
        while True:
            payload = json.dumps(cc.state.to_dict())
            await websocket.send_text(payload)
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# CONTROL ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.post("/run/{phase}")
async def run_phase(phase: str):
    """
    Trigger a phase run.

    Args:
        phase: "full" | "1" | "2" | "3" | "4" | "5" | "6"
    """
    if cc.is_running:
        return JSONResponse({"ok": False, "error": "Already running"}, status_code=409)

    loop = asyncio.get_event_loop()
    if phase == "full":
        loop.run_in_executor(None, cc.run_full_scrape)
        return {"ok": True, "message": "Full scrape started."}

    try:
        ph = int(phase)
        if ph not in range(1, 7):
            raise ValueError
    except ValueError:
        return JSONResponse({"ok": False, "error": "Invalid phase"}, status_code=400)

    loop.run_in_executor(None, cc.run_phase, ph)
    return {"ok": True, "message": f"Phase {ph} started."}


@app.post("/control/{action}")
async def control(action: str):
    """
    Control the running pipeline.

    Args:
        action: "pause" | "resume" | "stop"
    """
    if action == "pause":
        cc.pause()
        return {"ok": True, "status": "paused"}
    elif action == "resume":
        cc.resume()
        return {"ok": True, "status": "running"}
    elif action == "stop":
        cc.stop()
        return {"ok": True, "status": "stopped"}
    return JSONResponse({"ok": False, "error": "Unknown action"}, status_code=400)


# ══════════════════════════════════════════════════════════════════════
# API — STATS, LOGS, SEARCH
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/stats")
async def api_stats():
    """Return the full stats snapshot (state + storage + DB count)."""
    return cc.get_stats()


@app.get("/api/logs/{phase}")
async def api_logs(phase: str, lines: int = 100):
    """Return the last N lines of a phase log file."""
    return {"phase": phase, "lines": cc.get_log_tail(phase, lines)}


@app.get("/api/search")
async def api_search(
    q:          Optional[str] = None,
    subject:    Optional[str] = None,
    semester:   Optional[str] = None,
    regulation: Optional[str] = None,
    university: Optional[str] = None,
    category:   Optional[str] = None,
):
    """
    SearchEngine proxy.
    Returns list of matching PdfRecord dicts.
    """
    try:
        from database.db_manager import DatabaseManager
        from database.search_engine import SearchEngine
        db = DatabaseManager()
        db.create_tables()
        se = SearchEngine(db)

        if subject:
            results = se.search_by_subject(subject)
        elif semester:
            results = se.search_by_semester(semester)
        elif regulation:
            results = se.search_by_regulation(regulation)
        elif university:
            results = se.search_by_university(university)
        elif category:
            results = se.search_by_category(category)
        elif q:
            results = se.full_text_search(q)
        else:
            results = []

        db.close()
        return {"results": results, "count": len(results)}
    except Exception as exc:
        return JSONResponse({"results": [], "count": 0, "error": str(exc)})


@app.get("/api/analytics")
async def api_analytics():
    """Return DB analytics (total, by_university, by_category, etc.)."""
    try:
        from database.db_manager import DatabaseManager
        from database.search_engine import SearchEngine
        db = DatabaseManager()
        db.create_tables()
        se = SearchEngine(db)
        stats = se.get_analytics()
        db.close()
        return stats
    except Exception as exc:
        return JSONResponse({"error": str(exc)})
