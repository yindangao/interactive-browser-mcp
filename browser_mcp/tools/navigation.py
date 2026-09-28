"""Declarative definitions and handlers for navigation and session tools."""

from typing import Dict, Any, List
from mcp.types import Tool
from browser_mcp.core.session import BrowserSession
from browser_mcp.dom.reader import DOMReader

NAVIGATION_TOOLS: List[Tool] = [
    Tool(
        name="browse_page",
        description=(
            "Extract clean, noise-pruned content from a web page in Markdown format. "
            "If 'url' is provided, navigates to it; if omitted, inspects the current active tab. "
            "Supports 'wait_for_selector' to wait for dynamic elements in single-page apps (Jira, Confluence, Gemini) "
            "before reading, 'selector' to scope extraction, and 'mode' ('content', 'outline', 'links')."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Optional target URL. If omitted, inspects the current active page."
                },
                "wait_until": {
                    "type": "string",
                    "enum": ["load", "domcontentloaded", "networkidle"],
                    "default": "domcontentloaded",
                    "description": "Navigation lifecycle state to wait for."
                },
                "wait_for_selector": {
                    "type": "string",
                    "description": "Optional CSS selector to wait for before extracting content. Essential for single-page applications (Jira, Confluence, Gemini, GitHub) that render content or stream responses asynchronously."
                },
                "wait_for_timeout_ms": {
                    "type": "integer",
                    "default": 10000,
                    "description": "Max milliseconds to wait for wait_for_selector before extracting content (default 10000)."
                },
                "selector": {
                    "type": "string",
                    "description": "Optional CSS selector to scope content extraction."
                },
                "mode": {
                    "type": "string",
                    "enum": ["content", "outline", "links"],
                    "default": "content",
                    "description": "Extraction mode: 'content' for clean markdown text, 'outline' for heading hierarchy, 'links' for link list."
                },
                "max_length": {
                    "type": "integer",
                    "default": 25000,
                    "description": "Max character length before truncating output."
                }
            }
        }
    ),
    Tool(
        name="session_status",
        description="Inspect the active browser session, CDP connection state, tab count, and authentication tokens.",
        inputSchema={"type": "object", "properties": {}}
    ),
    Tool(
        name="authenticate",
        description="Surface a visible browser window for interactive Single Sign-On (SSO / MFA / PingFederate). Automatically saves session state upon successful redirect.",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target login or portal URL."},
                "timeout_seconds": {"type": "integer", "default": 900, "description": "Max seconds to wait for user completion."}
            }
        }
    ),
    Tool(
        name="tab_list",
        description="List all open tabs in the browser with index, title, URL, and active status.",
        inputSchema={"type": "object", "properties": {}}
    ),
    Tool(
        name="tab_new",
        description="Open a new browser tab and optionally navigate to a target URL.",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "default": "about:blank", "description": "URL to open in the new tab."},
                "wait_until": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle"], "default": "domcontentloaded"}
            }
        }
    ),
    Tool(
        name="tab_switch",
        description="Switch the active focus to a specific tab by its 0-based index.",
        inputSchema={
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "0-based tab index to switch to."}
            },
            "required": ["index"]
        }
    ),
    Tool(
        name="tab_close",
        description="Close a tab by its 0-based index (or close active tab if index is omitted).",
        inputSchema={
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "0-based tab index to close."}
            }
        }
    ),
]


async def handle_browse_page(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    if not await session.ensure_active():
        return {"success": False, "error": "Browser is not running."}
    return await DOMReader.browse(
        session.page,
        url=args.get("url"),
        wait_until=args.get("wait_until", "domcontentloaded"),
        wait_for_selector=args.get("wait_for_selector"),
        wait_for_timeout_ms=args.get("wait_for_timeout_ms", 10000),
        selector=args.get("selector"),
        mode=args.get("mode", "content"),
        max_length=args.get("max_length", 25000),
    )


async def handle_session_status(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    return await session.session_status()


async def handle_authenticate(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    return await session.authenticate(
        url=args.get("url"),
        timeout_seconds=args.get("timeout_seconds", 900),
    )


async def handle_tab_list(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    return await session.list_tabs()


async def handle_tab_new(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    return await session.new_tab(
        url=args.get("url", "about:blank"),
        wait_until=args.get("wait_until", "domcontentloaded"),
    )


async def handle_tab_switch(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    return await session.switch_tab(index=args.get("index", 0))


async def handle_tab_close(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    return await session.close_tab(index=args.get("index"))


NAVIGATION_HANDLERS = {
    "browse_page": handle_browse_page,
    "session_status": handle_session_status,
    "authenticate": handle_authenticate,
    "tab_list": handle_tab_list,
    "tab_new": handle_tab_new,
    "tab_switch": handle_tab_switch,
    "tab_close": handle_tab_close,
}
