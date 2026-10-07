"""Utility helpers for safe browser interaction, timeout guards, and internal scheme handling."""

import asyncio
import logging
from typing import Optional, Any
from playwright.async_api import Page

logger = logging.getLogger("browser_mcp.core.utils")

INTERNAL_SCHEMES = (
    "chrome://",
    "chrome-extension://",
    "chrome-search://",
    "chrome-error://",
    "chrome-untrusted://",
    "devtools://",
    "edge://",
    "view-source:",
    "about:",
)


def is_internal_url(url: Optional[str]) -> bool:
    """Return True if URL is empty or belongs to internal browser schemes."""
    if not url or not url.strip():
        return True
    clean_url = url.strip().lower()
    return clean_url.startswith(INTERNAL_SCHEMES)


async def safe_get_title(page: Optional[Page], timeout: float = 1.5) -> str:
    """Safely obtain page title without deadlocking on internal or uninitialized pages."""
    if not page:
        return ""

    try:
        url = getattr(page, "url", "") or ""
    except Exception:
        url = ""

    if not url or url == "about:blank" or url.startswith("chrome://new-tab-page"):
        return "New Tab"

    if is_internal_url(url):
        return url

    try:
        return await asyncio.wait_for(page.title(), timeout=timeout)
    except Exception as e:
        logger.debug("Failed to read title for '%s' within %ss: %s", url, timeout, e)
        return url or "<untitled>"


async def safe_bring_to_front(page: Optional[Page], timeout: float = 3.0) -> bool:
    """Safely bring a page to front with a timeout guard."""
    if not page:
        return False
    try:
        await asyncio.wait_for(page.bring_to_front(), timeout=timeout)
        return True
    except Exception as e:
        logger.warning("Failed to bring page to front: %s", e)
        return False


async def safe_evaluate(
    page: Optional[Page],
    script: str,
    arg: Any = None,
    timeout: float = 15.0,
) -> Any:
    """Execute JavaScript with an internal scheme guard and strict timeout."""
    if not page:
        raise ValueError("No active page available.")

    url = getattr(page, "url", "") or ""
    if is_internal_url(url):
        raise RuntimeError(
            f"Cannot evaluate JavaScript on internal browser page ({url or 'about:blank'}). Switch to a valid web page first."
        )

    eval_coro = page.evaluate(script, arg) if arg is not None else page.evaluate(script)
    return await asyncio.wait_for(eval_coro, timeout=timeout)
