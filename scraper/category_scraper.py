"""
scraper/category_scraper.py — JNTUScrapTool Category Recursive Engine
======================================================================
The central orchestrator for Phase 2.

Reads Phase 1's navbar_structure.json, visits each category URL,
detects page type, extracts posts, recurses into nested sub-categories,
follows pagination, and builds two export files:
  - exports/category_structure.json   (nested category hierarchy)
  - exports/post_links.json           (all discovered post URLs + metadata)

Scraping depth hierarchy:
  Level 1: Top-level category (e.g. /jntuk-academic-calendars/)
  Level 2: Nested category   (e.g. /jntuk-1-1-question-papers/)
  Level 3: Sub-reg page      (e.g. /jntuk-1-1-r23-question-papers-2024/)
  Level 4: Posts              (leaf pages with file download links)

Usage:
    python main.py phase2
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

import config
from core.logger import get_logger
from core.session_manager import SessionManager
from core.url_manager import URLManager
from core.duplicate_checker import DuplicateChecker
from core.link_router import LinkRouter, LinkType
from scraper.post_link_extractor import PostLinkExtractor, PostLink
from scraper.pagination_scraper import PaginationScraper

log = get_logger("category_scraper", config.PHASE2_LOG)

# Maximum recursion depth to prevent infinite loops
MAX_DEPTH = 4

# Persist dedup state between sessions
_DEDUP_STATE_FILE = config.EXPORTS_DIR / "dedup_state.json"


class CategoryScraper:
    """
    Orchestrates the recursive scraping of all category pages.

    Flow:
      1. Load navbar_structure.json (Phase 1 output)
      2. For each (university, category, url) triple:
           a. Fetch the page
           b. Extract posts via PostLinkExtractor
           c. Detect sub-category links via PostLinkExtractor
           d. Recurse into sub-categories (respecting MAX_DEPTH)
           e. Crawl all pagination pages at each level
      3. Save results to category_structure.json + post_links.json

    Attributes:
        session  (SessionManager):    Shared HTTP session.
        url_mgr  (URLManager):        URL normalisation.
        dedup    (DuplicateChecker):  Cross-page deduplication.
        router   (LinkRouter):        Link type classifier.
        extractor(PostLinkExtractor): Post card extractor.
        pager    (PaginationScraper): Pagination handler.
        all_posts(list[dict]):        Accumulated post records.
        cat_tree (dict):              Nested category → posts map.
    """

    def __init__(self, session: SessionManager) -> None:
        self.session   = session
        self.url_mgr   = URLManager()
        self.dedup     = DuplicateChecker()
        self.router    = LinkRouter()
        self.extractor = PostLinkExtractor(self.url_mgr, self.dedup, self.router)
        self.pager     = PaginationScraper(self.session, self.url_mgr)

        self.all_posts: list[dict] = []
        # cat_tree[uni][category][semester][regulation] = [PostLink, ...]
        self.cat_tree: dict[str, Any] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        )

        # Restore dedup state from last run (for resumable scraping)
        self.dedup.load(_DEDUP_STATE_FILE)

    # ══════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════

    def run(
        self,
        filter_university: str | None = None,
        filter_category:   str | None = None,
    ) -> None:
        """
        Main entry point — reads navbar JSON and scrapes everything.

        Args:
            filter_university: If set (e.g. 'JNTUK'), only scrape that university.
            filter_category:   If set (e.g. 'Question Papers'), only scrape that category.
        """
        navbar_path = config.NAVBAR_JSON
        if not navbar_path.exists():
            log.error("navbar_structure.json not found. Run phase1 first.")
            raise FileNotFoundError(
                f"Missing {navbar_path}. Run: python main.py phase1"
            )

        with open(navbar_path, encoding="utf-8") as f:
            navbar: dict = json.load(f)

        log.info("Loaded navbar with %d university entries.", len(navbar))

        for university, categories in navbar.items():
            if university == "General":
                continue
            if filter_university and university.upper() != filter_university.upper():
                log.debug("Skipping university: %s (filtered)", university)
                continue

            for cat_name, cat_url in categories.items():
                if filter_category and filter_category.lower() not in cat_name.lower():
                    log.debug("Skipping category: %s (filtered)", cat_name)
                    continue

                log.info("=" * 60)
                log.info("Scraping [%s] → %s", university, cat_name)
                log.info("URL: %s", cat_url)

                self._scrape_category(
                    url=cat_url,
                    university=university,
                    category=cat_name,
                    depth=1,
                )

        # ── Save outputs ──────────────────────────────────────
        self._save_outputs()

        # ── Persist dedup state ───────────────────────────────
        self.dedup.dump(_DEDUP_STATE_FILE)

        log.info("Phase 2 complete. Total posts collected: %d", len(self.all_posts))

    # ══════════════════════════════════════════════════════════
    # PRIVATE — SCRAPING LOGIC
    # ══════════════════════════════════════════════════════════

    def _scrape_category(
        self,
        url:        str,
        university: str,
        category:   str,
        depth:      int,
        semester:   str | None = None,
        regulation: str | None = None,
    ) -> None:
        """
        Scrape one category/nested-category URL recursively.

        Args:
            url:        Page URL to fetch.
            university: Current university classification.
            category:   Current category classification.
            depth:      Current recursion depth.
            semester:   Inherited semester hint (from parent URL).
            regulation: Inherited regulation hint (from parent URL).
        """
        if depth > MAX_DEPTH:
            log.debug("Max depth reached at %s — stopping recursion.", url)
            return

        # ── Fetch the page ────────────────────────────────────
        soup = self._fetch(url)
        if soup is None:
            return

        # ── Crawl all pagination pages at this level ──────────
        all_soups = self.pager.get_all_pages(url, soup)
        log.info("[depth=%d] %s — %d page(s) to process.", depth, url, len(all_soups))

        # ── Process every page soup ───────────────────────────
        for page_soup in all_soups:
            # Extract post links
            posts = self.extractor.extract(page_soup, page_url=url)
            for post in posts:
                # Fill in inherited metadata if extractor didn't get it
                if not post.university:
                    post.university = university
                if not post.category:
                    post.category = category
                if not post.semester and semester:
                    post.semester = semester
                if not post.regulation and regulation:
                    post.regulation = regulation

                self._store_post(post)

            # Extract sub-category links for recursion
            sub_cats = self.extractor.extract_category_links(page_soup, page_url=url)
            for sub in sub_cats:
                # Only recurse into pages that are new
                if not self.dedup.is_new_url(sub.url):
                    continue
                # Propagate known metadata downward
                sub_sem = sub.semester or semester
                sub_reg = sub.regulation or regulation
                sub_cat = sub.category or category
                sub_uni = sub.university or university

                self._scrape_category(
                    url=sub.url,
                    university=sub_uni,
                    category=sub_cat,
                    depth=depth + 1,
                    semester=sub_sem,
                    regulation=sub_reg,
                )

    def _fetch(self, url: str) -> BeautifulSoup | None:
        """
        Fetch a URL and return parsed BeautifulSoup, or None on failure.
        """
        try:
            response = self.session.get(url)
            if response.status_code == 404:
                log.warning("404 Not Found: %s", url)
                return None
            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml")
        except Exception as exc:
            log.error("Failed to fetch %s: %s", url, exc)
            return None

    # ══════════════════════════════════════════════════════════
    # PRIVATE — DATA STORAGE
    # ══════════════════════════════════════════════════════════

    def _store_post(self, post: PostLink) -> None:
        """
        Add a PostLink to both the flat list and the nested tree.

        Args:
            post: Extracted PostLink data object.
        """
        uni  = post.university or "Unknown"
        cat  = post.category   or "Unknown"
        sem  = post.semester   or "General"
        reg  = post.regulation or "General"

        record = {
            "title":      post.title,
            "url":        post.url,
            "university": uni,
            "category":   cat,
            "degree":     post.degree,
            "semester":   post.semester,
            "regulation": post.regulation,
            "year":       post.year,
            "page_source": post.page_source,
        }

        self.all_posts.append(record)

        # Add to nested tree
        self.cat_tree[uni][cat][sem][reg].append({
            "title": post.title,
            "url":   post.url,
        })

        log.debug("[%s][%s][%s][%s] %s", uni, cat, sem, reg, post.title[:60])

    # ══════════════════════════════════════════════════════════
    # PRIVATE — OUTPUT
    # ══════════════════════════════════════════════════════════

    def _save_outputs(self) -> None:
        """Write category_structure.json and post_links.json."""
        config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # post_links.json — flat list
        post_path = config.POST_LINKS_JSON
        with open(post_path, "w", encoding="utf-8") as f:
            json.dump(self.all_posts, f, indent=2, ensure_ascii=False)
        log.info("post_links.json saved → %s (%d posts)", post_path, len(self.all_posts))

        # category_structure.json — nested tree
        cat_path = config.CATEGORY_STRUCTURE_JSON
        with open(cat_path, "w", encoding="utf-8") as f:
            json.dump(self.cat_tree, f, indent=2, ensure_ascii=False)
        log.info("category_structure.json saved → %s", cat_path)
