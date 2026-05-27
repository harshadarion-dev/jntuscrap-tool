/**
 * dashboard.js — JNTUScrapTool Live Dashboard Client
 * ===================================================
 * Connects to /ws/progress WebSocket, dispatches UI updates,
 * and handles all button interactions.
 */

"use strict";

// ── State ─────────────────────────────────────────────────────
let wsConn = null;
let wsRetry = 0;
let lastStatus = "idle";
let paused = false;

// ── DOM refs (assigned on DOMContentLoaded) ───────────────────
const $ = id => document.getElementById(id);

// ══════════════════════════════════════════════════════════════
// WEBSOCKET
// ══════════════════════════════════════════════════════════════

function connectWS() {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    wsConn = new WebSocket(`${protocol}://${location.host}/ws/progress`);

    wsConn.onopen = () => {
        wsRetry = 0;
        setWSDot(true);
    };

    wsConn.onmessage = evt => {
        try {
            const data = JSON.parse(evt.data);
            applyState(data);
        } catch (e) { /* ignore parse error */ }
    };

    wsConn.onclose = wsConn.onerror = () => {
        setWSDot(false);
        const delay = Math.min(5000, 500 * Math.pow(2, wsRetry++));
        setTimeout(connectWS, delay);
    };
}

function setWSDot(connected) {
    const dot = $("ws-dot");
    if (dot) dot.className = "ws-dot" + (connected ? " connected" : "");
}

// ══════════════════════════════════════════════════════════════
// STATE APPLY
// ══════════════════════════════════════════════════════════════

function applyState(data) {
    // Overall progress
    const pct = data.overall_pct ?? 0;
    setEl("global-pct-text", pct.toFixed(1) + "%");
    setBar("global-bar", pct);

    // System status
    const status = data.system_status || "idle";
    updateStatusIndicator(status);

    // Phase bars
    const phases = data.phases || {};
    for (const [ph, info] of Object.entries(phases)) {
        setPhaseBar(ph, info);
    }

    // Counters
    const c = data.counters || {};
    setEl("cnt-links", fmt(c.links_found));
    setEl("cnt-cats", fmt(c.categories));
    setEl("cnt-posts", fmt(c.posts_found));
    setEl("cnt-fpages", fmt(c.file_pages));
    setEl("cnt-pdfs", fmt(c.pdfs_found));
    setEl("cnt-dl", fmt(c.pdfs_downloaded));
    setEl("cnt-failed", fmt(c.pdfs_failed));
    setEl("cnt-dup", fmt(c.pdfs_duplicate));
    setEl("cnt-storage", humanBytes(c.storage_bytes));
    setEl("cnt-speed", (c.speed_mbps || 0).toFixed(1) + " MB/s");
    setEl("cnt-eta", fmtEta(c.eta_seconds));
    setEl("url-ticker", c.current_url || "—");
    if (c.current_file) setEl("current-file", c.current_file);

    // Elapsed
    setEl("elapsed", fmtEta(data.elapsed_sec || 0));

    // Logs
    appendLogs(data.log_lines || []);

    // Button state
    const running = status === "running";
    const el = $("master-run-btn");
    if (el) el.disabled = running;

    lastStatus = status;
}

// ══════════════════════════════════════════════════════════════
// UI HELPERS
// ══════════════════════════════════════════════════════════════

function setEl(id, text) {
    const el = $(id);
    if (el) el.textContent = text;
}

function setBar(id, pct) {
    const el = $(id);
    if (el) el.style.width = Math.min(100, pct) + "%";
}

function fmt(n) {
    if (n === undefined || n === null) return "0";
    return Number(n).toLocaleString();
}

function humanBytes(b) {
    if (!b) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
    return b.toFixed(1) + " " + units[i];
}

