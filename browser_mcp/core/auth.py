"""Authentication monitoring, SSO detection, and cookie persistence."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
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

    async def save_storage_state(self, context: BrowserContext) -> bool:
        """Export browser cookies and origins to the session state file."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(self.state_file))
            logger.info("Saved browser storage state to %s", self.state_file)
            return True
        except Exception as error:
            logger.error("Failed to save storage state: %s", error)
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
                    await self.save_storage_state(context)
                    return True
            except Exception as e:
                logger.debug("Page check error during auth monitoring: %s", e)

            await asyncio.sleep(poll_interval)

        logger.warning("Auth monitoring timed out after %ds", timeout_seconds)
        return False
