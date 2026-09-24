"""MCP Server implementation and standard I/O runner for interactive-browser-mcp."""

import asyncio
import json
import logging
import sys
from typing import List
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from browser_mcp.core.session import BrowserSession
from browser_mcp.tools import ALL_TOOLS, dispatch_tool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("browser_mcp.server")

# Instantiate server and singleton browser session
server = Server("interactive-browser-mcp")
session_instance = BrowserSession()


@server.list_tools()
async def handle_list_tools() -> List[Tool]:
    """Expose the lean 12-tool suite."""
    return ALL_TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> List[TextContent]:
    """Dispatch incoming tool invocations to domain handlers."""
    try:
        result = await dispatch_tool(session_instance, name, arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as error:
        logger.error("Error executing tool '%s': %s", name, error, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(error)}, indent=2))]


async def main():
    """Run standard I/O MCP server."""
    logger.info("Starting interactive-browser-mcp server (12 tools registered)...")
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        logger.info("Shutting down browser session...")
        await session_instance.close()


if __name__ == "__main__":
    asyncio.run(main())