function fmtEta(sec) {
    if (!sec || sec <= 0) return "—";
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function updateStatusIndicator(status) {
    const dot = $("status-dot");
    const text = $("system-status-text");
    if (dot) { dot.className = "status-dot " + status; }
    if (text) { text.textContent = status.charAt(0).toUpperCase() + status.slice(1); }
}

function setPhaseBar(ph, info) {
    const pct = info.percent ?? 0;
    const status = info.status || "idle";
    const label = info.label || `Phase ${ph}`;

    // Bar width + classes
    const barEl = $(`phase-bar-${ph}`);
    if (barEl) {
        barEl.style.width = pct + "%";
        barEl.className = `phase-bar ${status}`;
    }
    // Percentage text
    setEl(`phase-pct-${ph}`, pct.toFixed(0) + "%");
    // Badge
    const badge = $(`phase-badge-${ph}`);
    if (badge) {
        badge.textContent = status;
        badge.className = `phase-status-badge ${status}`;
    }
}

// ── Log viewer ─────────────────────────────────────────────────
let lastLogCount = 0;
function appendLogs(lines) {
    const viewer = $("log-viewer");
    if (!viewer) return;
    if (lines.length === lastLogCount) return;
    lastLogCount = lines.length;

    viewer.innerHTML = "";
    for (const line of lines.slice(-80)) {
        const div = document.createElement("div");
        div.className = "log-line " + classifyLog(line);
        div.textContent = line;
        viewer.appendChild(div);
    }
    viewer.scrollTop = viewer.scrollHeight;
}

function classifyLog(line) {
    if (!line) return "";
    const l = line.toLowerCase();
    if (l.includes("✓") || l.includes("success") || l.includes("done")) return "success";
    if (l.includes("✗") || l.includes("error") || l.includes("failed")) return "error";
    if (l.includes("⚠") || l.includes("warn") || l.includes("skip")) return "warn";
    if (l.includes("▶") || l.includes("phase") || l.includes("started")) return "phase";
    if (l.includes("info")) return "info";
    return "";
}

// ══════════════════════════════════════════════════════════════
// API CALLS
// ══════════════════════════════════════════════════════════════

async function triggerRun(phase) {
    try {
        const res = await fetch(`/run/${phase}`, { method: "POST" });
        const data = await res.json();
        if (!data.ok) showToast(data.error || "Error", "error");
    } catch (e) { showToast("Network error", "error"); }
}

async function sendControl(action) {
    try {
        await fetch(`/control/${action}`, { method: "POST" });
    } catch (e) { /* ignore */ }
}

async function loadStorageStats() {
    try {
        const res = await fetch("/api/stats");
        const data = await res.json();
        renderStorageTable(data.storage || {});
        renderDownloadStats(data.download_counts || {});
        if (data.db_records !== undefined) {
            setEl("db-records", fmt(data.db_records));
        }
    } catch (e) { /* ignore */ }
}

function renderStorageTable(storage) {
    const tbody = $("storage-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    const tree = storage.tree || {};
    for (const [uni, cats] of Object.entries(tree)) {
        for (const [cat, cnt] of Object.entries(cats)) {
            const tr = document.createElement("tr");
            tr.innerHTML = `<td>${uni}</td><td>${cat}</td><td style="text-align:right;color:var(--orange)">${cnt}</td>`;
            tbody.appendChild(tr);
        }
    }
    setEl("total-storage", humanBytes(storage.total_bytes || 0));
    setEl("total-files", fmt(storage.total_files || 0));
}

function renderDownloadStats(counts) {
    setEl("dl-success", fmt(counts.success || 0));
    setEl("dl-failed", fmt(counts.failed || 0));
    setEl("dl-dup", fmt(counts.duplicate || 0));
    setEl("dl-invalid", fmt(counts.invalid || 0));
}

// ══════════════════════════════════════════════════════════════
// QUICK SEARCH
// ══════════════════════════════════════════════════════════════

function quickSearch() {
    const val = ($("quick-search-input") || {}).value || "";
    if (val.trim()) {
        window.open(`/search?q=${encodeURIComponent(val.trim())}`, "_blank");
    }
}

// ══════════════════════════════════════════════════════════════
// TOAST
// ══════════════════════════════════════════════════════════════

function showToast(msg, type = "info") {
    const t = document.createElement("div");
    t.style.cssText = `
    position:fixed;bottom:24px;right:24px;
    background:${type === "error" ? "var(--red)" : "var(--surface2)"};
    color:${type === "error" ? "#fff" : "var(--text)"};
    padding:12px 20px;border-radius:8px;font-size:13px;
    border:1px solid var(--border);box-shadow:var(--shadow);
    z-index:9999;animation:fadeIn .2s ease;
  `;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

// ══════════════════════════════════════════════════════════════
// CLOCK
// ══════════════════════════════════════════════════════════════

function updateClock() {
    const el = $("live-clock");
    if (el) el.textContent = new Date().toLocaleTimeString();
}

// ══════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
    connectWS();
    loadStorageStats();
    setInterval(updateClock, 1000);
    setInterval(loadStorageStats, 10000);  // Refresh storage every 10s

    // Master run
    const runBtn = $("master-run-btn");
    if (runBtn) runBtn.addEventListener("click", () => triggerRun("full"));

    // Phase buttons
    for (let i = 1; i <= 6; i++) {
        const btn = $(`phase-btn-${i}`);
        if (btn) btn.addEventListener("click", () => triggerRun(String(i)));
    }

    // Control buttons
    $("btn-pause")?.addEventListener("click", () => { sendControl("pause"); paused = true; });
    $("btn-resume")?.addEventListener("click", () => { sendControl("resume"); paused = false; });
    $("btn-stop")?.addEventListener("click", () => sendControl("stop"));

    // Quick search enter key
    $("quick-search-input")?.addEventListener("keydown", e => {
        if (e.key === "Enter") quickSearch();
    });
    $("quick-search-btn")?.addEventListener("click", quickSearch);

    // Log tab buttons
    document.querySelectorAll("[data-log-phase]").forEach(btn => {
        btn.addEventListener("click", async () => {
            document.querySelectorAll("[data-log-phase]").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const phase = btn.dataset.logPhase;
            try {
                const res = await fetch(`/api/logs/${phase}`);
                const data = await res.json();
                const viewer = $("log-viewer");
                if (viewer) {
                    viewer.innerHTML = "";
                    for (const line of (data.lines || [])) {
                        const div = document.createElement("div");
                        div.className = "log-line " + classifyLog(line);
                        div.textContent = line;
                        viewer.appendChild(div);
                    }
                    viewer.scrollTop = viewer.scrollHeight;
                    lastLogCount = 0;  // Force refresh on next WS tick
                }
            } catch (e) { /* ignore */ }
        });
    });
});
