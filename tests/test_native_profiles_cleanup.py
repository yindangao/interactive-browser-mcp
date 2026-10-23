"""Cleanup regressions run without launching Chrome or touching shared endpoints."""
import errno
import os
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

from test_native_profiles_live import _stop_owned_chrome, _chrome_fixture_directory


class OwnedChromeCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_denial_does_not_prevent_exact_child_termination(self):
        process = Mock(spec=subprocess.Popen)
        process.pid = 12345
        process.poll.return_value = None
        events = []
        process.terminate.side_effect = lambda: events.append("terminate")
        process.wait.side_effect = lambda timeout: events.append("wait")
        with patch.object(os, "killpg", side_effect=PermissionError(errno.EPERM, "denied")) as group:
            await _stop_owned_chrome(process)
        group.assert_not_called()
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=10)
        process.kill.assert_not_called()
        self.assertEqual(events, ["terminate", "wait"])

    async def test_already_exited_child_is_reaped_without_signalling(self):
        process = Mock(spec=subprocess.Popen)
        process.poll.return_value = 0
        await _stop_owned_chrome(process)
        process.terminate.assert_not_called()
        process.wait.assert_called_once_with(timeout=10)
        process.kill.assert_not_called()

    async def test_directory_cleanup_follows_child_exit(self):
        process = Mock(spec=subprocess.Popen)
        process.poll.return_value = None
        async with _chrome_fixture_directory("mcp-native-cleanup-test-") as (root, processes):
            processes.append(process)
            process.wait.side_effect = lambda timeout: self.assertTrue(root.is_dir())
        process.wait.assert_called_once_with(timeout=10)
        self.assertFalse(root.exists())

    async def test_timeout_preserves_directory_for_running_child(self):
        process = Mock(spec=subprocess.Popen)
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired("fixture Chrome", 10)
        root = None
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                async with _chrome_fixture_directory("mcp-native-cleanup-test-") as (root, processes):
                    processes.append(process)
            self.assertTrue(root.is_dir())
            process.kill.assert_not_called()
        finally:
            if root is not None:
                shutil.rmtree(root)

    async def test_timeout_is_reported_without_forced_kill(self):
        process = Mock(spec=subprocess.Popen)
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired("fixture Chrome", 10)
        with self.assertRaises(subprocess.TimeoutExpired):
            await _stop_owned_chrome(process)
        process.terminate.assert_called_once_with()
        process.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
