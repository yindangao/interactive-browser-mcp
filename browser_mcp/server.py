"""MCP Server implementation and multi-transport runner for interactive-browser-mcp.

Supports both:
1. Standard I/O (stdio) transport (default, used by local agent subprocesses).
2. HTTP transport supporting both Streamable HTTP (/mcp) and SSE (/sse, /messages).
"""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
from typing import List, Optional

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn

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
        args = arguments or {}
        if name == "authenticate":
            timeout_limit = float(args.get("timeout_seconds", 900)) + 30.0
        else:
            timeout_limit = 60.0

        result = await asyncio.wait_for(
            dispatch_tool(session_instance, name, args),
            timeout=timeout_limit,
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except asyncio.TimeoutError:
        error_msg = f"Tool '{name}' timed out after {timeout_limit}s."
        logger.error(error_msg)
        return [TextContent(type="text", text=json.dumps({"success": False, "error": error_msg}, indent=2))]
    except Exception as error:
        logger.error("Error executing tool '%s': %s", name, error, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(error)}, indent=2))]


# -----------------------------------------------------------------------------
# Standard I/O Transport
# -----------------------------------------------------------------------------

async def run_stdio():
    """Run standard I/O MCP server."""
    logger.info("Starting interactive-browser-mcp server over STDIO (12 tools registered)...")
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


# -----------------------------------------------------------------------------
# HTTP Transport (Streamable HTTP + SSE + Health Check)
# -----------------------------------------------------------------------------

class SseApp:
    """ASGI application wrapping MCP Server-Sent Events (SSE)."""

    def __init__(self, sse_transport: SseServerTransport, mcp_server: Server):
        self.sse_transport = sse_transport
        self.mcp_server = mcp_server

    async def __call__(self, scope, receive, send):
        async with self.sse_transport.connect_sse(scope, receive, send) as (read_stream, write_stream):
            await self.mcp_server.run(
                read_stream,
                write_stream,
                self.mcp_server.create_initialization_options(),
            )


class MessagesApp:
    """ASGI application handling POST messages for active SSE sessions."""

    def __init__(self, sse_transport: SseServerTransport):
        self.sse_transport = sse_transport

    async def __call__(self, scope, receive, send):
        await self.sse_transport.handle_post_message(scope, receive, send)


class StreamableApp:
    """ASGI application handling modern MCP Streamable HTTP requests."""

    def __init__(self, streamable_manager: StreamableHTTPSessionManager):
        self.streamable_manager = streamable_manager

    async def __call__(self, scope, receive, send):
        await self.streamable_manager.handle_request(scope, receive, send)


class RootApp:
    """Root endpoint router handling Streamable HTTP and browser/info requests."""

    def __init__(
        self,
        streamable_manager: StreamableHTTPSessionManager,
        mcp_server_name: str,
        tools_count: int,
    ):
        self.streamable_manager = streamable_manager
        self.mcp_server_name = mcp_server_name
        self.tools_count = tools_count

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            headers = dict(scope.get("headers", []))
            has_mcp_header = (
                b"mcp-protocol-version" in headers
                or b"last-event-id" in headers
                or b"mcp-session-id" in headers
            )
            method = scope.get("method", "GET")
            if method in ("POST", "DELETE") or has_mcp_header:
                await self.streamable_manager.handle_request(scope, receive, send)
                return

            response = JSONResponse({
                "name": self.mcp_server_name,
                "status": "running",
                "version": "0.2.0",
                "endpoints": {
                    "streamable_http": "/mcp",
                    "sse": "/sse",
                    "messages": "/messages",
                    "health": "/health",
                },
                "tools_count": self.tools_count,
            })
            await response(scope, receive, send)
            return

        await self.streamable_manager.handle_request(scope, receive, send)


