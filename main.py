"""
main.py — JNTUScrapTool CLI Entry Point
========================================
Command-line interface for the JNTUScrapTool.
Powered by Typer for clean, documented commands.

Usage examples:
    python main.py phase1                         # Phase 1: Navbar extraction
    python main.py scrape --full                  # Full scrape (Phase 2+)
    python main.py scrape --university jntuk      # Scrape single university
    python main.py scrape --category question-papers
    python main.py export --csv                   # Export index to CSV
    python main.py serve                          # Start FastAPI server (Phase 6+)
"""

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

import config
from core.logger import get_logger
from core.session_manager import SessionManager
from scraper.homepage_scraper import HomepageScraper
from scraper.navbar_extractor import NavbarExtractor
from scraper.category_scraper import CategoryScraper
from scraper.post_scraper import PostScraper
from scraper.pdf_downloader import PDFDownloader
from scraper.metadata_enricher import MetadataEnricher
from scraper.metadata_exporter import MetadataExporter
from database.index_builder import IndexBuilder
from database.search_engine import SearchEngine
from database.db_manager import DatabaseManager

# ── CLI Application ──────────────────────────────────────────
app     = Console()
cli     = typer.Typer(
    name="jntuscraptool",
    help="🎓 JNTUScrapTool — JNTU Academic Resource Scraper & Organiser",
    add_completion=False,
    rich_markup_mode="rich",
)

log = get_logger("main", config.PHASE1_LOG)


# ================================================================
# PHASE 1 COMMAND
# ================================================================

@cli.command("phase1")
def phase1() -> None:
    """
    [bold green]Phase 1[/bold green]: Extract homepage navbar and university-category structure.

    Output files:
    - [cyan]exports/snapshots/homepage_snapshot.html[/cyan]
    - [cyan]exports/navbar_structure.json[/cyan]
    - [cyan]logs/phase1.log[/cyan]
    """
    rprint("\n[bold cyan]==============================================[/bold cyan]")
    rprint("[bold white]   JNTUScrapTool — Phase 1: Navbar Extraction [/bold white]")
    rprint("[bold cyan]==============================================[/bold cyan]\n")

    log.info("="*60)
    log.info("Phase 1 started")
    log.info("="*60)

    # ── Step 1: Build shared HTTP session ────────────────────
    rprint("[yellow]>[/yellow] Initialising HTTP session...")
    session = SessionManager()

    # ── Step 2: Fetch homepage ────────────────────────────────
    rprint("[yellow]>[/yellow] Fetching homepage: [cyan]%s[/cyan]" % config.BASE_URL)
    scraper = HomepageScraper(session)
    soup    = scraper.fetch()

    # ── Step 3: Extract navbar ────────────────────────────────
    rprint("[yellow]>[/yellow] Extracting navbar structure...")
    extractor = NavbarExtractor()
    structure = extractor.extract(soup)

    # ── Step 4: Save JSON ─────────────────────────────────────
    rprint("[yellow]>[/yellow] Saving navbar_structure.json...")
    extractor.save_json(structure)

    # ── Step 5: Print results summary ─────────────────────────
    _print_structure_summary(structure)

    # ── Done ──────────────────────────────────────────────────
    rprint("\n[bold green][OK] Phase 1 complete![/bold green]")
    rprint(f"  Navbar JSON  → [cyan]{config.NAVBAR_JSON}[/cyan]")
    rprint(f"  HTML Snapshot→ [cyan]{config.HOMEPAGE_HTML}[/cyan]")
    rprint(f"  Phase log    → [cyan]{config.PHASE1_LOG}[/cyan]")
    rprint(f"  Errors log   → [cyan]{config.ERRORS_LOG}[/cyan]\n")

    log.info("Phase 1 finished successfully.")
    session.close()


# ================================================================
# PHASE 2 COMMAND
# ================================================================

