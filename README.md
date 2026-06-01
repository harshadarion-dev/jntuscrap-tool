# JNTUScrapTool 🎓

A comprehensive web scraping and data organization tool for JNTU (Jawaharlal Nehru Technological University) academic resources. This tool efficiently extracts, processes, and indexes academic materials from the JNTU website.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Technology Stack](#technology-stack)
- [Features](#features)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Usage](#usage)
- [Phases Explained](#phases-explained)
- [Configuration](#configuration)
- [Dependencies](#dependencies)
- [Output Files](#output-files)
- [License](#license)
- [Support](#support)

---

## 🎯 Overview

**JNTUScrapTool** is a modular, multi-phase scraping framework designed to:

- Crawl and extract the complete JNTU website structure
- Identify all academic categories (Question Papers, Syllabus, Results, etc.)
- Resolve file download links from nested post structures
- Download and validate PDF documents with SHA-256 deduplication
- Build a searchable SQLite database with full metadata
- Provide a FastAPI REST API and local dashboard for resource discovery

**Target Universities:**
- JNTU Kakinada (JNTUK)
- JNTU Hyderabad (JNTUH)
- JNTU Anantapur (JNTUA)
- JNTU Vizianagaram (JNTUGV)

---

## 📊 Technology Stack

| Language | Percentage | Role |
|----------|-----------|------|
| **Python** | 84% | Core logic, scraping, data processing |
| **HTML** | 8.7% | Dashboard templates & web UI |
| **JavaScript** | 3.7% | Frontend interactivity, real-time updates |
| **CSS** | 3.6% | Styling and responsive design |

### Key Technologies:

- **Web Scraping:** BeautifulSoup4, Selenium, lxml
- **HTTP:** Requests, aiohttp, urllib3
- **Data Processing:** Pandas, SQLAlchemy
- **CLI:** Typer + Rich (beautiful terminal output)
- **API:** FastAPI + Uvicorn
- **Database:** SQLite with async support
- **Progress Tracking:** tqdm

---

## ✨ Features

### Core Capabilities

✅ **Multi-phase scraping architecture** — Modular, resumable, and traceable workflows  
✅ **Advanced HTML parsing** — Handles dynamic JS-rendered content with Selenium fallback  
✅ **Smart link resolution** — Navigates nested post structures to find final file targets  
✅ **Parallel downloads** — Configurable worker threads for efficient file retrieval  
✅ **Content deduplication** — SHA-256 hashing prevents duplicate file storage  
✅ **Rich CLI interface** — Colored output, progress bars, detailed logs  
✅ **Comprehensive logging** — Phase-specific and error-specific log files  
✅ **SQLite database** — Full-text search, analytics, and metadata indexing  
✅ **FastAPI REST API** — JSON endpoints for programmatic access (Phase 6+)  
✅ **Local dashboard** — One-click scraping, live progress, search portal (Phase 7)

---

## 📁 Project Structure

```
jntuscrap-tool/
├── main.py                    # CLI entry point with Typer commands
├── config.py                  # Global configuration (paths, headers, timeouts, mappings)
├── control_center.py          # Orchestration and phase management
├── inspect_phase3.py          # Phase 3 inspection utility
├── requirements.txt           # Python dependencies
├── .gitignore                 # Git ignore rules
│
├── core/                      # Core utilities
│   ├── logger.py              # Logging setup per phase
│   ├── session_manager.py     # HTTP session with retries & delays
│   └── ...
│
├── scraper/                   # Scraping modules
│   ├── homepage_scraper.py    # Phase 1: Homepage fetching
│   ├── navbar_extractor.py    # Phase 1: Navbar parsing
│   ├── category_scraper.py    # Phase 2: Recursive category scraping
│   ├── post_scraper.py        # Phase 3: Post intelligence layer
│   ├── pdf_downloader.py      # Phase 4: Download engine
│   ├── metadata_enricher.py   # Phase 5: Metadata enrichment
│   └── metadata_exporter.py   # Phase 5: Export utilities
│
├── database/                  # Database layer
│   ├── db_manager.py          # SQLite connection & operations
│   ├── index_builder.py       # Phase 6: Database population
│   └── search_engine.py       # Query and analytics
│
├── api/                       # REST API & Dashboard
│   └── dashboard_api.py       # FastAPI server (Phase 7)
│
├── dashboard/                 # Frontend (HTML/JS/CSS)
│   └── ...
│
├── storage/                   # Downloaded PDFs (auto-created)
├── exports/                   # JSON/CSV index files (auto-created)
│   └── snapshots/             # HTML snapshots
├── logs/                      # Phase-specific logs (auto-created)
├── raw_data/                  # Intermediate data (auto-created)
│   ├── category_pages/
│   ├── pagination_pages/
│   ├── post_indexes/
│   ├── post_pages/
│   ├── nested_pages/
│   ├── file_pages/
│   └── download_cache/
└── database/                  # SQLite database (auto-created)
    └── jntuscraptool.db
```

---

## 🚀 Installation

### Prerequisites

- Python 3.9+ (3.11+ recommended)
- Git
- ~10-20 GB disk space (for full JNTU archive)
- Internet connection

### Step 1: Clone Repository

```bash
git clone https://github.com/harshadarion-dev/jntuscrap-tool.git
cd jntuscrap-tool
```

### Step 2: Create Virtual Environment

```bash
python -m venv venv

# Activate (Linux/macOS):
source venv/bin/activate

# Activate (Windows):
venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Verify Installation

```bash
python main.py --help
```

You should see the CLI help with all available commands.

---

## 📖 Usage

### Quick Start

#### Run Full Pipeline (All Phases)

```bash
python main.py phase1       # Extract navbar
python main.py phase2       # Scrape categories & posts
python main.py phase3 --limit 100  # Process first 100 posts (test)
python main.py phase4       # Download PDFs
python main.py phase5       # Enrich metadata
python main.py phase6       # Build database
python main.py dashboard    # Launch interactive dashboard
```

Or use the orchestrator:
```bash
python control_center.py --mode=full
```

#### Scrape Specific University

```bash
python main.py phase2 --university JNTUK
```

#### Scrape Specific Category

```bash
python main.py phase2 --category "Question Papers"
```

#### Test Mode (Limited Downloads)

```bash
python main.py phase3 --limit 10
python main.py phase4 --limit 10 --workers 2
```

### Available Commands

```
python main.py phase1              # Phase 1: Extract navbar structure
python main.py phase2              # Phase 2: Recursive category scrape
python main.py phase3 [--limit N]  # Phase 3: Post intelligence layer
python main.py phase4 [--limit N]  # Phase 4: PDF download engine
python main.py phase5              # Phase 5: Metadata enrichment
python main.py phase6              # Phase 6: Database builder
python main.py scrape [--full]     # Alias for phases 2-5
python main.py export [--csv]      # Export master index
python main.py serve               # Start FastAPI server
python main.py dashboard           # Launch local dashboard
```

---

## 🔄 Phases Explained

### **Phase 1: Navbar Extraction**
- Fetches the JNTU homepage
- Extracts navigation structure using CSS selectors
- Maps universities → categories → URLs
- **Output:** `navbar_structure.json`

### **Phase 2: Recursive Category Scraping**
- Navigates each category URL
- Follows pagination to collect all post links
- Filters by university/category (optional)
- **Output:** `post_links.json`, `category_structure.json`

### **Phase 3: Post Intelligence Layer**
- Resolves each post URL to find final file targets
- Handles three post types:
  - **Type A:** Direct file page link
  - **Type B:** Nested post → file page
  - **Type C:** Multiple subject links
  - **Type X:** No links / unresolvable
- **Output:** `file_targets.json`, `post_metadata.json`

### **Phase 4: PDF Download Engine**
- Downloads resolved file targets with parallel workers
- Validates PDFs (magic bytes, size, content-type)
- Deduplicates using SHA-256 hashing
- Organizes storage: `storage/JNTUK/Question Papers/...`
- **Output:** `downloads_index.json`, `download_history.csv`, `hash_registry.json`

### **Phase 5: Metadata Intelligence Engine**
- Enriches file metadata (title, university, category, regulation, semester)
- Classifies unclassified materials
- Exports to JSON/CSV
- **Output:** `master_metadata.json`, `master_metadata.csv`

### **Phase 6: Master Database Builder**
- Inserts all records into SQLite database
- Enables full-text search and advanced queries
- Computes analytics (by university, category, regulation, semester)
- **Output:** `jntuscraptool.db`, `master_index.json`, `master_index.csv`

### **Phase 7: Local Control Dashboard** (Optional)
- Interactive web interface at `http://127.0.0.1:8000`
- One-click phase execution
- Real-time progress with WebSocket
- Full-text search portal
- Resource statistics and analytics

---

## ⚙️ Configuration

Edit `config.py` to customize:

### Paths
```python
BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
EXPORTS_DIR = BASE_DIR / "exports"
LOGS_DIR = BASE_DIR / "logs"
```

### HTTP Settings
```python
REQUEST_TIMEOUT = (10, 30)        # (connect, read) in seconds
RETRY_COUNT = 3
RETRY_BACKOFF = 1.0
RETRY_ON_STATUS = [429, 500, 502, 503, 504]
REQUEST_DELAY = 1.5               # Polite delay between requests
```

### Download Settings
```python
DOWNLOAD_WORKERS = 4              # Parallel download threads
PDF_MIN_BYTES = 1024              # Minimum PDF size
PDF_MAX_BYTES = 200 * 1024 * 1024 # Maximum PDF size
DOWNLOAD_TIMEOUT = (15, 120)      # Longer timeout for downloads
```

### University & Category Mappings
```python
UNIVERSITIES = {
    "JNTUK": "JNTU Kakinada",
    "JNTUH": "JNTU Hyderabad",
    "JNTUA": "JNTU Anantapur",
    "JNTUGV": "JNTU Vizianagaram",
}

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
```

---

## 📦 Dependencies

### Core Scraping
- `requests>=2.31.0` — HTTP client
- `beautifulsoup4>=4.12.0` — HTML parsing
- `lxml>=4.9.0` — Fast XML/HTML parser
- `fake-useragent>=1.4.0` — Rotate user agents
- `selenium>=4.18.0` — Browser automation
- `undetected-chromedriver>=3.5.5` — Bypass detection

### Data & Storage
- `pandas>=2.1.0` — CSV/DataFrame export
- `SQLAlchemy>=2.0.0` — ORM
- `aiosqlite>=0.19.0` — Async SQLite

### CLI & Output
- `typer[all]>=0.12.0` — CLI framework
- `rich>=13.7.0` — Pretty terminal output

### Async & API
- `aiohttp>=3.9.0` — Async HTTP
- `aiofiles>=23.2.0` — Async file I/O
- `fastapi>=0.110.0` — REST API
- `uvicorn[standard]>=0.27.0` — ASGI server

### Utilities
- `python-dotenv>=1.0.0` — Environment variables
- `tqdm>=4.66.0` — Progress bars

See `requirements.txt` for all versions.

---

## 📄 Output Files

### Exports (`exports/`)

| File | Phase | Description |
|------|-------|-------------|
| `navbar_structure.json` | 1 | University→Category→URL mapping |
| `category_structure.json` | 2 | Detailed category crawl tree |
| `post_links.json` | 2 | All discovered post URLs |
| `file_targets.json` | 3 | Resolved file download targets |
| `post_metadata.json` | 3 | Per-post analysis records |
| `downloads_index.json` | 4 | All downloaded files metadata |
| `download_history.csv` | 4 | CSV log of downloads |
| `hash_registry.json` | 4 | SHA-256 dedup registry |
| `master_metadata.json` | 5 | Enriched metadata (JSON) |
| `master_metadata.csv` | 5 | Enriched metadata (CSV) |
| `master_index.json` | 6 | Database index export (JSON) |
| `master_index.csv` | 6 | Database index export (CSV) |

### Storage (`storage/`)

Organized by university and category:
```
storage/
├── JNTUK/
│   ├── Question Papers/
│   │   ├── R13/
│   │   │   ├── CSE/
│   │   │   │   └── exam_2023_q1.pdf
│   │   │   └── ...
│   │   └── ...
│   ├── Syllabus/
│   └── ...
├── JNTUH/
└── ...
```

### Logs (`logs/`)

Phase-specific and error-specific logging:
- `phase1.log`, `phase2.log`, ..., `phase6.log`
- `errors.log`, `download_errors.log`, `post_errors.log`
- `category_errors.log`, `duplicate_links.log`, `unclassified.log`

### Database (`database/`)

- `jntuscraptool.db` — SQLite database with all records, full-text search

---

## 🔍 Database Schema (Phase 6)

The SQLite database includes:

- **files** — Downloaded files with metadata
  - id, title, university, category, regulation, semester, path, size, sha256, date_added
  
- **posts** — Original post metadata
  - id, url, title, university, category, page_type

- **downloads** — Download history
  - id, file_id, timestamp, status, error_msg

Search via:
```python
from database.search_engine import SearchEngine
se = SearchEngine(db_manager)
results = se.search("quantum mechanics", filters={"university": "JNTUK"})
```

---

## 🎨 Dashboard (Phase 7)

Launch the local web interface:

```bash
python main.py dashboard --host 127.0.0.1 --port 8000
```

Features:
- 📊 Real-time scraping progress (WebSocket)
- 🔍 Full-text search with filters
- 📈 Statistics & analytics dashboard
- ⚙️ One-click phase execution
- 📥 Download status tracking

---

## 🐛 Troubleshooting

### Issue: `navbar_structure.json not found`
**Solution:** Run `python main.py phase1` first.

### Issue: Slow downloads
**Solution:** Increase workers in Phase 4:
```bash
python main.py phase4 --workers 8
```

### Issue: Memory errors on large scrapes
**Solution:** Use `--limit` flag to process in batches:
```bash
python main.py phase3 --limit 500
```

### Issue: PDF validation failures
**Solution:** Check `logs/file_page_errors.log` for details. Adjust `PDF_MIN_BYTES` and `PDF_MAX_BYTES` in `config.py` if needed.

---

## 📋 Environment Variables (Optional)

Create `.env` file in project root:

```env
LOG_LEVEL=INFO
REQUEST_TIMEOUT=30
DOWNLOAD_WORKERS=4
DATABASE_URL=sqlite:///database/jntuscraptool.db
```

---

## 📝 License

This project is provided as-is for educational and research purposes. Ensure you comply with JNTU's terms of service and copyright policies when using this tool.

---

## 💬 Support & Contributing

### Issues & Bug Reports
Report issues on the GitHub [Issues](https://github.com/harshadarion-dev/jntuscrap-tool/issues) page.

### Contributing
Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-feature`)
3. Commit your changes (`git commit -m "Add new feature"`)
4. Push to the branch (`git push origin feature/new-feature`)
5. Open a Pull Request

### Contact
- **Author:** harshadarion-dev
- **Email:** harsha.darion@gmail.com
- **Repository:** [jntuscrap-tool](https://github.com/harshadarion-dev/jntuscrap-tool)

---

## 🙏 Acknowledgments

- Built with [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/), [Typer](https://typer.tiangolo.com/), and [FastAPI](https://fastapi.tiangolo.com/)
- Thanks to all JNTU students and researchers using this tool

---

**Last Updated:** June 1, 2026  
**Latest Release:** v1.0.0
