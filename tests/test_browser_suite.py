"""Comprehensive test suite for interactive-browser-mcp modular architecture."""

import asyncio
import sys
from pathlib import Path

# Ensure root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from browser_mcp import BrowserSession, DOMReader, DOMActions
from browser_mcp.server import handle_list_tools, handle_call_tool


async def run_tests():
    print("=" * 60)
    print("TEST 1: Verifying list_tools schema registration (12 tools)")
    print("=" * 60)
    tools = await handle_list_tools()
    tool_names = [t.name for t in tools]
    print(f"Registered tools count: {len(tool_names)}")
    print(f"Tool list: {tool_names}")

    expected_tools = {
        "browse_page", "evaluate_js", "session_status", "take_screenshot",
        "authenticate", "tab_list", "tab_switch", "tab_new", "tab_close",
        "click_element", "fill_input", "scroll_page"
    }
    assert set(tool_names) == expected_tools, f"Mismatch in tools: {set(tool_names) ^ expected_tools}"
    print("TEST 1 PASSED: All 12 tools successfully registered in modular package.\n")

    print("=" * 60)
    print("TEST 2: Testing live browser session and DOMReader modes")
    print("=" * 60)
    session = BrowserSession()
    # Test starting session (will launch Chromium using .data/chrome_profile if CDP not active)
    active = await session.start(url="https://example.com")
    print(f"Session started: {active}")
    assert active, "Failed to connect to browser session"

    # Test Outline Mode
    outline_res = await DOMReader.browse(session.page, mode="outline")
    print("\n[Outline Mode Result]:")
    print(outline_res.get("content", "")[:300] + "...")
    assert outline_res["success"], f"Outline mode failed: {outline_res}"
    print("TEST 2A PASSED: Outline mode extracted clean heading hierarchy.")

    # Test Links Mode
    links_res = await DOMReader.browse(session.page, mode="links")
    print("\n[Links Mode Result (sample)]:")
    first_few_links = "\n".join(links_res.get("content", "").splitlines()[:5])
    print(first_few_links)
    assert links_res["success"], f"Links mode failed: {links_res}"
    print("TEST 2B PASSED: Links mode extracted clean Markdown links.")

    # Test Content Mode with Boilerplate Stripping & Truncation limit
    content_res = await DOMReader.browse(session.page, mode="content", max_length=1500)
    print(f"\n[Content Mode Result length: {len(content_res.get('content', ''))} chars]:")
    print(content_res.get("content", "")[:400] + "...")
    assert content_res["success"], f"Content mode failed: {content_res}"
    assert "Personalize Snapshots" not in content_res.get("content", ""), "Mega-menu noise was not stripped!"
    print("TEST 2C PASSED: Content mode successfully stripped mega-menus and noise!")

    print("\n" + "=" * 60)
    print("TEST 3: Testing DOMActions.scroll")
    print("=" * 60)
    scroll_res = await DOMActions.scroll(session.page, direction="down", amount=300)
    print(f"Scroll result: {scroll_res}")
    assert scroll_res["success"], f"scroll failed: {scroll_res}"
    print("TEST 3 PASSED: DOMActions.scroll executed successfully.\n")

    print("=" * 60)
    print("TEST 4: Testing handle_call_tool via MCP dispatcher")
    print("=" * 60)
    eval_call = await handle_call_tool("evaluate_js", {"script": "document.title"})
    print(f"handle_call_tool('evaluate_js') output: {eval_call[0].text}")
    assert '"success": true' in eval_call[0].text
    assert '"result":' in eval_call[0].text
    print("TEST 4 PASSED: handle_call_tool dispatched evaluate_js successfully.\n")

    print("=" * 60)
    print("TEST 5: Testing session_status and tab_list tools")
    print("=" * 60)
    status_call = await handle_call_tool("session_status", {})
    tabs_call = await handle_call_tool("tab_list", {})
    print(f"session_status output: {status_call[0].text}")
    print(f"tab_list output: {tabs_call[0].text}")
    assert '"success": true' in tabs_call[0].text
    print("TEST 5 PASSED: Session status and tab list tools work.\n")

    print("=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
