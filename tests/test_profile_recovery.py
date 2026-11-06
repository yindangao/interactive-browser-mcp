"""Recovery must preserve profile isolation even when operations are cancelled."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from browser_mcp.core.profiles import available_profiles, identify_profile, profile_popup
from browser_mcp.core.session import BrowserSession


class PopupAnchor:
    def __init__(self, page, cancel_creation=False):
        self.page = page
        self.cancel_creation = cancel_creation
        self.listeners = []
        self.bring_to_front = AsyncMock()

    def on(self, event, callback):
        self.listeners.append(callback)

    def remove_listener(self, event, callback):
        self.listeners.remove(callback)

    def expect_popup(self, **kwargs):
        anchor = self
        class Expectation:
            async def __aenter__(self):
                future = asyncio.get_running_loop().create_future()
                future.set_result(anchor.page)
                self.value = future
                return self

            async def __aexit__(self, *args):
                return False
        return Expectation()

    async def evaluate(self, script):
        for callback in self.listeners:
            callback(self.page)
        if self.cancel_creation:
            raise asyncio.CancelledError()


class ProfileRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'Local State').write_text(json.dumps({'profile': {'info_cache': {
            'Default': {'name': 'Personal'}, 'Profile 1': {'name': 'Work'}}}}))
        self.session = BrowserSession(profile_dir=self.root, state_file=self.root / 'state.json')

    async def test_start_rejects_unidentified_focused_profile(self):
        known = SimpleNamespace(is_closed=lambda: False, evaluate=AsyncMock(return_value=False))
        focused = SimpleNamespace(is_closed=lambda: False, evaluate=AsyncMock(return_value=True))
        self.session.context = SimpleNamespace(pages=[known, focused])
        self.session._connect = AsyncMock()
        self.session._context_profiles = {'known': 'Default'}
        async def context(page):
            return 'known' if page is known else 'unknown'
        async def identify(page, root):
            raise RuntimeError('probe blocked')
        with patch('browser_mcp.core.session.native_context', side_effect=context), \
                patch('browser_mcp.core.session.identify_profile', side_effect=identify):
            self.assertFalse(await self.session.start())
        self.assertIsNone(self.session.selected_profile)
        self.assertIsNone(self.session.page)

    async def test_switch_cancellation_restores_exact_state(self):
        for selected in (False, True):
            for stage in ('connect', 'activate', 'count'):
                with self.subTest(selected=selected, stage=stage):
                    session = BrowserSession(profile_dir=self.root, state_file=self.root / 'state.json')
                    if selected:
                        session._select('Default', object())
                    old = (session.selected_profile, session.page, session.state_file, session.auth_manager)
                    old_pages = session._last_pages.copy()
                    session._connect = AsyncMock()
                    async def activate(directory):
                        session._select(directory, SimpleNamespace(url='about:blank'))
                        if stage == 'activate':
                            raise asyncio.CancelledError()
                    session._activate_profile = activate
                    session._profile_pages = AsyncMock(side_effect=asyncio.CancelledError())
                    if stage == 'connect':
                        session._connect.side_effect = asyncio.CancelledError()
                    with self.assertRaises(asyncio.CancelledError):
                        await session.browser_launcher('open', 'Work')
                    self.assertEqual((session.selected_profile, session.page, session.state_file), old[:3])
                    self.assertIs(session.auth_manager, old[3])
                    self.assertEqual(session._last_pages, old_pages)

    async def test_failed_switch_preserves_auth_manager_identity(self):
        self.session._select('Default', object())
        auth = self.session.auth_manager
        self.session._connect = AsyncMock(side_effect=RuntimeError('offline'))
        self.assertFalse((await self.session.browser_launcher('open', 'Work'))['success'])
        self.assertIs(self.session.auth_manager, auth)

    def test_malformed_local_state_shapes_are_safe(self):
        for value in (None, [], 3, {'profile': None}, {'profile': []},
                      {'profile': {'info_cache': None}}, {'profile': {'info_cache': []}},
                      {'profile': {'info_cache': 'bad'}}, {'profile': {'info_cache': 3}}):
            with self.subTest(value=value):
                (self.root / 'Local State').write_text(json.dumps(value))
                self.assertEqual(available_profiles(self.root), {})

    async def test_popup_cancellation_during_context_check_closes_owned_page(self):
        for check in (1, 2):
            with self.subTest(check=check):
                page = SimpleNamespace(close=AsyncMock())
                anchor = PopupAnchor(page)
                effects = [asyncio.CancelledError()] if check == 1 else ['context', asyncio.CancelledError()]
                with patch('browser_mcp.core.profiles.native_context', side_effect=effects):
                    with self.assertRaises(asyncio.CancelledError):
                        await profile_popup(anchor)
                page.close.assert_awaited_once()
                self.assertEqual(anchor.listeners, [])

    async def test_popup_creation_cancellation_closes_known_owned_page(self):
        page = SimpleNamespace(close=AsyncMock())
        anchor = PopupAnchor(page, cancel_creation=True)
        with self.assertRaises(asyncio.CancelledError):
            await profile_popup(anchor)
        page.close.assert_awaited_once()
        self.assertEqual(anchor.listeners, [])

    async def test_cleanup_failure_does_not_replace_cancellation(self):
        page = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError('close failed')))
        with patch('browser_mcp.core.profiles.native_context', side_effect=asyncio.CancelledError()):
            with self.assertRaises(asyncio.CancelledError):
                await profile_popup(PopupAnchor(page))
        page.close.assert_awaited_once()

    async def test_repeated_cancellation_does_not_interrupt_owned_cleanup(self):
        closing = asyncio.Event()
        release = asyncio.Event()
        closed = asyncio.Event()
        async def close():
            closing.set()
            await release.wait()
            closed.set()
        page = SimpleNamespace(close=AsyncMock(side_effect=close))
        with patch('browser_mcp.core.profiles.native_context', side_effect=asyncio.CancelledError()):
            task = asyncio.create_task(profile_popup(PopupAnchor(page)))
            await asyncio.wait_for(closing.wait(), .5)
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(closed.is_set())
        page.close.assert_awaited_once()

    async def test_popup_verification_failure_keeps_original_error_if_close_fails(self):
        page = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError('close failed')))
        with patch('browser_mcp.core.profiles.native_context', side_effect=['popup', 'anchor']):
            with self.assertRaisesRegex(RuntimeError, 'different native profile'):
                await profile_popup(PopupAnchor(page))
        page.close.assert_awaited_once()

    async def test_cleanup_is_bounded(self):
        closed = asyncio.Event()
        async def stuck_close():
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        page = SimpleNamespace(close=AsyncMock(side_effect=stuck_close))
        with patch('browser_mcp.core.profiles.native_context', side_effect=asyncio.CancelledError()):
            task = asyncio.create_task(profile_popup(PopupAnchor(page)))
            done, _ = await asyncio.wait({task}, timeout=2)
            if not done:
                task.cancel()
            self.assertTrue(done, 'cleanup exceeded its time bound')
            with self.assertRaises(asyncio.CancelledError):
                await task
        await asyncio.wait_for(closed.wait(), .5)

    async def test_probe_cancellation_closes_probe_and_restores_focus(self):
        page = SimpleNamespace(close=AsyncMock(), goto=AsyncMock(side_effect=asyncio.CancelledError()))
        anchor = PopupAnchor(page)
        with patch('browser_mcp.core.profiles.profile_popup', return_value=page):
            with self.assertRaises(asyncio.CancelledError):
                await identify_profile(anchor, self.root)
        page.close.assert_awaited_once()
        anchor.bring_to_front.assert_awaited_once()
