"""Declarative definitions and handlers for script execution and screenshot tools."""

from typing import Dict, Any, List
from mcp.types import Tool
from browser_mcp.core.session import BrowserSession
from browser_mcp.dom.actions import DOMActions

SCRIPT_TOOLS: List[Tool] = [
    Tool(
        name="evaluate_js",
        description=(
            "Execute custom JavaScript in the active page context. Use this for the API-First pattern: "
            "run window.fetch() to query internal REST endpoints (Jira, Confluence, ServiceNow) "
            "leveraging the browser's active SSO cookies and session headers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "JavaScript code to execute in the page context. Can be synchronous or return a Promise."
                }
            },
            "required": ["script"]
        }
    ),
    Tool(
        name="take_screenshot",
        description="Capture a visual screenshot of the current page viewport and save it to disk.",
        inputSchema={
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "Optional file path to save the screenshot. Defaults to .data/screenshot.png."
                }
            }
        }
    ),
]


async def handle_evaluate_js(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    if not await session.ensure_active():
        return {"success": False, "error": "Browser is not running."}
    return await DOMActions.evaluate_js(session.page, script=args["script"])


async def handle_take_screenshot(session: BrowserSession, args: Dict[str, Any]) -> Dict[str, Any]:
    if not await session.ensure_active():
        return {"success": False, "error": "Browser is not running."}
    return await DOMActions.take_screenshot(session.page, output_path=args.get("output_path"))


SCRIPT_HANDLERS = {
    "evaluate_js": handle_evaluate_js,
    "take_screenshot": handle_take_screenshot,
}
