"""
config.py — JNTUScrapTool Global Configuration
================================================
Central configuration file for all scraper settings, paths, headers,
timeouts, and university/category mappings.

All modules import from here so settings are changed in one place.
"""

from pathlib import Path

# ════════════════════════════════════════════════════════════════
# BASE PATHS
# ════════════════════════════════════════════════════════════════

# Root of the project (the folder containing this file)
BASE_DIR = Path(__file__).resolve().parent

# Sub-directories
STORAGE_DIR   = BASE_DIR / "storage"      # Where PDFs are saved
EXPORTS_DIR   = BASE_DIR / "exports"      # JSON / CSV index files
LOGS_DIR      = BASE_DIR / "logs"         # Log files
SNAPSHOTS_DIR = EXPORTS_DIR / "snapshots" # Raw HTML snapshots
DATABASE_DIR  = BASE_DIR / "database"     # SQLite DB directory

# Phase 2 raw data directories
RAW_DATA_DIR        = BASE_DIR / "raw_data"
RAW_CATEGORY_DIR    = RAW_DATA_DIR / "category_pages"
RAW_PAGINATION_DIR  = RAW_DATA_DIR / "pagination_pages"
RAW_POST_INDEX_DIR  = RAW_DATA_DIR / "post_indexes"

# Phase 3 raw data directories
RAW_POST_PAGES_DIR    = RAW_DATA_DIR / "post_pages"
RAW_NESTED_PAGES_DIR  = RAW_DATA_DIR / "nested_pages"
RAW_FILE_PAGES_DIR    = RAW_DATA_DIR / "file_pages"

# Phase 4 raw data directories
DOWNLOAD_CACHE_DIR    = RAW_DATA_DIR / "download_cache"   # Temp files during download

# Auto-create directories on import
for _dir in [
    STORAGE_DIR, EXPORTS_DIR, LOGS_DIR, SNAPSHOTS_DIR,
    RAW_DATA_DIR, RAW_CATEGORY_DIR, RAW_PAGINATION_DIR, RAW_POST_INDEX_DIR,
    RAW_POST_PAGES_DIR, RAW_NESTED_PAGES_DIR, RAW_FILE_PAGES_DIR,
    DOWNLOAD_CACHE_DIR, DATABASE_DIR,
]:
    _dir.mkdir(parents=True, exist_ok=True)

# ════════════════════════════════════════════════════════════════
# TARGET WEBSITE
# ════════════════════════════════════════════════════════════════

BASE_URL      = "https://www.jntufastupdates.com/"
FILES_BASE    = "https://files.jntufastupdates.com/"  # PDF host

# ════════════════════════════════════════════════════════════════
# HTTP SETTINGS
# ════════════════════════════════════════════════════════════════

# Default timeout in seconds (connect, read)
REQUEST_TIMEOUT = (10, 30)

# How many times to retry a failed request
RETRY_COUNT = 3

# Backoff factor for retries (wait = backoff * 2^attempt seconds)
RETRY_BACKOFF = 1.0

# HTTP status codes that trigger a retry
RETRY_ON_STATUS = [429, 500, 502, 503, 504]

# Polite delay between requests (seconds) — avoids hammering the server
REQUEST_DELAY = 1.5

# ════════════════════════════════════════════════════════════════
# DEFAULT HTTP HEADERS
# ════════════════════════════════════════════════════════════════
# fake_useragent will rotate the User-Agent; this is the fallback.

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# ════════════════════════════════════════════════════════════════
# UNIVERSITY CONFIGURATION
# ════════════════════════════════════════════════════════════════

# Recognized universities and their short codes
UNIVERSITIES = {
    "JNTUK": "JNTU Kakinada",
    "JNTUH": "JNTU Hyderabad",
    "JNTUA": "JNTU Anantapur",
    "JNTUGV": "JNTU Vizianagaram",
}

