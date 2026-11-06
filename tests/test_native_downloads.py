"""Attachment must not override the shared browser's native download settings."""
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from playwright.async_api import BrowserType

from browser_mcp.core.session import BrowserSession


class NativeDownloadAttachmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.session = BrowserSession(cdp_port=12345, profile_dir=root / "profile",
                                      state_file=root / "state.json")
        self.context = SimpleNamespace(pages=[])
        self.browser = SimpleNamespace(contexts=[self.context], is_connected=Mock(return_value=True))
        self.connect = AsyncMock(return_value=self.browser)
        self.playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=self.connect))
        self.session.playwright = self.playwright

    async def test_initial_attachment_preserves_native_settings(self):
        with patch("browser_mcp.core.session._launch_detached") as launch:
            await self.session._connect()
        self.connect.assert_awaited_once_with(self.session.cdp_url, no_defaults=True)
        launch.assert_not_called()
        self.assertIs(self.session.context, self.context)
        self.assertTrue(self.session.is_cdp_connection)

    async def test_launch_retries_preserve_native_settings_on_every_attachment(self):
        self.connect.side_effect = [OSError("not running"), OSError("starting"), self.browser]
        with patch("browser_mcp.core.session._launch_detached") as launch, \
                patch("browser_mcp.core.session.resolve_chrome_executable", return_value="/test/chrome"), \
                patch("browser_mcp.core.session.asyncio.sleep", new_callable=AsyncMock):
            await self.session._connect()
        self.assertEqual(self.connect.await_args_list,
                         [call(self.session.cdp_url, no_defaults=True)] * 3)
        launch.assert_called_once()
        self.assertIn("--remote-debugging-port=12345", launch.call_args.args[0])
        self.assertIn(f"--user-data-dir={self.session.profile_dir}", launch.call_args.args[0])
        self.assertIs(self.session.context, self.context)

    async def test_reconnect_after_disconnect_preserves_native_settings(self):
        old_browser = SimpleNamespace(is_connected=Mock(return_value=False))
        self.session.browser = old_browser
        await self.session._connect()
        self.connect.assert_awaited_once_with(self.session.cdp_url, no_defaults=True)
        self.assertIs(self.session.browser, self.browser)

    async def test_connected_session_is_reused_without_reapplying_settings(self):
        self.session.browser = self.browser
        await self.session._connect()
        self.connect.assert_not_awaited()

    async def test_attachment_without_native_context_still_fails_closed(self):
        self.browser.contexts = []
        with self.assertRaisesRegex(RuntimeError, "no native browser context"):
            await self.session._connect()
        self.connect.assert_awaited_once_with(self.session.cdp_url, no_defaults=True)

    def test_installed_playwright_supports_native_attachment_option(self):
        self.assertIn("no_defaults", inspect.signature(BrowserType.connect_over_cdp).parameters)


if __name__ == "__main__":
    unittest.main()
