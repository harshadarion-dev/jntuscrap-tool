"""
scraper/homepage_scraper.py — JNTUScrapTool Homepage Scraper
=============================================================
Loads the target website homepage, saves an HTML snapshot, and
returns the parsed BeautifulSoup object for downstream processing.

Responsibilities:
  - Fetch https://www.jntufastupdates.com/
  - Handle request errors with informative messages
  - Save raw HTML snapshot to exports/snapshots/
  - Return soup + raw navbar HTML for NavbarExtractor
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

import config
from core.logger import get_logger
from core.session_manager import SessionManager

log = get_logger("homepage_scraper", config.PHASE1_LOG)


class HomepageScraper:
    """
    Fetches the JNTU Fast Updates homepage and prepares it
    for navbar extraction.

    Attributes:
        session (SessionManager): Shared HTTP session.
        url (str): Target URL to scrape.
    """

    def __init__(self, session: SessionManager) -> None:
        self.session = session
        self.url = config.BASE_URL

    # ────────────────────────────────────────────────────────
    def fetch(self) -> BeautifulSoup:
        """
        Fetch the homepage and return a parsed BeautifulSoup object.

        Returns:
            BeautifulSoup: Parsed HTML of the homepage.

        Raises:
            SystemExit: If the page cannot be fetched after retries.
        """
        log.info("Fetching homepage: %s", self.url)

        try:
            response = self.session.get(self.url, delay=False)
            response.raise_for_status()
        except Exception as exc:
            log.error("Failed to fetch homepage: %s", exc)
            raise SystemExit(
                f"[FATAL] Cannot reach {self.url}. Check your internet connection."
            ) from exc

        log.info("Homepage fetched successfully. Size: %d bytes", len(response.content))

        # Save HTML snapshot before parsing
        self.save_snapshot(response.text)

        soup = BeautifulSoup(response.text, "lxml")
        return soup

    # ────────────────────────────────────────────────────────
    def save_snapshot(self, html: str) -> None:
        """
        Save the raw homepage HTML to a snapshot file for debugging.
        Overwrites any existing snapshot.

        Args:
            html: Raw HTML string.
        """
        snapshot_path: Path = config.HOMEPAGE_HTML
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        with open(snapshot_path, "w", encoding="utf-8") as f:
            f.write(html)

        log.info("HTML snapshot saved → %s", snapshot_path)

    # ────────────────────────────────────────────────────────
    def get_navbar_element(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """
        Locate the main navigation bar in the parsed HTML.
        Tries multiple CSS selectors defined in config.NAVBAR_SELECTORS.

        Args:
            soup: Full parsed homepage soup.

        Returns:
            The first matching navbar Tag, or None if not found.
        """
        log.info("Searching for navbar element...")

        for selector in config.NAVBAR_SELECTORS:
            element = soup.select_one(selector)
            if element:
                log.info("Navbar found via selector: '%s'", selector)
                return element

        # Last resort — look for any <ul> inside <header>
        header = soup.find("header")
        if header:
            nav_ul = header.find("ul")
            if nav_ul:
                log.info("Navbar found inside <header> as <ul>")
                return nav_ul

        log.warning(
            "Could not locate navbar. The site structure may have changed. "
            "Check the homepage snapshot: %s",
            config.HOMEPAGE_HTML,
        )
        return None
