"""Verification test suite for safety guards against internal page hangs and deadlocks."""

import asyncio
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from browser_mcp.core.utils import is_internal_url, safe_get_title, safe_bring_to_front
from browser_mcp.core.session import BrowserSession
from browser_mcp.dom.reader import DOMReader
from browser_mcp.dom.actions import DOMActions
from browser_mcp.server import handle_call_tool, session_instance


async def run_safety_tests():
    print("=" * 60)
    print("TEST 1: Unit testing is_internal_url")
    print("=" * 60)
    assert is_internal_url("") is True
    assert is_internal_url("   ") is True
    assert is_internal_url(None) is True
    assert is_internal_url("about:blank") is True
    assert is_internal_url("about:version") is True
    assert is_internal_url("chrome://new-tab-page/") is True
    assert is_internal_url("chrome://settings/") is True
    assert is_internal_url("chrome-extension://oedggboaecbkcpnmkmdglidmfblggplg/offscreen.html") is True
    assert is_internal_url("devtools://devtools/bundled/inspector.html") is True
    assert is_internal_url("edge://settings") is True
    assert is_internal_url("https://jira.walmart.com") is False
    assert is_internal_url("http://127.0.0.1:8000") is False
    print("TEST 1 PASSED: is_internal_url correctly identifies internal and external schemes.\n")

    print("=" * 60)
    print("TEST 2: Connecting to live Chrome instance (CDP port 9222)")
    print("=" * 60)
    session = BrowserSession()
    connected = await session.start()
    assert connected, "Failed to connect to browser"
    print("Connected to browser successfully.\n")

    print("=" * 60)
    print("TEST 3: Listing tabs with safe_get_title")
    print("=" * 60)
    tab_list_res = await session.list_tabs()
    assert tab_list_res["success"] is True
    print(f"Discovered {tab_list_res['total_tabs']} tabs:")
    for t in tab_list_res["tabs"]:
        print(f"  [{t['index']}] {t['title']} ({t['url']})")
    print("TEST 3 PASSED: Tab list completed instantly with no deadlocks.\n")

    print("=" * 60)
    print("TEST 4: Creating a blank tab and testing safety guards")
    print("=" * 60)
    new_tab_res = await session.new_tab("about:blank")
    assert new_tab_res["success"] is True
    blank_idx = new_tab_res["tab_index"]
    print(f"Created blank tab at index {blank_idx}: {new_tab_res}")

    # Switch to the blank tab
    switch_res = await session.switch_tab(blank_idx)
    assert switch_res["success"] is True
    print(f"Switched to blank tab without hanging: {switch_res}")

    # DOMReader.browse on blank tab
    browse_res = await DOMReader.browse(session.page)
    assert browse_res["success"] is True
    assert "Browser internal page" in browse_res["content"]
    print(f"DOMReader returned safely on internal page: {browse_res['content']}")

    # DOMActions.evaluate_js on blank tab
    eval_res = await DOMActions.evaluate_js(session.page, "1 + 1")
    assert eval_res["success"] is False
    assert "Cannot evaluate JavaScript on internal browser page" in eval_res["error"]
    print(f"DOMActions.evaluate_js rejected safely: {eval_res['error']}")

    # DOMActions.click on blank tab
    click_res = await DOMActions.click(session.page, "#nonexistent")
    assert click_res["success"] is False
    assert "Cannot click element on internal browser page" in click_res["error"]
    print(f"DOMActions.click rejected safely: {click_res['error']}")

    # DOMActions.fill on blank tab
    fill_res = await DOMActions.fill(session.page, "input", "test")
    assert fill_res["success"] is False
    assert "Cannot fill input on internal browser page" in fill_res["error"]
    print(f"DOMActions.fill rejected safely: {fill_res['error']}")

    # Clean up by closing the blank tab
    close_res = await session.close_tab(blank_idx)
    assert close_res["success"] is True
    print(f"Closed blank tab cleanly: {close_res}")
    print("TEST 4 PASSED: All safety guards on internal tab verified.\n")

    print("=" * 60)
    print("ALL SAFETY TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_safety_tests())
