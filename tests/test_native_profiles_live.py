"""Opt-in live tests use only disposable user data and a random CDP port.

Run: MCP_PROFILE_LIVE_TEST=1 .venv/bin/python -m unittest discover -s tests -p test_native_profiles_live.py
"""
import asyncio
import json
import os
import socket
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import patch

from browser_mcp.config import resolve_chrome_executable
from browser_mcp.core.session import BrowserSession
from browser_mcp.core.profiles import native_context


async def _stop_owned_chrome(process):
    """Reap a Chrome subprocess launched by this fixture only."""
    # Popen owns this exact child. Never signal a process group or shared browser.
    if process.poll() is None:
        process.terminate()
    await asyncio.to_thread(process.wait, timeout=10)


@asynccontextmanager
async def _chrome_fixture_directory(prefix):
    # No TemporaryDirectory finalizer: preserve data if a child cannot stop.
    root = Path(tempfile.mkdtemp(prefix=prefix))
    processes = []
    try:
        yield root, processes
    finally:
        for process in processes:
            await _stop_owned_chrome(process)
        # Only remove the data after every owned child has exited.
        shutil.rmtree(root)


@unittest.skipUnless(os.environ.get("MCP_PROFILE_LIVE_TEST") == "1", "opt-in disposable Chrome test")
class NativeProfileLiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_routing_reuse_tabs_reconnect_and_cookie_isolation(self):
        async with _chrome_fixture_directory("mcp-native-profiles-test-") as (root, processes):
            userdata = root / "userdata"
            userdata.mkdir()
            (userdata / "Local State").write_text(json.dumps({"profile": {"info_cache": {
                "Default": {"name": "Personal"}, "Profile 1": {"name": "Work"}}}}))
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            session = BrowserSession(cdp_port=port, profile_dir=userdata, state_file=root / "state.json")
            process = subprocess.Popen(session._build_launch_command(resolve_chrome_executable(), False, "Default"),
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            processes.append(process)
            try:
                for _ in range(60):
                    try:
                        reader, writer = await asyncio.open_connection("127.0.0.1", port)
                        writer.close()
                        await writer.wait_closed()
                        break
                    except OSError:
                        await asyncio.sleep(.1)
                self.assertTrue(await session.start())
                initial = await session.browser_profile("switch", "Personal")
                self.assertTrue(initial["success"], initial)
                personal = session.page
                await personal.goto("data:text/html,<title>Personal</title>original")
                personal_id = await native_context(personal)
                async def windows():
                    ids = set()
                    browser_cdp = await session.browser.new_browser_cdp_session()
                    try:
                        for page in session.context.pages:
                            cdp = await session.context.new_cdp_session(page)
                            target = (await cdp.send("Target.getTargetInfo"))["targetInfo"]["targetId"]
                            await cdp.detach()
                            ids.add((await browser_cdp.send("Browser.getWindowForTarget", {"targetId": target}))["windowId"])
                        return ids
                    finally:
                        await browser_cdp.detach()
                initial_windows = await windows()
                originals = {page: page.url for page in session.context.pages}
                result = await session.browser_profile("switch", "Work")
                self.assertTrue(result["success"], result)
                work = session.page
                self.assertEqual(len(await windows()), len(initial_windows) + 1)
                open_windows = await windows()
                for page, url in originals.items():
                    self.assertFalse(page.is_closed())
                    self.assertEqual(page.url, url)
                work_id = await native_context(work)
                self.assertNotEqual(personal_id, work_id)
                await work.goto("data:text/html,<title>Work</title>original")
                for directory, anchor in [("Default", personal), ("Profile 1", work)]:
                    cdp = await session.context.new_cdp_session(anchor)
                    await cdp.send("Network.setCookie", {"name": "profile", "value": directory,
                                   "url": "https://native-profile-test.invalid/", "secure": True})
                    await cdp.detach()
                for directory, anchor in [("Default", personal), ("Profile 1", work)]:
                    result = await session.browser_profile("switch", directory)
                    self.assertTrue(result["success"], result)
                    self.assertIs(session.page, anchor)
                    before = len(session.context.pages)
                    for _ in range(2):
                        self.assertTrue((await session.browser_profile("switch", directory))["success"])
                        self.assertIs(session.page, anchor)
                    self.assertEqual(len(session.context.pages), before)
                    self.assertEqual(await windows(), open_windows)
                    result = await session.new_tab("data:text/html,<title>new</title>new")
                    self.assertTrue(result["success"], result)
                    self.assertEqual(await native_context(session.page), await native_context(anchor))
                    self.assertEqual(len((await session.list_tabs())["tabs"]), result["tab_index"] + 1)
                    # Export selected profile while the OTHER profile owns OS focus.
                    await (work if directory == "Default" else personal).bring_to_front()
                    self.assertTrue(await session.auth_manager.save_storage_state(session.context, page=session.page))
                    state = json.loads(session.state_file.read_text())
                    cookies = [c for c in state["cookies"] if c["name"] == "profile"]
                    self.assertEqual([c["value"] for c in cookies], [directory])
                    await session.close_tab()
                    self.assertIs(session.page, anchor)
                self.assertEqual(personal.url, "data:text/html,<title>Personal</title>original")
                self.assertEqual(work.url, "data:text/html,<title>Work</title>original")
                await session.close()
                self.assertIsNone(process.poll(), "Disconnect must not close detached Chrome")
                self.assertTrue(await session.start())
                self.assertEqual(session.selected_profile, "Profile 1")
                self.assertEqual((await session.session_status())["open_tabs"], 1)
                listed = await session.browser_profile("list")
                self.assertTrue(all(p["is_open"] for p in listed["profiles"]))
                self.assertEqual(set(session._context_profiles.values()), {"Default", "Profile 1"})
            finally:
                await session.close()

    async def test_cold_switch_launches_only_requested_profile(self):
        async with _chrome_fixture_directory("mcp-native-profile-cold-") as (root, processes):
            (root / "Local State").write_text(json.dumps({"profile": {"info_cache": {
                "Default": {"name": "Personal"}, "Profile 1": {"name": "Work"}}}}))
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            session = BrowserSession(cdp_port=port, profile_dir=root, state_file=root / "state.json")
            def launch(command):
                processes.append(subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.DEVNULL, start_new_session=True))
            try:
                with patch("browser_mcp.core.session._launch_detached", side_effect=launch):
                    result = await session.browser_profile("switch", "Work")
                    self.assertTrue(result["success"], result)
                    self.assertEqual(len(processes), 1)
                    self.assertIn("--profile-directory=Profile 1", processes[0].args)
                    self.assertEqual(set(session._context_profiles.values()), {"Profile 1"})
                    self.assertEqual(session.selected_profile, "Profile 1")
            finally:
                await session.close()


if __name__ == "__main__":
    unittest.main()
