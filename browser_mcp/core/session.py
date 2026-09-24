"""Playwright browser lifecycle, persistent CDP socket management, and tab routing."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
)

from browser_mcp.config import (
    CDP_PORT,
    CDP_URL,
    CHROME_PROFILE_DIR,
    SESSION_STATE_FILE,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    DEFAULT_AUTH_TIMEOUT_S,
)
from browser_mcp.core.auth import AuthManager

logger = logging.getLogger("browser_mcp.core.session")


class BrowserSession:
    """Manages Playwright browser lifecycle, CDP connection, and tab state."""

    def __init__(
        self,
        cdp_port: int = CDP_PORT,
        profile_dir: Optional[Path] = None,
        state_file: Optional[Path] = None,
    ):
        self.cdp_port = cdp_port
        self.cdp_url = f"http://127.0.0.1:{cdp_port}"
        self.profile_dir = profile_dir or CHROME_PROFILE_DIR
        self.state_file = state_file or SESSION_STATE_FILE
        self.auth_manager = AuthManager(state_file=self.state_file)

        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_cdp_connection: bool = False

    async def start(self, url: Optional[str] = None, headless: bool = False) -> bool:
        """Connect to an existing Chromium instance via CDP or launch a new persistent context."""
        try:
            if not self.playwright:
                self.playwright = await async_playwright().start()

            # Attempt 1: Reconnect to running Chrome on remote debugging port
            try:
                logger.info("Attempting CDP connect on port %d...", self.cdp_port)
                self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_url)
                self.is_cdp_connection = True

                if self.browser.contexts:
                    self.context = self.browser.contexts[0]
                else:
                    self.context = await self.browser.new_context()

                if self.context.pages:
                    self.page = self.context.pages[-1]
                else:
                    self.page = await self.context.new_page()

                logger.info("Successfully connected to existing browser session via CDP")
                if url:
                    await self.page.goto(url, wait_until="domcontentloaded")
                return True
            except Exception as cdp_err:
                logger.info("CDP connect failed (%s), launching persistent browser...", cdp_err)

            # Attempt 2: Launch fresh persistent browser instance with remote debugging port
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=headless,
                args=[
                    f"--remote-debugging-port={self.cdp_port}",
                    "--disable-blink-features=AutomationControlled",
                ],
                viewport={"width": 1280, "height": 800},
            )
            self.is_cdp_connection = False

            if self.context.pages:
                self.page = self.context.pages[0]
            else:
                self.page = await self.context.new_page()

            logger.info("Launched persistent Chromium context (headless=%s)", headless)
            if url:
                await self.page.goto(url, wait_until="domcontentloaded")
            return True

        except Exception as error:
            logger.error("Failed to start browser session: %s", error)
            return False

    async def ensure_active(self) -> bool:
        """Verify the browser and active page are responsive; reconnect if needed."""
        try:
            if self.page and not self.page.is_closed():
                # Quick health check
                _ = self.page.url
                return True
        except Exception:
            pass

        logger.info("Active page not responsive. Reconnecting browser session...")
        return await self.start()

    async def list_tabs(self) -> Dict[str, Any]:
        """List all open tabs in the browser context."""
        if not await self.ensure_active():
            return {"success": False, "error": "Browser is not running."}

        tabs: List[Dict[str, Any]] = []
        pages = self.context.pages if self.context else []
        for idx, p in enumerate(pages):
            try:
                tabs.append({
                    "index": idx,
                    "title": await p.title(),
                    "url": p.url,
                    "is_active": (p == self.page),
                })
            except Exception:
                tabs.append({
                    "index": idx,
                    "title": "<error reading tab>",
                    "url": "<unknown>",
                    "is_active": (p == self.page),
                })

        return {
            "success": True,
            "total_tabs": len(tabs),
            "tabs": tabs,
            "timestamp": datetime.now().isoformat(),
        }

    async def switch_tab(self, index: int) -> Dict[str, Any]:
        """Switch focus to the tab at index."""
        if not await self.ensure_active():
            return {"success": False, "error": "Browser is not running."}

        pages = self.context.pages if self.context else []
        if 0 <= index < len(pages):
            self.page = pages[index]
            await self.page.bring_to_front()
            return {
                "success": True,
                "message": f"Switched to tab {index}",
                "title": await self.page.title(),
                "url": self.page.url,
                "timestamp": datetime.now().isoformat(),
            }
        return {"success": False, "error": f"Tab index {index} out of range (0-{len(pages) - 1})"}

    async def new_tab(self, url: str = "about:blank", wait_until: str = "domcontentloaded") -> Dict[str, Any]:
        """Open a new tab and navigate to url."""
        if not await self.ensure_active():
            return {"success": False, "error": "Browser is not running."}

        try:
            new_p = await self.context.new_page()
            self.page = new_p
            if url and url != "about:blank":
                await self.page.goto(url, wait_until=wait_until, timeout=DEFAULT_PAGE_LOAD_TIMEOUT_MS)
            return {
                "success": True,
                "message": "Opened new tab",
                "tab_index": len(self.context.pages) - 1,
                "url": self.page.url,
                "title": await self.page.title(),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as error:
            return {"success": False, "error": f"Failed to open new tab: {error}"}

    async def close_tab(self, index: Optional[int] = None) -> Dict[str, Any]:
        """Close specified tab (or active tab if index is None)."""
        if not await self.ensure_active():
            return {"success": False, "error": "Browser is not running."}

        pages = self.context.pages if self.context else []
        target = self.page if index is None else (pages[index] if 0 <= index < len(pages) else None)
        if not target:
            return {"success": False, "error": f"Invalid tab index {index}"}

        try:
            closed_url = target.url
            await target.close()
            remaining = self.context.pages
            if remaining:
                self.page = remaining[-1]
                await self.page.bring_to_front()
            else:
                self.page = None

            return {
                "success": True,
                "message": "Closed tab",
                "closed_url": closed_url,
                "remaining_tabs": len(remaining),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as error:
            return {"success": False, "error": f"Failed to close tab: {error}"}

    async def session_status(self) -> Dict[str, Any]:
        """Inspect current browser state, CDP connectivity, and saved authentication tokens."""
        status = {
            "saved_session_exists": self.auth_manager.has_saved_session(),
            "state_file": str(self.state_file),
            "authenticated_active": False,
            "active_url": None,
            "active_title": None,
            "open_tabs": 0,
            "is_cdp_connection": self.is_cdp_connection,
            "timestamp": datetime.now().isoformat(),
        }

        if self.page and not self.page.is_closed():
            try:
                status["active_url"] = self.page.url
                status["active_title"] = await self.page.title()
                status["open_tabs"] = len(self.context.pages) if self.context else 0
                status["authenticated_active"] = not self.auth_manager.is_auth_domain(status["active_url"])
            except Exception as e:
                logger.debug("Error retrieving active page details: %s", e)

        return status

    async def authenticate(self, url: Optional[str] = None, timeout_seconds: int = DEFAULT_AUTH_TIMEOUT_S) -> Dict[str, Any]:
        """Surface visible browser window for manual SSO/MFA authentication."""
        if not self.browser or self.is_cdp_connection:
            started = await self.start(url=url, headless=False)
            if not started:
                return {"success": False, "error": "Failed to launch browser for authentication."}
        elif url and self.page:
            await self.page.goto(url, wait_until="domcontentloaded")

        if not self.page:
            return {"success": False, "error": "No active page available."}

        auth_success = await self.auth_manager.monitor_auth(
            self.page, self.context, timeout_seconds=timeout_seconds
        )
        return {
            "success": auth_success,
            "authenticated": auth_success,
            "current_url": self.page.url,
            "title": await self.page.title(),
            "timestamp": datetime.now().isoformat(),
        }

    async def close(self) -> None:
        """Gracefully close browser and playwright instances."""
        try:
            if self.context:
                await self.auth_manager.save_storage_state(self.context)
            if self.browser:
                await self.browser.close()
            elif self.context:
                await self.context.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as error:
            logger.warning("Error during browser close: %s", error)
        finally:
            self.browser = None
            self.context = None
            self.page = None
            self.playwright = None
