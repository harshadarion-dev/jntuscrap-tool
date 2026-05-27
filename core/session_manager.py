"""
core/session_manager.py — JNTUScrapTool HTTP Session Manager
=============================================================
Provides a reusable, production-grade HTTP session with:
  - Automatic retry with exponential backoff
  - Random User-Agent rotation (via fake_useragent)
  - Configurable timeout
  - Polite rate-limiting delay between requests

Usage:
    from core.session_manager import SessionManager
    sm = SessionManager()
    response = sm.get("https://www.jntufastupdates.com/")
"""

import time
import random
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from core.logger import get_logger

# Try to import fake_useragent; fall back to static UA if not installed
try:
    from fake_useragent import UserAgent
    _UA = UserAgent()
    _UA_AVAILABLE = True
except Exception:
    _UA = None
    _UA_AVAILABLE = False


log = get_logger("session_manager", config.SCRAPER_LOG)


class SessionManager:
    """
    A wrapper around requests.Session that adds:
      - Retry logic (configurable via config.py)
      - Random User-Agent on every request
      - Polite delay between requests
      - Centralized timeout

    Attributes:
        session (requests.Session): The underlying session object.
    """

    def __init__(self) -> None:
        self.session = self._build_session()

    # ────────────────────────────────────────────────────────
    def _build_session(self) -> requests.Session:
        """
        Create and configure a requests.Session with:
          - Retry adapter mounted on http:// and https://
          - Default headers from config
        """
        session = requests.Session()
        session.headers.update(config.DEFAULT_HEADERS)

        # ── Retry strategy ────────────────────────────────
        retry_strategy = Retry(
            total=config.RETRY_COUNT,
            backoff_factor=config.RETRY_BACKOFF,
            status_forcelist=config.RETRY_ON_STATUS,
            allowed_methods=["GET", "HEAD", "OPTIONS"],
            raise_on_status=False,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        log.debug("HTTP session created with retry=%d, backoff=%.1f",
                  config.RETRY_COUNT, config.RETRY_BACKOFF)
        return session

    # ────────────────────────────────────────────────────────
    def _rotate_user_agent(self) -> None:
        """
        Randomly pick a new User-Agent and apply it to the session headers.
        Falls back to the default UA from config if fake_useragent is unavailable.
        """
        if _UA_AVAILABLE and _UA:
            try:
                ua = _UA.random
                self.session.headers.update({"User-Agent": ua})
                log.debug("User-Agent rotated: %.60s...", ua)
                return
            except Exception as exc:
                log.debug("UA rotation failed (%s); using default.", exc)

        # Fallback — use static UA from config
        self.session.headers.update({"User-Agent": config.DEFAULT_HEADERS["User-Agent"]})

    # ────────────────────────────────────────────────────────
    def get(self, url: str, delay: bool = True, **kwargs: Any) -> requests.Response:
        """
        Perform a GET request with UA rotation, configurable timeout,
        and optional polite delay.

        Args:
            url:    The URL to fetch.
            delay:  If True, sleep REQUEST_DELAY seconds before the request.
            **kwargs: Extra arguments forwarded to requests.Session.get().

        Returns:
            requests.Response object.

        Raises:
            requests.RequestException: On network or HTTP errors after retries.
        """
        self._rotate_user_agent()

        # Polite delay — don't hammer the server
        if delay:
            sleep_time = config.REQUEST_DELAY + random.uniform(0, 0.5)
            log.debug("Sleeping %.2f s before request.", sleep_time)
            time.sleep(sleep_time)

        # Apply default timeout unless caller overrides
        kwargs.setdefault("timeout", config.REQUEST_TIMEOUT)

        log.debug("GET %s", url)
        response = self.session.get(url, **kwargs)

        log.debug("Response: %d | %s", response.status_code, url)
        return response

    # ────────────────────────────────────────────────────────
    def close(self) -> None:
        """Close the underlying session and free resources."""
        self.session.close()
        log.debug("Session closed.")