@cli.command("phase2")
def phase2(
    university: Optional[str] = typer.Option(None, "--university", "-u",
        help="Only scrape this university (e.g. JNTUK, JNTUH)"),
    category: Optional[str] = typer.Option(None, "--category", "-c",
        help="Only scrape this category (e.g. 'Question Papers')"),
) -> None:
    """
    [bold green]Phase 2[/bold green]: Recursively scrape all category pages and collect post URLs.

    Output files:
    - [cyan]exports/category_structure.json[/cyan]
    - [cyan]exports/post_links.json[/cyan]
    - [cyan]logs/phase2.log[/cyan]

    Reads [cyan]exports/navbar_structure.json[/cyan] from Phase 1. Run phase1 first.
    """
    log2 = get_logger("main_phase2", config.PHASE2_LOG)

    rprint("\n[bold cyan]===================================================[/bold cyan]")
    rprint("[bold white]   JNTUScrapTool — Phase 2: Category Recursive Scraper[/bold white]")
    rprint("[bold cyan]===================================================[/bold cyan]\n")

    if not config.NAVBAR_JSON.exists():
        rprint("[bold red][X] navbar_structure.json not found.[/bold red]")
        rprint("  Run [cyan]python main.py phase1[/cyan] first to generate it.")
        raise typer.Exit(code=1)

    log2.info("="*60)
    log2.info("Phase 2 started (university=%s, category=%s)", university, category)
    log2.info("="*60)

    rprint("[yellow]>[/yellow] Initialising HTTP session...")
    session = SessionManager()

    rprint("[yellow]>[/yellow] Starting recursive category scraper...")
    scraper = CategoryScraper(session)

    try:
        scraper.run(
            filter_university=university,
            filter_category=category,
        )
    except KeyboardInterrupt:
        rprint("\n[bold yellow]⚠ Interrupted by user. Partial results saved.[/bold yellow]")
        scraper._save_outputs()
    finally:
        session.close()

    # ── Print summary ─────────────────────────────────────────
    total = len(scraper.all_posts)
    rprint(f"\n[bold green][OK] Phase 2 complete! {total} posts discovered.[/bold green]")
    rprint(f"  Post index  → [cyan]{config.POST_LINKS_JSON}[/cyan]")
    rprint(f"  Category map→ [cyan]{config.CATEGORY_STRUCTURE_JSON}[/cyan]")
    rprint(f"  Phase log   → [cyan]{config.PHASE2_LOG}[/cyan]\n")

    log2.info("Phase 2 finished. Total posts: %d", total)


