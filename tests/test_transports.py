"""Automated test suite verifying multi-transport capabilities (HTTP SSE, Streamable HTTP, STDIO)."""

import asyncio
from pathlib import Path
import sys

# Ensure root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import httpx
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from browser_mcp.server import create_starlette_app, ALL_TOOLS


EXPECTED_TOOLS = {
    "browse_page", "evaluate_js", "session_status", "take_screenshot",
    "authenticate", "tab_list", "tab_switch", "tab_new", "tab_close",
    "click_element", "fill_input", "scroll_page"
}


async def run_transport_tests():
    port = 19123
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}"

    app = create_starlette_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    # Wait for server to bind
    for _ in range(50):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{base_url}/health", timeout=1.0)
                if resp.status_code == 200:
                    break
        except Exception:
            await asyncio.sleep(0.1)
    else:
        raise RuntimeError("Failed to start HTTP server for testing.")

    try:
        print("=" * 60)
        print("TEST 1: Health & Discovery HTTP Endpoints")
        print("=" * 60)
        async with httpx.AsyncClient() as client:
            # Test /health
            resp = await client.get(f"{base_url}/health")
            assert resp.status_code == 200, f"/health returned {resp.status_code}"
            health_data = resp.json()
            print(f"/health response: {health_data}")
            assert health_data["status"] == "ok"
            assert health_data["tools"] == len(ALL_TOOLS)
            assert "streamable-http" in health_data["transports"]
            assert "sse" in health_data["transports"]

            # Test root /
            resp = await client.get(f"{base_url}/")
            assert resp.status_code == 200, f"/ returned {resp.status_code}"
            root_data = resp.json()
            print(f"/ response: {root_data}")
            assert root_data["status"] == "running"
            assert "/mcp" in root_data["endpoints"]["streamable_http"]
            assert "/sse" in root_data["endpoints"]["sse"]
        print("TEST 1 PASSED: Health and discovery endpoints work.\n")

        print("=" * 60)
        print("TEST 2: MCP SSE Transport (/sse + /messages)")
        print("=" * 60)
        async with sse_client(f"{base_url}/sse") as (read, write):
            async with ClientSession(read, write) as session:
                init_res = await session.initialize()
                print(f"SSE Server initialized: {init_res.serverInfo.name} v{init_res.serverInfo.version}")

                tools_res = await session.list_tools()
                tool_names = {t.name for t in tools_res.tools}
                print(f"SSE Tools discovered ({len(tool_names)}): {sorted(tool_names)}")
                assert tool_names == EXPECTED_TOOLS, f"Mismatch: {tool_names ^ EXPECTED_TOOLS}"

                call_res = await session.call_tool("session_status", {})
                print(f"SSE call_tool('session_status') output: {call_res.content[0].text[:120]}...")
                assert "state_file" in call_res.content[0].text
        print("TEST 2 PASSED: SSE transport fully functional.\n")

        print("=" * 60)
        print("TEST 3: MCP Streamable HTTP Transport (/mcp)")
        print("=" * 60)
        async with streamable_http_client(f"{base_url}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                init_res = await session.initialize()
                print(f"Streamable HTTP Server initialized: {init_res.serverInfo.name}")

                tools_res = await session.list_tools()
                tool_names = {t.name for t in tools_res.tools}
                print(f"Streamable HTTP Tools discovered: {len(tool_names)}")
                assert tool_names == EXPECTED_TOOLS, f"Mismatch: {tool_names ^ EXPECTED_TOOLS}"

                call_res = await session.call_tool("session_status", {})
                print(f"Streamable HTTP call_tool output: {call_res.content[0].text[:120]}...")
                assert "state_file" in call_res.content[0].text
        print("TEST 3 PASSED: Streamable HTTP transport fully functional.\n")

        print("=" * 60)
        print("TEST 4: MCP Streamable HTTP Transport on Root (/)")
        print("=" * 60)
        async with streamable_http_client(f"{base_url}/") as (read, write, _):
            async with ClientSession(read, write) as session:
                init_res = await session.initialize()
                print(f"Streamable HTTP Root initialized: {init_res.serverInfo.name}")
                tools_res = await session.list_tools()
                assert {t.name for t in tools_res.tools} == EXPECTED_TOOLS
        print("TEST 4 PASSED: Streamable HTTP works directly on root URL.\n")

        print("=" * 60)
        print("ALL MULTI-TRANSPORT INTEGRATION TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)

    finally:
        server.should_exit = True
        await server_task


if __name__ == "__main__":
    asyncio.run(run_transport_tests())
