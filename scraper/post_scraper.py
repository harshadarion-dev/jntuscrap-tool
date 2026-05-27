"""
scraper/post_scraper.py — JNTUScrapTool Post Page Processor
============================================================
Visits every Phase 2 post URL, classifies the page type, and extracts:
  - All file page links (files.jntufastupdates.com/download/*)
  - All direct PDF links
  - All nested post links (for recursion)
  - All external download links (Google Drive etc.)

Page type classification:
  Type A — Page directly contains a single file page link
  Type B — Page links to nested informational post(s)
  Type C — Page contains multiple subject/file-page links
  Type X — Empty / no useful links

For Type C posts (e.g. Question Papers) the anchor text of each file-page
link is used as the subject name for that specific FileTarget.

For each file page found, uses FilePageScraper to get the final
download URL from data-downloadurl.

Outputs:
  1. file_targets.json  — merged from all post analyses
  2. post_metadata.json — one record per post URL with full page analysis

Usage:
    python main.py phase3
    python main.py phase3 --limit 10   (test first N posts)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

import config
from core.logger import get_logger
from core.session_manager import SessionManager
from core.link_classifier import LinkClassifier, LinkKind, NAV_SLUGS
from core.content_parser import ContentParser, ContentMetadata
from core.html_snapshot_manager import HTMLSnapshotManager
from core.duplicate_checker import DuplicateChecker
from core.url_manager import URLManager
from scraper.nested_post_scraper import NestedPostScraper
from scraper.file_page_scraper import FilePageScraper

log = get_logger("post_scraper", config.POST_ERRORS_LOG)


class PageType(str, Enum):
    TYPE_A = "type_a"   # Direct file page link (single)
    TYPE_B = "type_b"   # Nested post links
    TYPE_C = "type_c"   # Multiple subject/file-page links
    TYPE_X = "type_x"   # Empty / unresolvable


@dataclass
class FileTarget:
    """One resolved download target."""
    title:           str
    university:      Optional[str] = None
    category:        Optional[str] = None
    degree:          Optional[str] = None
    semester:        Optional[str] = None
    regulation:      Optional[str] = None
    subject:         Optional[str] = None
    branch:          Optional[str] = None
    exam_month:      Optional[str] = None
    year:            Optional[str] = None
    academic_year:   Optional[str] = None
    post_url:        Optional[str] = None
    nested_url:      Optional[str] = None
    file_page_url:   Optional[str] = None
    download_target: Optional[str] = None
    direct_pdf_url:  Optional[str] = None
    external_url:    Optional[str] = None
    page_type:       Optional[str] = None


@dataclass
class PostAnalysis:
    """Full analysis record for a single post URL."""
    post_url:    str
    page_type:   PageType                = PageType.TYPE_X
    title:       Optional[str]           = None
    metadata:    Optional[ContentMetadata] = None
    file_targets: list[FileTarget]       = field(default_factory=list)
    error:       Optional[str]           = None


# Content area selectors (most specific first)
_CONTENT_SELECTORS = [
    ".td-pb-span8", ".td-post-content", ".entry-content",
    ".vc_column.tdc-column", ".post-content", "article",
]

# URL slugs for posts that are nav/utility pages — skip entirely
_NAV_URL_PATTERNS = NAV_SLUGS | {
    "about-us", "contact-us", "disclaimer", "privacy-policy",
    "terms-conditions", "sitemap",
}


class PostScraper:
    """
    Processes all Phase 2 post URLs to find and resolve file download targets.

    Flow per post:
      1. Pre-filter: skip nav/utility page URLs
      2. Fetch post page HTML
      3. Save snapshot
      4. Extract title and content
      5. Classify all links on the page
      6. Based on counts → determine page type
      7. For each file page URL → call FilePageScraper (passes anchor text as subject)
      8. For each nested post link → call NestedPostScraper
      9. Build FileTarget records
      10. Accumulate into file_targets + post_metadata

    Attributes:
        session      (SessionManager)
        classifier   (LinkClassifier)
        parser       (ContentParser)
        snapshot_mgr (HTMLSnapshotManager)
        file_scraper (FilePageScraper)
        dedup        (DuplicateChecker)
    """

    def __init__(self, session: SessionManager) -> None:
        self.session      = session
        self.classifier   = LinkClassifier()
        self.parser       = ContentParser()
        self.snapshot_mgr = HTMLSnapshotManager()
        self.file_scraper = FilePageScraper(session, self.snapshot_mgr)
        self.dedup        = DuplicateChecker()
        self.url_mgr      = URLManager()

        self._file_targets:   list[dict] = []
        self._post_metadata:  list[dict] = []
        # Shared visited set for nested scraper (prevent loops)
        self._visited_nested: set[str]   = set()

        # Load Phase 3 dedup state (separate from Phase 2's dedup_state.json)
        # This ensures we don't skip posts because Phase 2 already saw them
        self.dedup.load(config.PHASE3_DEDUP_JSON)

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def run(self, limit: int | None = None) -> None:
        """
        Main entry point.
        Reads post_links.json (Phase 2 output) and processes each post.

        Args:
            limit: If set, only process the first N posts (for testing).
        """
        post_links_path = config.POST_LINKS_JSON
        if not post_links_path.exists():
            log.error("post_links.json not found — run phase2 first.")
            raise FileNotFoundError(
                f"Missing {post_links_path}. Run: python main.py phase2"
            )

        with open(post_links_path, encoding="utf-8") as f:
            posts: list[dict] = json.load(f)

        if limit:
            posts = posts[:limit]

        log.info("Processing %d post(s).", len(posts))

        for i, post_record in enumerate(posts, 1):
            url = post_record.get("url", "")
            if not url:
                continue

            # ── Pre-filter nav/utility pages ──────────────────
            if self._is_nav_url(url):
                log.debug("Skipping nav/utility URL: %s", url)
                continue

            log.info("[%d/%d] %s", i, len(posts), url)
            analysis = self._process_post(post_record)

            # Accumulate
            for ft in analysis.file_targets:
                self._file_targets.append(asdict(ft))

            self._post_metadata.append({
                "post_url":    analysis.post_url,
                "page_type":   analysis.page_type,
                "title":       analysis.title,
                "num_targets": len(analysis.file_targets),
                "error":       analysis.error,
            })

        self._save_outputs()
        log.info(
            "Phase 3 complete. Total file targets: %d", len(self._file_targets)
        )

    # ══════════════════════════════════════════════════════════
    # PRIVATE — POST PROCESSING
    # ══════════════════════════════════════════════════════════

    def _process_post(self, post_record: dict) -> PostAnalysis:
        """
        Fetch and fully analyse one post URL.

        Args:
            post_record: Dict from post_links.json (includes hints from Phase 2).

        Returns:
            PostAnalysis with all file targets resolved.
        """
        url      = post_record["url"]
        analysis = PostAnalysis(post_url=url)

        # ── Dedup at post level ────────────────────────────────
        if not self.dedup.is_new_url(url):
            analysis.error = "duplicate"
            return analysis

        # ── Fetch ─────────────────────────────────────────────
        soup = self._fetch(url)
        if soup is None:
            analysis.error = "fetch_error"
            return analysis

        self.snapshot_mgr.save_post(soup.prettify(), url)

        # ── Title ─────────────────────────────────────────────
        title_el = soup.find("h1") or soup.find("h2")
        title = title_el.get_text(strip=True) if title_el else post_record.get("title", "")
        analysis.title = title

        # ── Parse metadata ────────────────────────────────────
        hints = {k: post_record.get(k) for k in
                 ["university", "category", "semester", "regulation", "year", "degree"]}
        meta = self.parser.parse_title(title, hints)
        meta = self.parser.parse_content(soup, meta)
        analysis.metadata = meta

        # ── Find content area ─────────────────────────────────
        content_el = None
        for sel in _CONTENT_SELECTORS:
            content_el = soup.select_one(sel)
            if content_el:
                break

        # ── Classify links ────────────────────────────────────
        # classify_all now returns dict[LinkKind, list[(url, anchor_text)]]
        classified = self.classifier.classify_all(soup, url, content_el)

        file_page_pairs  = classified[LinkKind.FILE_PAGE]      # [(url, text), ...]
        nested_post_pairs = classified[LinkKind.NESTED_POST]   # [(url, text), ...]
        direct_pdfs      = classified[LinkKind.DIRECT_PDF]
        external_files   = classified[LinkKind.EXTERNAL_FILE]
        download_btns    = classified[LinkKind.DOWNLOAD_BUTTON]

        # ── Determine page type ───────────────────────────────
        if file_page_pairs or download_btns:
            analysis.page_type = (PageType.TYPE_C if len(file_page_pairs) > 1
                                  else PageType.TYPE_A)
        elif nested_post_pairs:
            analysis.page_type = PageType.TYPE_B
        elif direct_pdfs or external_files:
            analysis.page_type = PageType.TYPE_A
        else:
            analysis.page_type = PageType.TYPE_X
            analysis.error = "no_links_found"
            log.warning("[TYPE_X] No useful links: %s", url)
            return analysis

        # ── Process file pages ────────────────────────────────
        # For Type C posts, anchor text IS the subject name (e.g. "BASIC CIVIL AND MECHANICAL ENGINEERING")
        for fp_url, anchor_text in file_page_pairs:
            ft = self._build_file_target(
                fp_url, meta, url, nested_url=None,
                subject_override=anchor_text or None,
            )
            ft.page_type = analysis.page_type
            analysis.file_targets.append(ft)

        # ── Process download buttons directly ─────────────────
        for dl_url, _ in download_btns:
            ft = FileTarget(
                title=title,
                university=meta.university, category=meta.category,
                degree=meta.degree, semester=meta.semester,
                regulation=meta.regulation, subject=meta.subject,
                branch=meta.branch, exam_month=meta.exam_month,
                year=meta.year, academic_year=meta.academic_year,
                post_url=url, page_type=PageType.TYPE_A,
                download_target=dl_url,
            )
            analysis.file_targets.append(ft)

        # ── Process direct PDFs ───────────────────────────────
        for pdf_url, _ in direct_pdfs:
            ft = FileTarget(
                title=title,
                university=meta.university, category=meta.category,
                degree=meta.degree, semester=meta.semester,
                regulation=meta.regulation, subject=meta.subject,
                branch=meta.branch, year=meta.year,
                post_url=url, page_type=PageType.TYPE_A,
                direct_pdf_url=pdf_url,
            )
            analysis.file_targets.append(ft)

        # ── Process external links ────────────────────────────
        for ext_url, _ in external_files:
            ft = FileTarget(
                title=title,
                university=meta.university, category=meta.category,
                degree=meta.degree, semester=meta.semester,
                regulation=meta.regulation, subject=meta.subject,
                post_url=url, page_type=PageType.TYPE_A,
                external_url=ext_url,
            )
            analysis.file_targets.append(ft)

        # ── Process nested posts (Type B) ─────────────────────
        if not analysis.file_targets and nested_post_pairs:
            ns = NestedPostScraper(
                self.session, self.classifier,
                self.snapshot_mgr, self._visited_nested
            )
            for nested_url, _ in nested_post_pairs:
                # triples are (nested_url, file_page_url, anchor_text)
                triples = ns.resolve(nested_url, depth=1)
                for (n_url, fp_url, anchor_text) in triples:
                    ft = self._build_file_target(
                        fp_url, meta, url, nested_url=n_url,
                        subject_override=anchor_text or None,
                    )
                    ft.page_type = PageType.TYPE_B
                    analysis.file_targets.append(ft)

        log.info(
            "[%s] %d target(s) found.", analysis.page_type, len(analysis.file_targets)
        )
        return analysis

    def _build_file_target(
        self,
        file_page_url:    str,
        meta:             ContentMetadata,
        post_url:         str,
        nested_url:       Optional[str] = None,
        subject_override: Optional[str] = None,
    ) -> FileTarget:
        """
        Call FilePageScraper on a file page URL, then assemble a FileTarget.

        The subject is resolved in priority order:
          1. subject_override  — anchor text from the linking post (most accurate for Type C)
          2. meta.subject      — computed from the post title
          3. file-page title   — fallback parsed from the file page itself

        Args:
            file_page_url:    URL of the WPDM download page.
            meta:             Metadata already extracted from the post title.
            post_url:         The originating post URL.
            nested_url:       Intermediate nested post URL (None for Type A/C).
            subject_override: Anchor text from the file-page link (often = subject).
        """
        fp_result = self.file_scraper.extract(file_page_url)

        # Determine best subject
        subject = subject_override
        if not subject:
            subject = meta.subject
        if not subject and fp_result.title:
            # Parse subject from file-page title as last resort
            fp_meta = self.parser.parse_title(fp_result.title, {})
            subject = fp_meta.subject or fp_result.title

        # Prefer file-page title if post title is generic
        title = fp_result.title or meta.title or ""

        return FileTarget(
            title=title,
            university=meta.university,
            category=meta.category,
            degree=meta.degree,
            semester=meta.semester,
            regulation=meta.regulation,
            subject=subject,
            branch=meta.branch,
            exam_month=meta.exam_month,
            year=meta.year,
            academic_year=meta.academic_year,
            post_url=post_url,
            nested_url=nested_url,
            file_page_url=file_page_url,
            download_target=fp_result.download_url,
            direct_pdf_url=fp_result.direct_pdf_url,
            external_url=fp_result.external_url,
            page_type=PageType.TYPE_A,
        )

    # ══════════════════════════════════════════════════════════
    # PRIVATE — UTILITIES
    # ══════════════════════════════════════════════════════════

    def _is_nav_url(self, url: str) -> bool:
        """
        Return True if the URL is a navigation/utility page that should be skipped.

        Checks:
          - Slug matches known nav patterns (about-us, sitemap, disclaimer…)
          - URL does not contain a year or semester hint (crude but effective
            filter for generic "All Results at One Place" aggregator pages)
        """
        slug = self.url_mgr.get_slug(url)
        if slug in _NAV_URL_PATTERNS:
            return True
        # Also skip if title text in the URL looks like a region/site-nav page
        for nav_slug in _NAV_URL_PATTERNS:
            if url.rstrip("/").endswith(nav_slug):
                return True
        return False

    def _fetch(self, url: str) -> BeautifulSoup | None:
        try:
            resp = self.session.get(url)
            if resp.status_code == 404:
                log.warning("404: %s", url)
                return None
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            log.error("Fetch error %s: %s", url, exc)
            return None

    def _save_outputs(self) -> None:
        """Write file_targets.json and post_metadata.json to exports/."""
        config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

        with open(config.FILE_TARGETS_JSON, "w", encoding="utf-8") as f:
            json.dump(self._file_targets, f, indent=2, ensure_ascii=False)
        log.info("file_targets.json → %d records", len(self._file_targets))

        with open(config.POST_METADATA_JSON, "w", encoding="utf-8") as f:
            json.dump(self._post_metadata, f, indent=2, ensure_ascii=False)
        log.info("post_metadata.json → %d records", len(self._post_metadata))

        # Persist dedup state for future runs
        self.dedup.dump(config.PHASE3_DEDUP_JSON)
        log.info("Dedup state saved.")