@cli.command("phase3")
def phase3(
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n",
        help="Only process first N posts (for testing)."
    ),
) -> None:
    """
    [bold green]Phase 3[/bold green]: Post Intelligence Layer — resolves every post URL
    to its final file download target.

    Reads [cyan]exports/post_links.json[/cyan] from Phase 2.

    Output files:
    - [cyan]exports/file_targets.json[/cyan]   — all resolved file targets
    - [cyan]exports/post_metadata.json[/cyan]  — one record per post
    - [cyan]logs/phase3.log[/cyan]
    - [cyan]raw_data/post_pages/[/cyan]        — HTML snapshots of post pages
    - [cyan]raw_data/nested_pages/[/cyan]      — HTML snapshots of nested posts
    - [cyan]raw_data/file_pages/[/cyan]        — HTML snapshots of file pages
    """
    log3 = get_logger("main_phase3", config.PHASE3_LOG)

    rprint("\n[bold cyan]=======================================================[/bold cyan]")
    rprint("[bold white]   JNTUScrapTool — Phase 3: Post Intelligence Layer     [/bold white]")
    rprint("[bold cyan]=======================================================[/bold cyan]\n")

    if not config.POST_LINKS_JSON.exists():
        rprint("[bold red][X] post_links.json not found.[/bold red]")
        rprint("  Run [cyan]python main.py phase2[/cyan] first.")
        raise typer.Exit(code=1)

    log3.info("=" * 60)
    log3.info("Phase 3 started (limit=%s)", limit)
    log3.info("=" * 60)

    if limit:
        rprint(f"[yellow]ℹ[/yellow] Test mode: processing first [bold]{limit}[/bold] posts.")

    rprint("[yellow]>[/yellow] Initialising HTTP session...")
    session = SessionManager()

    rprint("[yellow]>[/yellow] Starting Post Intelligence Layer...")
    scraper = PostScraper(session)

    try:
        scraper.run(limit=limit)
    except KeyboardInterrupt:
        rprint("\n[bold yellow]⚠ Interrupted. Partial results saved.[/bold yellow]")
        scraper._save_outputs()
    finally:
        session.close()

    # ── Summary ───────────────────────────────────────────────
    total_targets  = len(scraper._file_targets)
    total_posts    = len(scraper._post_metadata)
    type_counts    = {}
    error_counts   = {}
    for rec in scraper._post_metadata:
        pt = rec.get("page_type", "unknown")
        type_counts[pt] = type_counts.get(pt, 0) + 1
        if rec.get("error"):
            err = rec["error"]
            error_counts[err] = error_counts.get(err, 0) + 1

    rprint(f"\n[bold green][OK] Phase 3 complete![/bold green]")
    rprint(f"  Posts analysed  → [cyan]{total_posts}[/cyan]")
    rprint(f"  File targets    → [bold cyan]{total_targets}[/bold cyan]")

    # Page-type breakdown table
    table = Table(
        title="📊 Page Type Summary",
        show_lines=True,
        title_style="bold cyan",
    )
    table.add_column("Page Type", style="bold yellow")
    table.add_column("Description", style="white")
    table.add_column("Count", style="cyan", justify="right")
    _type_desc = {
        "type_a": "Direct file page link",
        "type_b": "Nested post → file page",
        "type_c": "Multiple subject links",
        "type_x": "No links / unresolvable",
    }
    for pt, cnt in sorted(type_counts.items()):
        table.add_row(pt.upper(), _type_desc.get(pt, "-"), str(cnt))

    from rich.console import Console as RConsole
    console = RConsole()
    console.print(table)

    if error_counts:
        rprint("\n[bold yellow]⚠ Errors encountered:[/bold yellow]")
        for err, cnt in error_counts.items():
            rprint(f"  {err}: {cnt}")

    rprint(f"  File targets    → [cyan]{config.FILE_TARGETS_JSON}[/cyan]")
    rprint(f"  Post metadata   → [cyan]{config.POST_METADATA_JSON}[/cyan]")
    rprint(f"  Phase log       → [cyan]{config.PHASE3_LOG}[/cyan]\n")

    log3.info("Phase 3 finished. Targets: %d", total_targets)


