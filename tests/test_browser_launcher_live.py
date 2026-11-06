"""Opt-in launcher coverage against an owned, headful Chrome profile picker.

Run: MCP_LAUNCHER_LIVE_TEST=1 .venv/bin/python -m unittest discover -s tests -p test_browser_launcher_live.py
No shared Chrome process, user-data directory, or fixed CDP port is used.
"""
import asyncio
import json
import os
import socket
import subprocess
import unittest
from unittest.mock import patch

from playwright.async_api import async_playwright

from browser_mcp.config import resolve_chrome_executable
from browser_mcp.core.session import BrowserSession
from test_native_profiles_live import _chrome_fixture_directory


@unittest.skipUnless(os.environ.get("MCP_LAUNCHER_LIVE_TEST") == "1",
                     "opt-in disposable Chrome launcher test")
class BrowserLauncherLiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_work_from_picker_and_reuse_selected_page(self):
        async with _chrome_fixture_directory("mcp-launcher-picker-test-") as (root, processes):
            userdata = root / "userdata"
            userdata.mkdir()
            (userdata / "Local State").write_text(json.dumps({"profile": {
                "show_picker_on_startup": True,
                "last_used": "Default",
                "info_cache": {
                    "Default": {"name": "Personal"},
                    "Profile 1": {"name": "Work"},
                },
            }}))
            for directory, name in (("Default", "Personal"), ("Profile 1", "Work")):
                profile = userdata / directory
                profile.mkdir()
                (profile / "Preferences").write_text(json.dumps({"profile": {
                    "name": name, "avatar_index": 0,
                }}))
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            session = BrowserSession(cdp_port=port, profile_dir=userdata,
                                     state_file=root / "state.json")

            def launch_owned(command):
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, start_new_session=True)
                processes.append(process)
                return process

            command = session._build_launch_command(resolve_chrome_executable(), False, None)
            self.assertFalse(any(arg.startswith("--profile-directory") for arg in command))
            chrome = launch_owned(command)
            # Keep every launch (including singleton-forwarding CLI children)
            # inside the existing owned-child fixture's cleanup boundary.
            with patch("browser_mcp.core.session._launch_detached", side_effect=launch_owned):
                try:
                    async with async_playwright() as playwright:
                        observer = None
                        deadline = asyncio.get_running_loop().time() + 20
                        while asyncio.get_running_loop().time() < deadline:
                            self.assertIsNone(chrome.poll(), "Owned Chrome exited before CDP connected")
                            try:
                                observer = await playwright.chromium.connect_over_cdp(
                                    session.cdp_url, no_defaults=True, timeout=1000)
                                break
                            except Exception:
                                await asyncio.sleep(.1)
                        self.assertIsNotNone(observer, "Owned Chrome did not expose CDP")
                        cdp = await observer.new_browser_cdp_session()
                        try:
                            targets = []
                            deadline = asyncio.get_running_loop().time() + 15
                            while asyncio.get_running_loop().time() < deadline:
                                targets = (await cdp.send("Target.getTargets"))["targetInfos"]
                                if any(target["type"] == "browser_ui"
                                       and target["url"].startswith("chrome://profile-picker")
                                       for target in targets):
                                    break
                                await asyncio.sleep(.1)
                            self.assertTrue(any(
                                target["type"] == "browser_ui"
                                and target["url"].startswith("chrome://profile-picker")
                                for target in targets), f"No actual profile picker target: {targets!r}")
                            self.assertFalse([t for t in targets if t["type"] == "page"],
                                             "Fixture must start at picker, not an already-open profile")

                            result = await session.browser_launcher(action="open", profile="Work")
                            self.assertTrue(result["success"], result)
                            self.assertEqual(session.selected_profile, "Profile 1")
                            selected = session.page
                            self.assertIsNotNone(selected)
                            self.assertFalse(selected.is_closed())
                            # Independently verify the actual native profile, not just the label.
                            await selected.goto("chrome://version/", wait_until="domcontentloaded")
                            actual_path = (await selected.locator("#profile_path").inner_text()).strip()
                            self.assertEqual(os.path.realpath(actual_path),
                                             os.path.realpath(userdata / "Profile 1"))
                            await selected.goto("data:text/html,<title>Work launcher</title>keep this tab")
                            original_url = selected.url

                            async def page_windows():
                                infos = (await cdp.send("Target.getTargets"))["targetInfos"]
                                return {
                                    target["targetId"]: (await cdp.send("Browser.getWindowForTarget", {
                                        "targetId": target["targetId"],
                                    }))["windowId"]
                                    for target in infos if target["type"] == "page"
                                }

                            original_pages = list(session.context.pages)
                            original_windows = await page_windows()
                            launch_count = len(processes)
                            for _ in range(2):
                                result = await session.browser_launcher(action="open", profile="Work")
                                self.assertTrue(result["success"], result)
                                self.assertIs(session.page, selected)
                                self.assertEqual(session.selected_profile, "Profile 1")
                                self.assertEqual(selected.url, original_url)
                                self.assertEqual(list(session.context.pages), original_pages)
                                self.assertEqual(await page_windows(), original_windows)
                                self.assertEqual(len(processes), launch_count,
                                                 "Repeated open must not launch Chrome again")
                        finally:
                            await cdp.detach()
                finally:
                    await session.close()


if __name__ == "__main__":
    unittest.main()