# Keyword → university code mapping (for classification)
# Used by the metadata parser to detect university from URLs/titles
UNIVERSITY_KEYWORDS = {
    "jntuk": "JNTUK",
    "kakinada": "JNTUK",
    "jntuh": "JNTUH",
    "hyderabad": "JNTUH",
    "jntua": "JNTUA",
    "anantapur": "JNTUA",
    "jntugv": "JNTUGV",
    "vizianagaram": "JNTUGV",
    "gv": "JNTUGV",
}

# ════════════════════════════════════════════════════════════════
# CATEGORY CONFIGURATION
# ════════════════════════════════════════════════════════════════

# All recognized academic categories
CATEGORIES = [
    "Academic Calendars",
    "Academic Regulations",
    "Question Papers",
    "Syllabus",
    "Time Tables",
    "Results",
    "Materials",
    "Notifications",
]

# Keyword → category mapping (for classification)
CATEGORY_KEYWORDS = {
    "academic-calendar":    "Academic Calendars",
    "academic-calendars":   "Academic Calendars",
    "regulation":           "Academic Regulations",
    "regulations":          "Academic Regulations",
    "question-paper":       "Question Papers",
    "question-papers":      "Question Papers",
    "syllabus":             "Syllabus",
    "time-table":           "Time Tables",
    "time-tables":          "Time Tables",
    "timetable":            "Time Tables",
    "result":               "Results",
    "results":              "Results",
    "material":             "Materials",
    "materials":            "Materials",
    "notification":         "Notifications",
    "notifications":        "Notifications",
}

# ════════════════════════════════════════════════════════════════
# OUTPUT FILE PATHS
# ════════════════════════════════════════════════════════════════

# Phase 1 outputs
NAVBAR_JSON      = EXPORTS_DIR / "navbar_structure.json"
HOMEPAGE_HTML    = SNAPSHOTS_DIR / "homepage_snapshot.html"

# Phase 2 outputs
CATEGORY_STRUCTURE_JSON = EXPORTS_DIR / "category_structure.json"
POST_LINKS_JSON         = EXPORTS_DIR / "post_links.json"

# Phase 3 outputs
FILE_TARGETS_JSON   = EXPORTS_DIR / "file_targets.json"
POST_METADATA_JSON  = EXPORTS_DIR / "post_metadata.json"
PHASE3_DEDUP_JSON   = EXPORTS_DIR / "phase3_dedup_state.json"   # Separate from Phase 2 dedup

# Phase 4 outputs
DOWNLOADS_INDEX_JSON  = EXPORTS_DIR / "downloads_index.json"
DOWNLOAD_HISTORY_CSV  = EXPORTS_DIR / "download_history.csv"
HASH_REGISTRY_JSON    = EXPORTS_DIR / "hash_registry.json"

# Phase 5 outputs
MASTER_METADATA_JSON  = EXPORTS_DIR / "master_metadata.json"
MASTER_METADATA_CSV   = EXPORTS_DIR / "master_metadata.csv"

# Phase 6 outputs
MASTER_INDEX_CSV      = EXPORTS_DIR / "master_index.csv"
MASTER_INDEX_JSON     = EXPORTS_DIR / "master_index.json"

# Database
DATABASE_PATH = DATABASE_DIR / "jntuscraptool.db"

# ════════════════════════════════════════════════════════════════
# LOG FILE PATHS
# ════════════════════════════════════════════════════════════════