@cli.command("phase4")
def phase4(
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n",
        help="Only download first N targets (for testing)."
    ),
    workers: int = typer.Option(
        config.DOWNLOAD_WORKERS, "--workers", "-w",
        help="Parallel download threads."
    ),
) -> None:
    """
    [bold green]Phase 4[/bold green]: PDF Download Engine — downloads every resolved
    file target to structured local storage with hash verification.

    Reads [cyan]exports/file_targets.json[/cyan] from Phase 3.

    Output files:
    - [cyan]storage/[/cyan]                      — organised PDF archive
    - [cyan]exports/downloads_index.json[/cyan]  — full download index
    - [cyan]exports/download_history.csv[/cyan]  — download history
    - [cyan]exports/hash_registry.json[/cyan]    — SHA-256 dedup registry
    - [cyan]logs/phase4.log[/cyan]
    """
    log4 = get_logger("main_phase4", config.PHASE4_LOG)

    rprint("\n[bold cyan]=======================================================[/bold cyan]")
    rprint("[bold white]   JNTUScrapTool — Phase 4: PDF Download Engine          [/bold white]")
    rprint("[bold cyan]=======================================================[/bold cyan]\n")

    if not config.FILE_TARGETS_JSON.exists():
        rprint("[bold red][X] file_targets.json not found.[/bold red]")
        rprint("  Run [cyan]python main.py phase3[/cyan] first.")
        raise typer.Exit(code=1)

    import json as _json
    with open(config.FILE_TARGETS_JSON, encoding="utf-8") as fh:
        targets: list[dict] = _json.load(fh)

    total_input = len(targets)
    rprint(f"[yellow]>[/yellow] Loaded [bold]{total_input}[/bold] file targets from Phase 3.")
    if limit:
        rprint(f"[yellow]ℹ[/yellow] Test mode: downloading first [bold]{limit}[/bold] targets.")
    rprint(f"[yellow]>[/yellow] Using [bold]{workers}[/bold] parallel download thread(s).")

    log4.info("=" * 60)
    log4.info("Phase 4 started  targets=%d  workers=%d  limit=%s",
              total_input, workers, limit)
    log4.info("=" * 60)

    rprint("[yellow]>[/yellow] Initialising session & components...")
    session = SessionManager()
    downloader = PDFDownloader(session)

    try:
        downloader.run(targets, workers=workers, limit=limit)
    except KeyboardInterrupt:
        rprint("\n[bold yellow]⚠ Interrupted. Saving partial results...[/bold yellow]")
        downloader.tracker.save()
        downloader.hasher.save_registry()
    finally:
        session.close()

    # ── Rich summary table ──
    tracker = downloader.tracker
    rprint(f"\n[bold green][OK] Phase 4 complete![/bold green]")

    table = Table(
        title="📥 Download Summary",
        show_lines=True,
        title_style="bold cyan",
    )
    table.add_column("Status",     style="bold",   min_width=12)
    table.add_column("Count",      style="cyan",   justify="right")
    table.add_column("Description", style="white")

    status_rows = [
        ("success",   str(tracker.success_count),   "[green]PDF downloaded & validated[/green]"),
        ("duplicate", str(tracker.duplicate_count), "[yellow]Same content already on disk[/yellow]"),
        ("skipped",   str(tracker.skipped_count),   "[dim]Already downloaded in prior run[/dim]"),
        ("invalid",   str(tracker.invalid_count),   "[red]Failed validation (not a PDF)[/red]"),
        ("failed",    str(tracker.failed_count),    "[red]Download error / all retries failed[/red]"),
    ]
    for status, cnt, desc in status_rows:
        table.add_row(status, cnt, desc)

    from rich.console import Console as RConsole
    console = RConsole()
    console.print(table)

    rprint(f"  Storage root    → [cyan]{config.STORAGE_DIR}[/cyan]")
    rprint(f"  Download index  → [cyan]{config.DOWNLOADS_INDEX_JSON}[/cyan]")
    rprint(f"  History CSV     → [cyan]{config.DOWNLOAD_HISTORY_CSV}[/cyan]")
    rprint(f"  Hash registry   → [cyan]{config.HASH_REGISTRY_JSON}[/cyan]")
    rprint(f"  Phase log       → [cyan]{config.PHASE4_LOG}[/cyan]\n")

    log4.info(
        "Phase 4 finished. success=%d  failed=%d  dup=%d  skip=%d  invalid=%d",
        tracker.success_count, tracker.failed_count,
        tracker.duplicate_count, tracker.skipped_count, tracker.invalid_count,
    )


