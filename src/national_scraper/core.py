"""
Universal Browser Scraper Core

Handles: Browser lifecycle, navigation, JS rendering, rate limiting,
cookie banners, retries, screenshots on error.

Country-specific logic lives in adapters — this module is generic.
"""

import time
import logging
from pathlib import Path
from typing import Optional, Callable

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, Response

logger = logging.getLogger(__name__)


class BrowserCore:
    """Manages a Playwright browser instance for scraping."""

    def __init__(self, headless: bool = True, slow_mo: int = 100,
                 screenshot_dir: str = "data/raw/screenshots"):
        self.headless = headless
        self.slow_mo = slow_mo
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._last_nav_time = 0.0
        self.min_interval = 2.0  # Minimum seconds between page loads

    def start(self):
        """Launch browser."""
        import os
        ssl_bypass = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() in ("1", "true", "yes")

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            # Bypass SSL errors from corporate proxy (same as requests' verify=False)
            args=["--ignore-certificate-errors"] if ssl_bypass else [],
        )
        self.context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-GB",
            # Ignore HTTPS/SSL errors globally (corporate proxy support)
            ignore_https_errors=True,
        )
        self.page = self.context.new_page()
        if ssl_bypass:
            logger.info("Browser started (headless=%s, SSL bypass enabled)", self.headless)
        else:
            logger.info("Browser started (headless=%s)", self.headless)

    def stop(self):
        """Close browser and clean up."""
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            logger.info("Browser stopped")
        except Exception as e:
            logger.debug(f"Browser stop error (ignorable): {e}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    # ── Navigation ──

    def goto(self, url: str, wait_for: str = "networkidle",
             timeout: int = 30000, max_retries: int = 2) -> bool:
        """
        Navigate to URL and wait for page to be ready.

        Args:
            url: Target URL
            wait_for: "networkidle", "load", "domcontentloaded",
                      or a CSS selector to wait for
            timeout: Max wait time in ms
            max_retries: Retry count on timeout/transient errors (default 2)

        Returns:
            True if successful, False on error
        """
        self._rate_limit()

        for attempt in range(max_retries + 1):
            if attempt > 0:
                backoff = 2 ** attempt
                logger.info(f"goto retry {attempt}/{max_retries} for {url} in {backoff}s")
                time.sleep(backoff)

            try:
                self._ensure_page_alive()
                self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)

                if wait_for in ("networkidle", "load", "domcontentloaded"):
                    try:
                        self.page.wait_for_load_state(wait_for, timeout=timeout)
                    except Exception:
                        pass  # networkidle may never fire on some sites — not fatal
                elif wait_for != "domcontentloaded":
                    # wait_for is a CSS selector
                    try:
                        self.page.wait_for_selector(wait_for, timeout=min(timeout, 8000))
                    except Exception:
                        pass  # Selector missing is not fatal

                self._dismiss_cookie_banner()
                return True

            except Exception as e:
                err = str(e)
                # Page/context was closed externally — recover by opening a new page
                if "closed" in err.lower() or "target" in err.lower():
                    logger.warning(f"Page closed unexpectedly, recovering... ({url})")
                    try:
                        self.page = self.context.new_page()
                        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                        self._dismiss_cookie_banner()
                        return True
                    except Exception as e2:
                        logger.error(f"Recovery navigation also failed: {url} — {e2}")
                        return False

                if attempt < max_retries:
                    logger.warning(f"Navigation attempt {attempt + 1} failed: {url} — {e}")
                    continue

                logger.error(f"Navigation failed after {max_retries + 1} attempts: {url} — {e}")
                self._screenshot(f"nav_error_{int(time.time())}")
                return False

        return False

    def _rate_limit(self):
        """Enforce minimum interval between navigations."""
        elapsed = time.time() - self._last_nav_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_nav_time = time.time()

    def _ensure_page_alive(self):
        """If the current page is closed/crashed, open a fresh one."""
        try:
            _ = self.page.url  # Will raise if page is closed
        except Exception:
            logger.info("Page was closed — opening a new page")
            try:
                self.page = self.context.new_page()
            except Exception as e:
                logger.error(f"Could not create new page: {e}")

    # ── Content Extraction ──

    def get_text(self, selector: str, timeout: int = 5000) -> str:
        """Get text content of first matching element."""
        try:
            el = self.page.wait_for_selector(selector, timeout=timeout)
            return el.text_content().strip() if el else ""
        except Exception:
            return ""

    def get_all_texts(self, selector: str, timeout: int = 5000) -> list:
        """Get text content of ALL matching elements."""
        try:
            self.page.wait_for_selector(selector, timeout=timeout)
            elements = self.page.query_selector_all(selector)
            return [el.text_content().strip() for el in elements
                    if el.text_content() and el.text_content().strip()]
        except Exception:
            return []

    def get_attribute(self, selector: str, attribute: str,
                      timeout: int = 5000) -> str:
        """Get attribute value of first matching element."""
        try:
            el = self.page.wait_for_selector(selector, timeout=timeout)
            return el.get_attribute(attribute) or "" if el else ""
        except Exception:
            return ""

    def get_page_text(self) -> str:
        """Get full page text content (cleaned).

        Uses JavaScript innerText so it works regardless of page structure
        (avoids strict-mode failures on missing 'main' / 'body' selectors).
        """
        try:
            # JavaScript innerText is the most reliable cross-browser way
            text = self.page.evaluate(
                "() => { "
                "  const el = document.querySelector('main') || document.body; "
                "  return el ? el.innerText : ''; "
                "}"
            ) or ""
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            return "\n".join(lines)
        except Exception:
            try:
                # Fallback: full page content via inner_text
                return self.page.inner_text("body") or ""
            except Exception:
                return ""

    def get_page_html(self) -> str:
        """Get full page outer HTML."""
        try:
            return self.page.content() or ""
        except Exception:
            return ""

    def get_inner_html(self, selector: str, timeout: int = 5000) -> str:
        """Get innerHTML of first matching element."""
        try:
            el = self.page.wait_for_selector(selector, timeout=timeout)
            return el.inner_html() if el else ""
        except Exception:
            return ""

    def get_current_url(self) -> str:
        """Return current page URL."""
        try:
            return self.page.url
        except Exception:
            return ""

    # ── Interaction ──

    def click(self, selector: str, timeout: int = 5000) -> bool:
        """Click an element."""
        try:
            self.page.click(selector, timeout=timeout)
            time.sleep(0.5)  # Brief pause after click
            return True
        except Exception:
            return False

    def fill(self, selector: str, value: str, timeout: int = 5000) -> bool:
        """Fill a text input (clear first, then type)."""
        try:
            self.page.fill(selector, "", timeout=timeout)  # Clear first
            self.page.fill(selector, value, timeout=timeout)
            return True
        except Exception:
            return False

    def select_option(self, selector: str, value: str,
                      timeout: int = 5000) -> bool:
        """Select a dropdown option by value."""
        try:
            self.page.select_option(selector, value, timeout=timeout)
            return True
        except Exception:
            return False

    def press_key(self, key: str):
        """Press a keyboard key on the focused element."""
        try:
            self.page.keyboard.press(key)
        except Exception:
            pass

    def focus(self, selector: str, timeout: int = 5000) -> bool:
        """Focus an element."""
        try:
            self.page.focus(selector, timeout=timeout)
            return True
        except Exception:
            return False

    # ── Waiting ──

    def wait_for(self, selector: str, timeout: int = 10000) -> bool:
        """Wait for an element to appear."""
        try:
            self.page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    def wait_for_url(self, pattern: str, timeout: int = 10000) -> bool:
        """Wait for URL to match a pattern."""
        try:
            self.page.wait_for_url(f"**{pattern}**", timeout=timeout)
            return True
        except Exception:
            return False

    def wait_seconds(self, seconds: float):
        """Explicit wait."""
        time.sleep(seconds)

    def wait_networkidle(self, timeout: int = 10000):
        """Wait for network to be idle."""
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass

    # ── XHR / API Interception ──

    def capture_response(self, url_pattern: str,
                         trigger: Callable, timeout: int = 15000) -> Optional[dict]:
        """
        Capture an XHR/Fetch response by URL pattern while executing a trigger action.

        Usage:
            data = browser.capture_response(
                "/api/search",
                trigger=lambda: browser.click("#search-btn"),
                timeout=15000
            )

        Returns parsed JSON dict, or None if not captured / not JSON.
        """
        captured = {}

        def on_response(response: Response):
            try:
                if url_pattern in response.url and response.status == 200:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        captured["data"] = response.json()
                    else:
                        captured["data"] = {"_text": response.text()[:5000]}
            except Exception:
                pass

        self.page.on("response", on_response)
        try:
            trigger()
            # Give the browser time to receive and process the response
            deadline = time.time() + timeout / 1000
            while time.time() < deadline:
                if "data" in captured:
                    break
                time.sleep(0.2)
        finally:
            self.page.remove_listener("response", on_response)

        return captured.get("data")

    # ── Utilities ──

    def _dismiss_cookie_banner(self):
        """Try to dismiss common cookie consent banners (best-effort)."""
        selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Accept')",
            "button:has-text('Akzeptieren')",
            "button:has-text('Alle akzeptieren')",
            "button:has-text('Zaakceptuj wszystkie')",
            "button:has-text('Zaakceptuj')",
            "#cookie-accept",
            ".cookie-accept",
            "[data-testid='cookie-accept']",
            "#onetrust-accept-btn-handler",
            ".CookieConsent button",
        ]
        for sel in selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click(timeout=2000)
                    logger.debug(f"Cookie banner dismissed ({sel})")
                    time.sleep(0.5)
                    return
            except Exception:
                continue

    def _screenshot(self, name: str):
        """Save a screenshot for debugging."""
        try:
            path = self.screenshot_dir / f"{name}.png"
            self.page.screenshot(path=str(path), full_page=True)
            logger.info(f"Screenshot saved: {path}")
        except Exception as e:
            logger.debug(f"Screenshot failed: {e}")

    def save_page_text(self, filename: str):
        """Save page text content to a .txt file for debugging."""
        try:
            text = self.get_page_text()
            path = self.screenshot_dir / filename
            path.write_text(text[:20000], encoding="utf-8")
            logger.info(f"Page text saved: {path} ({len(text)} chars)")
        except Exception as e:
            logger.debug(f"Page text save failed: {e}")

    def current_url(self) -> str:
        """Get current page URL."""
        try:
            return self.page.url
        except Exception:
            return ""

    def query_all(self, selector: str) -> list:
        """Return all matching ElementHandle objects."""
        try:
            return self.page.query_selector_all(selector) or []
        except Exception:
            return []

    def element_exists(self, selector: str, timeout: int = 2000) -> bool:
        """Check if a selector exists on the page."""
        try:
            el = self.page.wait_for_selector(selector, timeout=timeout)
            return el is not None
        except Exception:
            return False

    def get_links(self, selector: str = "a", base_url: str = "") -> list:
        """Get all href links matching a selector."""
        links = []
        try:
            elements = self.page.query_selector_all(selector)
            for el in elements:
                href = el.get_attribute("href") or ""
                if href:
                    if not href.startswith("http") and base_url:
                        href = base_url.rstrip("/") + "/" + href.lstrip("/")
                    links.append(href)
        except Exception:
            pass
        return links
