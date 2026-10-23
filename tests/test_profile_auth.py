"""Profile-scoped authentication persistence; never uses a live browser profile."""

import asyncio
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.async_api import BrowserContext, Page
from browser_mcp.core.auth import AuthManager


class ProfileAuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = AuthManager(self.root / "states" / "work.json")
        self.context = Mock(spec=BrowserContext)
        self.context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
        self.context.new_cdp_session = AsyncMock()

    def page_fixture(self, profile="work", url="https://app.example/path"):
        page = Mock(spec=Page)
        page.url = url
        page.evaluate = AsyncMock(return_value={
            "origin": "https://app.example",
            "localStorage": [{"name": "fixture-profile", "value": profile}],
        })
        cdp = Mock()
        cdp.send = AsyncMock(return_value={"cookies": [{
            "name": "fixture-profile", "value": profile,
            "domain": "app.example", "path": "/", "expires": -1,
            "httpOnly": True, "secure": True,
            "session": True, "size": 1, "priority": "Medium",
        }]})
        cdp.detach = AsyncMock()
        return page, cdp

    def load(self, manager=None):
        return json.loads((manager or self.manager).state_file.read_text())

    async def test_page_scoped_export_never_reads_flattened_context(self):
        page, cdp = self.page_fixture()
        self.context.new_cdp_session.return_value = cdp
        self.assertTrue(await self.manager.save_storage_state(self.context, page=page))
        self.context.new_cdp_session.assert_awaited_once_with(page)
        cdp.send.assert_awaited_once_with("Network.getAllCookies")
        cdp.detach.assert_awaited_once_with()
        self.context.storage_state.assert_not_awaited()
        state = self.load()
        self.assertEqual(state["origins"], [page.evaluate.return_value])
        self.assertEqual(state["cookies"][0]["sameSite"], "Lax")
        self.assertEqual(set(state["cookies"][0]), {
            "name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite",
        })

    async def test_two_profiles_write_only_their_own_page_state(self):
        other = AuthManager(self.root / "states" / "personal.json")
        work_page, work_cdp = self.page_fixture("work")
        personal_page, personal_cdp = self.page_fixture("personal")
        self.context.new_cdp_session.side_effect = [work_cdp, personal_cdp]
        self.assertTrue(await self.manager.save_storage_state(self.context, page=work_page))
        work_bytes = self.manager.state_file.read_bytes()
        self.assertTrue(await other.save_storage_state(self.context, page=personal_page))
        self.assertEqual(self.manager.state_file.read_bytes(), work_bytes)
        for manager, profile in [(self.manager, "work"), (other, "personal")]:
            state = self.load(manager)
            self.assertEqual([c["value"] for c in state["cookies"]], [profile])
            self.assertEqual(state["origins"][0]["localStorage"][0]["value"], profile)
        self.context.storage_state.assert_not_awaited()

    async def test_context_only_remains_supported_with_private_atomic_file(self):
        expected = {"cookies": [], "origins": []}
        self.context.storage_state.return_value = expected
        self.assertTrue(await self.manager.save_storage_state(self.context))
        self.context.storage_state.assert_awaited_once_with()
        self.context.new_cdp_session.assert_not_awaited()
        self.assertEqual(self.load(), expected)
        self.assertEqual(stat.S_IMODE(self.manager.state_file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.manager.state_file.parent.stat().st_mode), 0o700)

    async def test_new_nested_directories_are_private_without_chmod_existing_parent(self):
        parent = self.root / "existing"
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
        manager = AuthManager(parent / "new" / "nested" / "state.json")
        self.assertTrue(await manager.save_storage_state(self.context))
        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o755)
        for directory in [parent / "new", parent / "new" / "nested"]:
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(manager.state_file.stat().st_mode), 0o600)

    async def test_non_web_pages_skip_local_storage_but_remain_page_scoped(self):
        for url in ["about:blank", "chrome://settings", "file:///tmp/fixture.html", ""]:
            with self.subTest(url=url):
                page, cdp = self.page_fixture(url=url)
                self.context.new_cdp_session.return_value = cdp
                self.assertTrue(await self.manager.save_storage_state(self.context, page=page))
                page.evaluate.assert_not_awaited()
                cdp.detach.assert_awaited_once_with()
                self.assertEqual(self.load()["origins"], [])
        self.context.storage_state.assert_not_awaited()

    async def test_navigation_to_non_web_during_evaluation_omits_origin(self):
        page, cdp = self.page_fixture()
        page.evaluate.return_value = None
        self.context.new_cdp_session.return_value = cdp
        self.assertTrue(await self.manager.save_storage_state(self.context, page=page))
        self.assertEqual(self.load()["origins"], [])

    async def test_capture_failure_preserves_previous_file_and_detaches(self):
        self.manager.state_file.parent.mkdir()
        self.manager.state_file.write_text('{"previous": true}')
        before = self.manager.state_file.read_bytes()
        for stage in ["attach", "cookies", "local_storage", "detach"]:
            with self.subTest(stage=stage):
                page, cdp = self.page_fixture()
                self.context.new_cdp_session.side_effect = None
                self.context.new_cdp_session.return_value = cdp
                failing = {"attach": self.context.new_cdp_session, "cookies": cdp.send,
                           "local_storage": page.evaluate, "detach": cdp.detach}[stage]
                failing.side_effect = RuntimeError("synthetic failure")
                self.assertFalse(await self.manager.save_storage_state(self.context, page=page))
                self.assertEqual(self.manager.state_file.read_bytes(), before)
                if stage != "attach":
                    cdp.detach.assert_awaited_once_with()
        self.context.storage_state.assert_not_awaited()

    async def test_cancelled_capture_detaches_and_preserves_previous_file(self):
        self.manager.state_file.parent.mkdir()
        self.manager.state_file.write_text('{"previous": true}')
        before = self.manager.state_file.read_bytes()
        page, cdp = self.page_fixture()
        self.context.new_cdp_session.return_value = cdp
        cdp.send.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.manager.save_storage_state(self.context, page=page)
        cdp.detach.assert_awaited_once_with()
        self.assertEqual(self.manager.state_file.read_bytes(), before)

    async def test_failed_atomic_replace_preserves_previous_file_and_removes_temp(self):
        self.manager.state_file.parent.mkdir()
        self.manager.state_file.write_text('{"previous": true}')
        before = self.manager.state_file.read_bytes()
        with patch("browser_mcp.core.auth.os.replace", side_effect=OSError("synthetic failure")):
            self.assertFalse(await self.manager.save_storage_state(self.context))
        self.assertEqual(self.manager.state_file.read_bytes(), before)
        self.assertEqual(list(self.manager.state_file.parent.iterdir()), [self.manager.state_file])

    async def test_serialization_failure_preserves_previous_file_and_removes_temp(self):
        self.manager.state_file.parent.mkdir()
        self.manager.state_file.write_text('{"previous": true}')
        before = self.manager.state_file.read_bytes()
        self.context.storage_state.return_value = {"invalid": object()}
        self.assertFalse(await self.manager.save_storage_state(self.context))
        self.assertEqual(self.manager.state_file.read_bytes(), before)
        self.assertEqual(list(self.manager.state_file.parent.iterdir()), [self.manager.state_file])

    async def test_atomic_replace_uses_private_complete_file_and_restricts_old_mode(self):
        self.manager.state_file.parent.mkdir()
        self.manager.state_file.write_text('{"previous": true}')
        self.manager.state_file.chmod(0o644)
        replace = os.replace

        def inspect_replace(source, destination):
            self.assertEqual(json.loads(destination.read_text()), {"previous": True})
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o600)
            self.assertEqual(json.loads(source.read_text()), {"cookies": [], "origins": []})
            replace(source, destination)

        with patch("browser_mcp.core.auth.os.replace", side_effect=inspect_replace):
            self.assertTrue(await self.manager.save_storage_state(self.context))
        self.assertEqual(stat.S_IMODE(self.manager.state_file.stat().st_mode), 0o600)
        self.assertEqual(list(self.manager.state_file.parent.iterdir()), [self.manager.state_file])

    async def test_legacy_capture_failure_preserves_previous_file(self):
        self.manager.state_file.parent.mkdir()
        self.manager.state_file.write_text('{"previous": true}')
        before = self.manager.state_file.read_bytes()
        self.context.storage_state.side_effect = RuntimeError("synthetic failure")
        self.assertFalse(await self.manager.save_storage_state(self.context))
        self.assertEqual(self.manager.state_file.read_bytes(), before)
        self.context.new_cdp_session.assert_not_awaited()

    async def test_errors_do_not_log_capture_contents(self):
        page, cdp = self.page_fixture()
        self.context.new_cdp_session.return_value = cdp
        cdp.send.side_effect = RuntimeError("synthetic-sensitive-marker")
        with self.assertLogs("browser_mcp.core.auth", level="ERROR") as logs:
            self.assertFalse(await self.manager.save_storage_state(self.context, page=page))
        self.assertNotIn("synthetic-sensitive-marker", " ".join(logs.output))

    async def test_monitor_auth_reports_snapshot_failure(self):
        page, _ = self.page_fixture()
        self.manager.save_storage_state = AsyncMock(return_value=False)
        with patch("browser_mcp.core.auth.asyncio.sleep", new_callable=AsyncMock):
            self.assertFalse(await self.manager.monitor_auth(page, self.context, timeout_seconds=1))

    async def test_monitor_auth_passes_selected_page(self):
        page, _ = self.page_fixture()
        self.manager.save_storage_state = AsyncMock(return_value=True)
        with patch("browser_mcp.core.auth.asyncio.sleep", new_callable=AsyncMock):
            self.assertTrue(await self.manager.monitor_auth(page, self.context, timeout_seconds=1))
        self.manager.save_storage_state.assert_awaited_once_with(self.context, page=page)


if __name__ == "__main__":
    unittest.main()
