"""Declarative definitions and handlers for user interaction tools."""

from typing import Dict, Any, List
from mcp.types import Tool
from browser_mcp.core.session import BrowserSession
from browser_mcp.dom.actions import DOMActions

INTERACTION_TOOLS: List[Tool] = [
    Tool(
        name="click_element",
        description=(
            "Click an interactive element on the active page. Accepts standard CSS selectors "
            "(e.g., '#submit-btn', 'button.continue') or plain text matches (e.g., 'Android', 'Sign in'). "
            "Visually highlights the element before clicking."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector or text match (e.g., '#my-btn', 'Submit', 'text=\"Next\"')."
                },
                "timeout_ms": {
                    "type": "integer",
                    "default": 10000,
                    "description": "Max milliseconds to wait for the element to become actionable."
                }
            },
            "required": ["selector"]
        }
    ),
    Tool(
        name="fill_input",
        description=(
            "Type text into an input or textarea field. Optionally simulates pressing Enter immediately "
            "after filling to submit forms or search queries in a single step."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector targeting the input element."
                },
                "text": {
                    "type": "string",
                    "description": "Text to fill into the input."
                },
                "press_enter": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to simulate pressing the Enter key after typing."
                },
                "timeout_ms": {
                    "type": "integer",
                    "default": 10000,
                    "description": "Max milliseconds to wait for the input."
                }
            },
            "required": ["selector", "text"]
        }
    ),
    Tool(
        name="scroll_page",
        description=(
            "Scroll the active page or a nested virtualized scrollable container. "
            "Essential for infinite scroll feeds (e.g., Microsoft Teams chats, Slack feeds, Jira boards) "
            "where older items only mount into the DOM when scrolled into view."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "top", "bottom"],
                    "default": "down",
                    "description": "Scroll direction."
                },
                "amount": {
                    "type": "integer",
                    "default": 500,
                    "description": "Pixel distance to scroll (for 'up' or 'down')."
                },
                "selector": {
                    "type": "string",
                    "description": "Optional CSS selector targeting a specific scrollable container. If omitted, auto-detects scrollable elements or scrolls window."
                }
            }
        }
    ),
]


async def handle_click_element(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    if not await session.ensure_active():
        return {"success": False, "error": "Browser is not running."}
    return await DOMActions.click(
        session.page,
        selector=args["selector"],
        timeout_ms=args.get("timeout_ms", 10000),
    )


async def handle_fill_input(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    if not await session.ensure_active():
        return {"success": False, "error": "Browser is not running."}
    return await DOMActions.fill(
        session.page,
        selector=args["selector"],
        text=args["text"],
        press_enter=args.get("press_enter", False),
        timeout_ms=args.get("timeout_ms", 10000),
    )


async def handle_scroll_page(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    if not await session.ensure_active():
        return {"success": False, "error": "Browser is not running."}
    return await DOMActions.scroll(
        session.page,
        direction=args.get("direction", "down"),
        amount=args.get("amount", 500),
        selector=args.get("selector"),
    )


INTERACTION_HANDLERS = {
    "click_element": handle_click_element,
    "fill_input": handle_fill_input,
    "scroll_page": handle_scroll_page,
}