@cli.command("phase5")
def phase5() -> None:
    """
    [bold green]Phase 5[/bold green]: Metadata Intelligence Engine — enriches all
    Phase 3+4 records into a fully structured master metadata list.

    Reads:
    - [cyan]exports/file_targets.json[/cyan]    (Phase 3)
    - [cyan]exports/downloads_index.json[/cyan] (Phase 4)

    Outputs:
    - [cyan]exports/master_metadata.json[/cyan]
    - [cyan]exports/master_metadata.csv[/cyan]
    """
    log5 = get_logger("main_phase5", config.PHASE5_LOG)

    rprint("\n[bold cyan]=======================================================[/bold cyan]")
    rprint("[bold white]   JNTUScrapTool — Phase 5: Metadata Intelligence Engine  [/bold white]")
    rprint("[bold cyan]=======================================================[/bold cyan]\n")

    log5.info("=" * 60)
    log5.info("Phase 5 started")
    log5.info("=" * 60)

    rprint("[yellow]>[/yellow] Running metadata enrichment...")
    enricher = MetadataEnricher()
    records  = enricher.enrich()

    rprint("[yellow]>[/yellow] Exporting metadata...")
    exporter = MetadataExporter()
    exporter.save(records)

    # Stats
    total        = len(records)
    classified   = sum(1 for r in records if r.get("classified"))
    unclassified = total - classified
    by_uni:  dict = {}
    by_cat:  dict = {}
    for r in records:
        u = r.get("university") or "Unknown"
        c = r.get("category")   or "Unknown"
        by_uni[u] = by_uni.get(u, 0) + 1
        by_cat[c] = by_cat.get(c, 0) + 1

    rprint(f"\n[bold green][OK] Phase 5 complete![/bold green]")
    rprint(f"  Total records    → [bold cyan]{total}[/bold cyan]")
    rprint(f"  Classified       → [green]{classified}[/green]")
    rprint(f"  Unclassified     → [yellow]{unclassified}[/yellow]")

    table = Table(title="🏛️ University Breakdown",
                  show_lines=True, title_style="bold cyan")
    table.add_column("University", style="bold yellow")
    table.add_column("Records", style="cyan", justify="right")
    for uni, cnt in sorted(by_uni.items(), key=lambda x: -x[1]):
        table.add_row(uni, str(cnt))

    from rich.console import Console as RConsole
    RConsole().print(table)

    rprint(f"  Master metadata → [cyan]{config.MASTER_METADATA_JSON}[/cyan]")
    rprint(f"  Master CSV      → [cyan]{config.MASTER_METADATA_CSV}[/cyan]")
    rprint(f"  Phase log       → [cyan]{config.PHASE5_LOG}[/cyan]\n")
    log5.info("Phase 5 finished. Total: %d  Classified: %d", total, classified)


@cli.command("phase6")
def phase6() -> None:
    """
    [bold green]Phase 6[/bold green]: Master Database Builder — inserts the Phase 5
    metadata into a searchable SQLite database and exports master indexes.

    Reads:  [cyan]exports/master_metadata.json[/cyan]

    Outputs:
    - [cyan]database/jntuscraptool.db[/cyan]  — SQLite database
    - [cyan]exports/master_index.json[/cyan]  — flat JSON index
    - [cyan]exports/master_index.csv[/cyan]   — CSV index
    """
    log6 = get_logger("main_phase6", config.PHASE6_LOG)

    rprint("\n[bold cyan]=======================================================[/bold cyan]")
    rprint("[bold white]   JNTUScrapTool — Phase 6: Master Database Builder       [/bold white]")
    rprint("[bold cyan]=======================================================[/bold cyan]\n")

    if not config.MASTER_METADATA_JSON.exists():
        rprint("[bold red][X] master_metadata.json not found.[/bold red]")
        rprint("  Run [cyan]python main.py phase5[/cyan] first.")
        raise typer.Exit(code=1)

    log6.info("=" * 60)
    log6.info("Phase 6 started")
    log6.info("=" * 60)

    rprint("[yellow]>[/yellow] Building master index...")
    db       = DatabaseManager()
    builder  = IndexBuilder(db_manager=db)
    inserted, skipped = builder.build()

    # Analytics via search engine
    rprint("[yellow]>[/yellow] Computing analytics...")
    se    = SearchEngine(db)
    stats = se.get_analytics()
    db.close()

    rprint(f"\n[bold green][OK] Phase 6 complete![/bold green]")
    rprint(f"  DB inserted      → [bold cyan]{inserted}[/bold cyan]")
    rprint(f"  DB skipped (dup) → [yellow]{skipped}[/yellow]")
    rprint(f"  Total in DB      → [cyan]{stats.get('total', 0)}[/cyan]")

    table = Table(title="📊 Database Analytics",
                  show_lines=True, title_style="bold cyan")
    table.add_column("Dimension",  style="bold yellow")
    table.add_column("Breakdown",  style="white")
    analytics_rows = [
        ("By University",  stats.get("by_university", {})),
        ("By Category",    stats.get("by_category",   {})),
        ("By Regulation",  stats.get("by_regulation", {})),
        ("By Semester",    stats.get("by_semester",   {})),
    ]
    for dim, data in analytics_rows:
        if data:
            breakdown = "  ".join(f"{k}:{v}" for k, v in list(data.items())[:6])
            table.add_row(dim, breakdown)

    from rich.console import Console as RConsole
    RConsole().print(table)

    rprint(f"  Database         → [cyan]{config.DATABASE_PATH}[/cyan]")
    rprint(f"  Master JSON      → [cyan]{config.MASTER_INDEX_JSON}[/cyan]")
    rprint(f"  Master CSV       → [cyan]{config.MASTER_INDEX_CSV}[/cyan]")
    rprint(f"  Phase log        → [cyan]{config.PHASE6_LOG}[/cyan]\n")
    log6.info("Phase 6 finished. inserted=%d skipped=%d total=%d",
              inserted, skipped, stats.get("total", 0))


