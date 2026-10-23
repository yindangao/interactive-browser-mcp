"""Profile selection cannot change while another browser tool is in flight."""
import asyncio
import json
import unittest
from unittest.mock import patch

from browser_mcp.server import handle_call_tool


class ToolSerializationTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_switch_waits_for_inflight_tool(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        history = []

        async def dispatch(session, name, arguments):
            history.append((name, "start"))
            if name == "browse_page":
                entered.set()
                await release.wait()
            history.append((name, "end"))
            return {"success": True}

        with patch("browser_mcp.server.dispatch_tool", dispatch):
            reader = asyncio.create_task(handle_call_tool("browse_page", {}))
            await entered.wait()
            switch = asyncio.create_task(handle_call_tool("browser_profile", {"action": "switch", "profile": "Work"}))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            try:
                self.assertEqual(history, [("browse_page", "start")])
            finally:
                release.set()
                await asyncio.gather(reader, switch)
            self.assertEqual(history, [("browse_page", "start"), ("browse_page", "end"), ("browser_profile", "start"), ("browser_profile", "end")])

    async def test_failed_tool_releases_lock(self):
        async def dispatch(session, name, arguments):
            if name == "browse_page":
                raise ValueError("test failure")
            return {"success": True}
        with patch("browser_mcp.server.dispatch_tool", dispatch):
            failed = await handle_call_tool("browse_page", {})
            self.assertFalse(json.loads(failed[0].text)["success"])
            result = await asyncio.wait_for(handle_call_tool("browser_profile", {"action": "list"}), 1)
            self.assertTrue(json.loads(result[0].text)["success"])
