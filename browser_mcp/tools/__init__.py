"""Unified tool registry and dispatcher for interactive-browser-mcp."""

from typing import List, Dict, Any, Callable, Coroutine
from mcp.types import Tool
from browser_mcp.core.session import BrowserSession
from browser_mcp.tools.navigation import NAVIGATION_TOOLS, NAVIGATION_HANDLERS
from browser_mcp.tools.interaction import INTERACTION_TOOLS, INTERACTION_HANDLERS
from browser_mcp.tools.script import SCRIPT_TOOLS, SCRIPT_HANDLERS

ALL_TOOLS: List[Tool] = NAVIGATION_TOOLS + INTERACTION_TOOLS + SCRIPT_TOOLS

TOOL_HANDLERS: Dict[str, Callable[[BrowserSession, Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]] = {
    **NAVIGATION_HANDLERS,
    **INTERACTION_HANDLERS,
    **SCRIPT_HANDLERS,
}


async def dispatch_tool(session: BrowserSession, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Route tool execution to its registered handler."""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        raise ValueError(f"Unknown tool: '{name}'. Available tools: {list(TOOL_HANDLERS.keys())}")
    return await handler(session, arguments or {})
