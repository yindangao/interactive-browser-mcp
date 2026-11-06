"""Native profile selection and isolation; no user's browser is touched."""
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from browser_mcp.core.session import BrowserSession


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "Local State").write_text(json.dumps({"profile": {"info_cache": {
            "Default": {"name": "Personal"}, "Profile 1": {"name": "Work"}}}}))
        self.session = BrowserSession(profile_dir=self.root, state_file=self.root / "state.json")

    async def test_list_does_not_start_browser(self):
        self.session.start = AsyncMock()
        self.session._connect = AsyncMock()
        result = await self.session.browser_launcher("list_profiles")
        self.assertTrue(result["success"])
        self.assertEqual([p["directory"] for p in result["profiles"]], ["Default", "Profile 1"])
        self.assertTrue(all(p["is_open"] is None for p in result["profiles"]))
        self.assertFalse(result["connected"])
        self.session.start.assert_not_awaited()
        self.session._connect.assert_not_awaited()

    async def test_invalid_selection_does_not_change_selected_profile(self):
        self.session._connect = AsyncMock()
        for action, profile in [(None, None), ("bad", None), ("list", None), ("switch", "Work"), ("open", None),
                                ("open", ""), ("open", "Unknown")]:
            result = await self.session.browser_launcher(action, profile)
            self.assertFalse(result["success"])
            self.assertIsNone(self.session.selected_profile)
        self.session._connect.assert_not_awaited()

    async def test_switch_launches_requested_profile_and_rolls_back_on_failure(self):
        seen = []
        async def connect():
            seen.append(self.session.selected_profile)
        self.session._connect = connect
        self.session._activate_profile = AsyncMock(side_effect=RuntimeError("blocked"))
        result = await self.session.browser_launcher("open", "Work")
        self.assertFalse(result["success"])
        self.assertEqual(seen, ["Profile 1"])
        self.assertIsNone(self.session.selected_profile)
        self.session._select("Default", "original page")
        state_file = self.session.state_file
        result = await self.session.browser_launcher("open", "Work")
        self.assertFalse(result["success"])
        self.assertEqual(self.session.selected_profile, "Default")
        self.assertEqual(self.session.page, "original page")
        self.assertEqual(self.session.state_file, state_file)

    async def test_open_reuses_last_selected_tab_without_launching(self):
        first = SimpleNamespace(url="https://work/first")
        last = SimpleNamespace(url="https://work/last")
        self.session._select("Profile 1", first)
        # Remembered tab wins over the page order returned by Chrome.
        self.session._profile_pages = AsyncMock(return_value=[first, last])
        self.session._connect = AsyncMock()
        self.session._open_profile = AsyncMock()
        with patch("browser_mcp.core.session.safe_bring_to_front", new_callable=AsyncMock):
            for _ in range(2):
                result = await self.session.browser_launcher("open", "Work")
                self.assertTrue(result["success"], result)
                self.assertEqual(result["open_tabs"], 2)
                self.assertIs(self.session.page, first)
        self.session._open_profile.assert_not_awaited()

    async def test_profile_state_files_are_distinct(self):
        self.session._select("Default", None)
        personal = self.session.state_file
        self.session._select("Profile 1", None)
        self.assertNotEqual(personal, self.session.state_file)
        self.assertEqual(self.session.auth_manager.state_file, self.session.state_file)

    async def test_resolution(self):
        self.assertEqual(self.session._resolve_profile_directory("work"), "Profile 1")
        self.assertEqual(self.session._resolve_profile_directory("Default"), "Default")
        with self.assertRaisesRegex(ValueError, "Available profiles"):
            self.session._resolve_profile_directory("missing")
        (self.root / "Local State").write_text(json.dumps({"profile": {"info_cache": {
            "Default": {"name": "Work"}, "Profile 1": {"name": "Work"}}}}))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.session._resolve_profile_directory("work")

    async def test_authenticate_has_no_profile_argument(self):
        self.assertNotIn("profile", inspect.signature(self.session.authenticate).parameters)
        self.assertNotIn("profile", inspect.signature(self.session.start).parameters)

    async def test_tabs_are_filtered_by_native_profile(self):
        a = SimpleNamespace(url="https://personal", is_closed=lambda: False, title=AsyncMock(return_value="Personal"))
        b = SimpleNamespace(url="https://work", is_closed=lambda: False, title=AsyncMock(return_value="Work"))
        self.session.selected_profile = "Profile 1"
        self.session.page = b
        self.session.context = SimpleNamespace(pages=[a, b])
        self.session.ensure_active = AsyncMock(return_value=True)
        self.session._profile_pages = AsyncMock(return_value=[b])
        result = await self.session.list_tabs()
        self.assertEqual([p["url"] for p in result["tabs"]], ["https://work"])
        self.assertFalse((await self.session.switch_tab(1))["success"])
        self.assertFalse((await self.session.close_tab(1))["success"])

    async def test_close_detaches_without_browser_close_or_context_export(self):
        browser = SimpleNamespace(close=AsyncMock())
        context = SimpleNamespace(storage_state=AsyncMock(), close=AsyncMock())
        self.session.browser = browser
        self.session.context = context
        self.session.is_cdp_connection = True
        self.session.playwright = SimpleNamespace(stop=AsyncMock())
        await self.session.close()
        browser.close.assert_not_awaited()
        context.close.assert_not_awaited()
        context.storage_state.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
