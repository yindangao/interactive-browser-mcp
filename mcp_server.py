"""MCP server for interactive browser automation."""

import asyncio
import json
import os
import sys
from pathlib import Path
from mcp.server import Server
from mcp.types import Tool, TextContent

from browser_session_manager import BrowserSessionManager

# Resolve paths portably relative to the server location
BASE_DIR = Path(__file__).resolve().parent
state_file_path = str(Path(os.environ.get("BROWSER_SESSION_STATE", BASE_DIR / "browser_session_state.json")))
session_manager = BrowserSessionManager(state_file=state_file_path)

# Initialize MCP server
server = Server("interactive-browser-mcp")

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools for interactive browser automation."""
    return [
        Tool(
            name="browse_page",
            description="Navigate the visible browser to a webpage to establish the domain origin and verify/load SSO session cookies. Supports fast SPA loading via the 'wait_until' option.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL of the webpage or document to navigate to."
                    },
                    "wait_until": {
                        "type": "string",
                        "description": "Navigation wait strategy: 'domcontentloaded' (fast, default), 'load', or 'networkidle'. Prefer 'domcontentloaded' for SPAs (Jira, Teams, Confluence) to avoid long network-idle timeouts.",
                        "default": "domcontentloaded",
                        "enum": ["domcontentloaded", "load", "networkidle"]
                    }
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="evaluate_js",
            description="Execute custom JavaScript code directly in the active browser page context and return the result. PRIMARY TOOL for interacting with internal web applications: use fetch() to query/mutate authenticated REST APIs (e.g. Jira /rest/api/2/..., Confluence, ServiceNow) with existing corporate SSO session cookies, or extract structured DOM data. For asynchronous operations, always wrap in an async IIFE: '(async () => { const res = await fetch(...); return await res.json(); })()'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "The JavaScript code string to execute. Wrap async code in an IIFE: '(async () => { ... })()'."
                    }
                },
                "required": ["script"]
            }
        ),
        Tool(
            name="session_status",
            description="Retrieve status of the current browser session: active page URL, page title, open tab count, CDP connection status, and whether login cookies exist, without making network requests.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="take_screenshot",
            description="Capture a screenshot of the currently active browser page in the visible window. Useful for visually analyzing complex charts, layouts, or verifying page load state.",
            inputSchema={
                "type": "object",
                "properties": {
                    "output_path": {
                        "type": "string",
                        "description": "Optional custom absolute path to save the screenshot image file, e.g. /path/to/screenshot.png"
                    }
                }
            }
        ),
        Tool(
            name="authenticate",
            description="Open a visible Chrome browser window to perform manual SSO/MFA login. Optionally navigates directly to the specified target URL and saves authenticated session cookies once complete.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Optional target enterprise URL to navigate to for login (e.g. 'https://jira.walmart.com')."
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Optional timeout in seconds to wait for user login. Defaults to 900 (15 minutes).",
                        "default": 900
                    }
                }
            }
        ),
        Tool(
            name="tab_list",
            description="List all currently open tabs in the browser session, returning their 0-based index, URL, title, and whether each tab is currently active.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="tab_switch",
            description="Switch active focus to a specific tab using its 0-based integer index from tab_list.",
            inputSchema={
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The 0-based index of the tab to switch to."
                    }
                },
                "required": ["index"]
            }
        ),
        Tool(
            name="tab_new",
            description="Open a new browser tab, optionally navigating to a URL, and make it the active tab.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Optional URL to navigate to in the new tab. Defaults to 'about:blank'."
                    },
                    "wait_until": {
                        "type": "string",
                        "description": "Optional wait strategy: 'domcontentloaded' (default), 'load', or 'networkidle'.",
                        "default": "domcontentloaded",
                        "enum": ["domcontentloaded", "load", "networkidle"]
                    }
                }
            }
        ),
        Tool(
            name="tab_close",
            description="Close a specific tab by its 0-based index from tab_list, or close the currently active tab if no index is provided.",
            inputSchema={
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "Optional 0-based index of the tab to close. If omitted, closes the active tab."
                    }
                }
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
    """Handle tool invocations."""
    try:
        if name == "authenticate":
            timeout_seconds = int(arguments.get("timeout_seconds", 900))
            url = arguments.get("url")
            success = await session_manager.authenticate(url=url, timeout_seconds=timeout_seconds)
            return [TextContent(type="text", text=json.dumps({"success": success}))]

        elif name == "browse_page":
            url = arguments.get("url", "")
            wait_until = arguments.get("wait_until", "domcontentloaded")
            result = await session_manager.browse_page(url, wait_until=wait_until)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "session_status":
            exists = Path(state_file_path).exists()
            active_url = session_manager.page.url if session_manager.page else None
            active_title = None
            if session_manager.page:
                try:
                    active_title = await session_manager.page.title()
                except Exception:
                    pass
            open_tabs = len(session_manager.context.pages) if session_manager.context else 0
            status = {
                "saved_session_exists": exists,
                "state_file": state_file_path,
                "authenticated_active": session_manager.authenticated,
                "active_url": active_url,
                "active_title": active_title,
                "open_tabs": open_tabs,
                "is_cdp_connection": session_manager.is_cdp_connection,
                "timestamp": session_manager.session_started_at.isoformat() if session_manager.session_started_at else None
            }
            return [TextContent(type="text", text=json.dumps(status, indent=2))]

        elif name == "take_screenshot":
            default_screenshot = str(BASE_DIR / "screenshot.png")
            output_path = arguments.get("output_path", default_screenshot)
            result = await session_manager.take_screenshot(output_path=output_path)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "evaluate_js":
            script = arguments.get("script", "")
            result = await session_manager.evaluate_js(script=script)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "tab_list":
            result = await session_manager.list_tabs()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "tab_switch":
            index = int(arguments.get("index", 0))
            result = await session_manager.switch_tab(index=index)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "tab_new":
            url = arguments.get("url", "about:blank")
            wait_until = arguments.get("wait_until", "domcontentloaded")
            result = await session_manager.new_tab(url=url, wait_until=wait_until)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "tab_close":
            index_val = arguments.get("index")
            index = int(index_val) if index_val is not None else None
            result = await session_manager.close_tab(index=index)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error running tool: {e}")]

async def main():
    """Start the MCP server using stdin/stdout streams."""
    from mcp.server.stdio import stdio_server

    print("interactive-browser-mcp server starting...", file=sys.stderr)
    print("Tools available: authenticate, browse_page, evaluate_js, session_status, tab_close, tab_list, tab_new, tab_switch, take_screenshot", file=sys.stderr)

    # Auto-initialize session if saved state already exists and auto-start is enabled.
    # Set AUTO_START_BROWSER=false to lazy-load the browser only when browser-based tools are called.
    auto_start = os.environ.get("AUTO_START_BROWSER", "true").lower() in ("true", "1", "yes")
    if auto_start and Path(state_file_path).exists():
        print(f"Found saved browser session cookies. Auto-initializing visible browser session...", file=sys.stderr)
        try:
            ok = await session_manager.session_start()
            if ok:
                print("Visible browser session ready and active.", file=sys.stderr)
            else:
                print("Failed to restore previous session. Please run authenticate to sign in.", file=sys.stderr)
        except Exception as e:
            print(f"Auto-init failed with error: {e}", file=sys.stderr)
    else:
        print("No browser_session_state.json found. Run authenticate first.", file=sys.stderr)

    try:
        async with stdio_server() as (read_stream, write_stream):
            init = server.create_initialization_options()
            await server.run(read_stream, write_stream, init, raise_exceptions=False)
    finally:
        print("Shutting down interactive-browser-mcp and cleaning up browser sessions...", file=sys.stderr)
        await session_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