async def handle_health_check(request) -> JSONResponse:
    """Health and status endpoint returning browser session and tool availability."""
    cdp_status = "disconnected"
    if session_instance.page and not session_instance.page.is_closed():
        cdp_status = "active"
    elif session_instance.browser:
        cdp_status = "connected"

    return JSONResponse({
        "status": "ok",
        "name": server.name,
        "tools": len(ALL_TOOLS),
        "transports": ["stdio", "streamable-http", "sse"],
        "browser_session": {
            "cdp_port": session_instance.cdp_port,
            "status": cdp_status,
        },
    })


def create_starlette_app() -> Starlette:
    """Build and configure the Starlette application with MCP HTTP transports."""
    enable_dns = os.environ.get("MCP_ENABLE_DNS_REBINDING", "false").strip().lower() in ("true", "1", "yes")
    allowed_hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "*").split(",") if h.strip()]

    if "*" in allowed_hosts or not enable_dns:
        sec_settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    else:
        sec_settings = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
        )

    sse_transport = SseServerTransport(endpoint="/messages", security_settings=sec_settings)
    streamable_manager = StreamableHTTPSessionManager(
        app=server,
        security_settings=sec_settings,
        stateless=False,
    )

    @contextlib.asynccontextmanager
    async def app_lifespan(app: Starlette):
        async with streamable_manager.run():
            yield
        logger.info("HTTP server stopping. Detaching browser session...")
        await session_instance.close()

    routes = [
        Route("/health", endpoint=handle_health_check, methods=["GET"]),
        Route("/status", endpoint=handle_health_check, methods=["GET"]),
        Route("/sse", endpoint=SseApp(sse_transport, server), methods=["GET"]),
        Route("/messages", endpoint=MessagesApp(sse_transport), methods=["POST"]),
        Route("/mcp", endpoint=StreamableApp(streamable_manager), methods=["GET", "POST", "DELETE"]),
        Route(
            "/",
            endpoint=RootApp(streamable_manager, server.name, len(ALL_TOOLS)),
            methods=["GET", "POST", "DELETE"],
        ),
    ]

    return Starlette(routes=routes, lifespan=app_lifespan)


async def run_http(
    host: str = "127.0.0.1",
    port: int = 8000,
    log_level: str = "info",
    app: Optional[Starlette] = None,
):
    """Run HTTP MCP server supporting Streamable HTTP and SSE."""
    if app is None:
        app = create_starlette_app()
    logger.info(
        "Starting interactive-browser-mcp HTTP server on http://%s:%s (endpoints: /mcp, /sse, /health)...",
        host,
        port,
    )
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level.lower(),
        lifespan="on",
    )
    http_server = uvicorn.Server(config)
    await http_server.serve()


# -----------------------------------------------------------------------------
# Main & CLI Dispatcher
# -----------------------------------------------------------------------------

async def main(argv: Optional[List[str]] = None):
    """Main entrypoint dispatching to stdio or HTTP transport based on CLI flags and env."""
    parser = argparse.ArgumentParser(
        description="interactive-browser-mcp: Persistent browser automation MCP server"
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio").lower(),
        help="Transport type: 'stdio' for standard I/O (default), 'http'/'sse'/'streamable-http' for web server.",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Shorthand for --transport http",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "127.0.0.1"),
        help="Host address for HTTP server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8000")),
        help="Port for HTTP server (default: 8000)",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "info"),
        help="Log level (default: info)",
    )

    args = parser.parse_args(argv)
    transport = "http" if args.http else args.transport

    if transport == "stdio":
        await run_stdio()
    elif transport in ("http", "sse", "streamable-http"):
        await run_http(host=args.host, port=args.port, log_level=args.log_level)
    else:
        raise ValueError(f"Unsupported transport: {transport}")


__all__ = [
    "server",
    "session_instance",
    "handle_list_tools",
    "handle_call_tool",
    "main",
    "cli",
    "run_stdio",
    "run_http",
    "create_starlette_app",
]


def cli():
    """Synchronous CLI entry point for console scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
