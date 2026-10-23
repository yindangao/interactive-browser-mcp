"""Authentication monitoring, SSO detection, and cookie persistence."""

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlsplit
from playwright.async_api import BrowserContext, Page

from browser_mcp.config import AUTH_DOMAINS, SESSION_STATE_FILE, DEFAULT_AUTH_TIMEOUT_S

logger = logging.getLogger("browser_mcp.core.auth")


class AuthManager:
    """Handles enterprise SSO/MFA detection, session state export, and authentication loops."""

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file or SESSION_STATE_FILE

    def is_auth_domain(self, url: str) -> bool:
        """Check if a URL belongs to a corporate SSO/MFA identity provider."""
        if not url:
            return False
        url_lower = url.lower()
        return any(domain in url_lower for domain in AUTH_DOMAINS)

    def has_saved_session(self) -> bool:
        """Check if a valid storage state file exists."""
        return self.state_file.exists() and self.state_file.stat().st_size > 0

    @staticmethod
    def _mkdir_private(directory: Path) -> None:
        """Create missing directories privately without changing existing permissions."""
        if directory.is_dir():
            return
        AuthManager._mkdir_private(directory.parent)
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if not directory.is_dir():
                raise

    def _write_state_atomic(self, state: Dict[str, Any]) -> None:
        """Replace a snapshot only after a complete, private file has been written."""
        self._mkdir_private(self.state_file.parent)
        temporary = None
        try:
            # NamedTemporaryFile creates the file exclusively with mode 0600.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.state_file.parent,
                prefix=f".{self.state_file.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_file)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def save_storage_state(
        self, context: BrowserContext, *, page: Optional[Page] = None,
    ) -> bool:
        """Export a private snapshot, scoped to the selected page's native profile.

        A CDP-connected context can flatten several native Chrome profiles; its
        storage_state() must never be used when a selected page is available.
        Context-only export remains supported for legacy, single-profile callers.
        Only the selected web page's localStorage origin is included.
        """
        try:
            if page is None:
                state = await context.storage_state()
            else:
                cdp = await context.new_cdp_session(page)
                try:
                    result = await cdp.send("Network.getAllCookies")
                    # Strip CDP-only metadata so the result is Playwright storage
                    # state, rather than a raw Network.Cookie response.
                    fields = ("name", "value", "domain", "path", "expires", "httpOnly", "secure")
                    cookies = []
                    for cookie in result["cookies"]:
                        exported = {field: cookie[field] for field in fields}
                        exported["sameSite"] = cookie.get("sameSite", "Lax")
                        cookies.append(exported)
                    origins = []
                    if urlsplit(page.url).scheme.lower() in {"http", "https"}:
                        # Recheck the protocol in-page: navigation may have
                        # happened since page.url was read. Capture origin and
                        # storage together so they always refer to one document.
                        origin = await page.evaluate("""() => {
                            if (!['http:', 'https:'].includes(location.protocol)) return null;
                            return {
                                origin: location.origin,
                                localStorage: Object.keys(localStorage).map(name => ({
                                    name, value: localStorage.getItem(name)
                                }))
                            };
                        }""")
                        if origin is not None:
                            origins.append(origin)
                    state = {"cookies": cookies, "origins": origins}
                finally:
                    await cdp.detach()
            self._write_state_atomic(state)
            logger.info("Saved browser storage state to %s", self.state_file)
            return True
        except Exception as error:
            # CDP/evaluation exceptions may contain authentication material.
            logger.error("Failed to save storage state (%s)", type(error).__name__)
            return False

    async def load_storage_state(self) -> Optional[Dict[str, Any]]:
        """Read storage state file if present."""
        if not self.has_saved_session():
            return None
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as error:
            logger.error("Failed to load storage state: %s", error)
            return None

    async def monitor_auth(
        self,
        page: Page,
        context: BrowserContext,
        timeout_seconds: int = DEFAULT_AUTH_TIMEOUT_S,
        poll_interval: float = 2.0,
    ) -> bool:
        """Poll the active page until it redirects away from SSO domains to a target application."""
        start_time = datetime.now()
        logger.info("Starting auth monitoring (timeout: %ds)...", timeout_seconds)

        while (datetime.now() - start_time).total_seconds() < timeout_seconds:
            try:
                current_url = page.url
                if not self.is_auth_domain(current_url) and current_url != "about:blank":
                    logger.info("Auth complete! Redirected to: %s", current_url)
                    await asyncio.sleep(2.0)  # Allow cookies to settle
                    return await self.save_storage_state(context, page=page)
            except Exception as e:
                logger.debug("Page check error during auth monitoring: %s", e)

            await asyncio.sleep(poll_interval)

        logger.warning("Auth monitoring timed out after %ds", timeout_seconds)
        return False