@cli.command("scrape")
def scrape(
    full: bool = typer.Option(False, "--full", help="Scrape all universities"),
    university: Optional[str] = typer.Option(None, "--university", "-u"),
    category:   Optional[str] = typer.Option(None, "--category",   "-c"),
) -> None:
    """
    [bold green]Phase 2-5[/bold green]: Alias for phase2 — runs the full recursive scrape.
    """
    rprint("[bold yellow]ℹ scrape aliases phase2. Running phase2...[/bold yellow]")
    # Delegate to phase2 logic
    phase2(university=university, category=category)


@cli.command("export")
def export(
    csv: bool = typer.Option(False, "--csv", help="Export master index as CSV"),
) -> None:
    """
    [bold green]Phase 6[/bold green]: Export scraped index to CSV or JSON.
    (Not yet implemented)
    """
    rprint("[bold red]⚠ Export not yet implemented.[/bold red]")
    raise typer.Exit(code=1)


@cli.command("serve")
def serve() -> None:
    """
    [bold green]Phase 6[/bold green]: Start the FastAPI API server.
    (Not yet implemented)
    """
    rprint("[bold red]⚠ FastAPI server not yet implemented.[/bold red]")
    raise typer.Exit(code=1)


# ================================================================
# HELPERS
# ================================================================

def _print_structure_summary(structure: dict) -> None:
    """Pretty-print the extracted structure as a Rich table."""
    table = Table(
        title="📚 Extracted Navbar Structure",
        show_lines=True,
        title_style="bold cyan",
    )
    table.add_column("University / Group", style="bold yellow", min_width=14)
    table.add_column("Category", style="white")
    table.add_column("URL", style="dim cyan", overflow="fold")

    for uni, categories in structure.items():
        if not categories:
            table.add_row(uni, "[dim]— no links found —[/dim]", "")
        else:
            for cat, url in categories.items():
                table.add_row(uni, cat, url)

    from rich.console import Console as RConsole
    console = RConsole()
    console.print(table)
    console.print()


@cli.command("dashboard")
def dashboard(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000,        "--port", help="Port number"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open browser"),
) -> None:
    """
    [bold green]Phase 7[/bold green]: Launch the local control dashboard.

    Opens [cyan]http://127.0.0.1:8000[/cyan] in your browser.
    WebSocket live progress, one-click full scrape, search portal.
    """
    import webbrowser
    import uvicorn
    from api.dashboard_api import app as dashboard_app

    rprint("\n[bold cyan]=======================================================[/bold cyan]")
    rprint("[bold white]   JNTUScrapTool — Phase 7: Local Control Dashboard      [/bold white]")
    rprint("[bold cyan]=======================================================[/bold cyan]\n")
    rprint(f"[yellow]>[/yellow] Starting dashboard at [bold cyan]http://{host}:{port}[/bold cyan]")
    rprint("[yellow]>[/yellow] Press Ctrl+C to stop\n")

    url = f"http://{host}:{port}"
    if not no_browser:
        import threading
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        dashboard_app,
        host=host,
        port=port,
        log_level="warning",
    )


# ================================================================
# ENTRY POINT
# ================================================================

if __name__ == "__main__":
    cli()