PHASE1_LOG         = LOGS_DIR / "phase1.log"
PHASE2_LOG         = LOGS_DIR / "phase2.log"
PHASE3_LOG         = LOGS_DIR / "phase3.log"
PHASE4_LOG         = LOGS_DIR / "phase4.log"
PHASE5_LOG         = LOGS_DIR / "phase5.log"
PHASE6_LOG         = LOGS_DIR / "phase6.log"
ERRORS_LOG         = LOGS_DIR / "errors.log"
SCRAPER_LOG        = LOGS_DIR / "scraper.log"
DOWNLOAD_LOG       = LOGS_DIR / "downloads.log"
CATEGORY_ERRORS_LOG    = LOGS_DIR / "category_errors.log"
PAGINATION_ERRORS_LOG  = LOGS_DIR / "pagination_errors.log"
DUPLICATE_LOG          = LOGS_DIR / "duplicate_links.log"
POST_ERRORS_LOG        = LOGS_DIR / "post_errors.log"
NESTED_ERRORS_LOG      = LOGS_DIR / "nested_errors.log"
FILE_PAGE_ERRORS_LOG   = LOGS_DIR / "file_page_errors.log"
DOWNLOAD_ERRORS_LOG    = LOGS_DIR / "download_errors.log"
FILE_VALIDATION_LOG    = LOGS_DIR / "file_validation.log"
METADATA_ERRORS_LOG    = LOGS_DIR / "metadata_errors.log"
UNCLASSIFIED_LOG       = LOGS_DIR / "unclassified_titles.log"
DATABASE_ERRORS_LOG    = LOGS_DIR / "database_errors.log"

# ════════════════════════════════════════════════════════════════
# NAVBAR EXTRACTION SETTINGS
# ════════════════════════════════════════════════════════════════

# CSS selectors to try when locating the navbar (most specific first).
# The confirmed selector for jntufastupdates.com (Tagdiv Composer theme)
# is listed first for fast matching; generic fallbacks follow.
NAVBAR_SELECTORS = [
    # ── jntufastupdates.com (Tagdiv Composer theme) ───────
    "ul#menu-main-menu-1",          # Mobile-responsive main menu (confirmed)
    "ul.td-mobile-main-menu",       # Class-based fallback
    "ul.tdb-menu-items-visible",    # Desktop Tagdiv menu
    # ── Generic WordPress themes ──────────────────────────
    "#primary-menu",
    "#main-menu",
    ".primary-menu",
    ".main-navigation ul",
    "#main-navigation ul",
    "nav ul",
    "nav",
    "header ul",
]

# Tags that indicate a dropdown parent (parent → children)
DROPDOWN_CONTAINER_TAGS = ["li", "div"]

# Class names that indicate a dropdown
DROPDOWN_CLASS_HINTS = [
    "dropdown", "has-sub", "menu-item-has-children",
    "sub-menu", "submenu", "mega-menu",
]

# ════════════════════════════════════════════════════════════════
# PDF / FILE DETECTION
# ════════════════════════════════════════════════════════════════

# Anchor text that signals a download link
DOWNLOAD_KEYWORDS = [
    "download", "click here", "get pdf", "view pdf",
    "download pdf", "get file", "open pdf",
]

# File extensions considered downloadable
DOWNLOADABLE_EXTENSIONS = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"]

# ════════════════════════════════════════════════════════════════
# PHASE 4 — DOWNLOAD ENGINE SETTINGS
# ════════════════════════════════════════════════════════════════

# Number of parallel download threads
DOWNLOAD_WORKERS = 4

# Stream chunk size (bytes) for PDF downloads
DOWNLOAD_CHUNK_SIZE = 8 * 1024          # 8 KB

# Minimum valid PDF file size (bytes)
PDF_MIN_BYTES = 1024                     # 1 KB — reject empty/stub files

# Maximum PDF file size to accept without warning (bytes)
PDF_MAX_BYTES = 200 * 1024 * 1024       # 200 MB

# Timeout for download requests (connect, read) — longer than scrape timeout
DOWNLOAD_TIMEOUT = (15, 120)

# Content-Type strings that indicate a real PDF
PDF_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "binary/octet-stream",   # Generic — rely on magic bytes
    "application/octet-stream",
}

# Content-Type strings that indicate a bad/fake download (HTML ad redirect)
BAD_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "application/javascript",
    "application/json",
}
