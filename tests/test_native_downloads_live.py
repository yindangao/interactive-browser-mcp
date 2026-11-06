"""Opt-in native downloads; never attach to a shared Chrome or real profile.

Run: MCP_DOWNLOAD_LIVE_TEST=1 .venv/bin/python -m unittest discover -s tests -p test_native_downloads_live.py -v
"""
import asyncio
import json
import os
import socket
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from browser_mcp.config import resolve_chrome_executable
from browser_mcp.core.session import BrowserSession
from test_native_profiles_live import _chrome_fixture_directory


_FILES = {
    "native-before.csv": b"stage,value\r\nbefore,17\r\n",
    "native-after.csv": b"stage,value\r\nafter,23\r\n",
}


class _DownloadHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        filename = self.path.lstrip("/")
        if self.path == "/":
            body = ("<!doctype html><title>Disposable downloads</title>" + "".join(
                f'<a href="/{name}">{name}</a>' for name in _FILES
            )).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif filename in _FILES:
            body = _FILES[filename]
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        else:
            self.send_error(404)
            return
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@unittest.skipUnless(os.environ.get("MCP_DOWNLOAD_LIVE_TEST") == "1",
                     "opt-in disposable Chrome download test")
class NativeDownloadLiveTests(unittest.IsolatedAsyncioTestCase):
    async def _wait_for_file(self, downloads, name):
        path = downloads / name
        deadline = asyncio.get_running_loop().time() + 20
        while asyncio.get_running_loop().time() < deadline:
            if path.is_file() and path.read_bytes() == _FILES[name]:
                return
            await asyncio.sleep(.1)
        self.fail(f"Native download {name!r} missing or incorrect; "
                  f"download directory contains: {sorted(p.name for p in downloads.iterdir())}")

    async def test_native_downloads_survive_detach_and_reconnect(self):
        executable = resolve_chrome_executable()
        self.assertIsNotNone(executable, "Opt-in test requires Chrome/Chromium")
        async with _chrome_fixture_directory("mcp-native-downloads-test-") as (root, processes):
            downloads = root / "downloads"
            downloads.mkdir()
            userdata = root / "userdata"
            profile = userdata / "Default"
            profile.mkdir(parents=True)
            (profile / "Preferences").write_text(json.dumps({"download": {
                "default_directory": str(downloads),
                "prompt_for_download": False,
                "directory_upgrade": True,
            }}))
            # Never use the shared service, even if an ephemeral range includes it.
            port = 9222
            while port == 9222:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
            session = BrowserSession(cdp_port=port, profile_dir=userdata,
                                     state_file=root / "state.json")
            server = ThreadingHTTPServer(("127.0.0.1", 0), _DownloadHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                command = session._build_launch_command(executable, True, "Default")
                process = subprocess.Popen(command + ["about:blank"], stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, start_new_session=True)
                processes.append(process)
                for _ in range(150):
                    self.assertIsNone(process.poll(), "Disposable Chrome exited during startup")
                    try:
                        _, writer = await asyncio.open_connection("127.0.0.1", port)
                        writer.close()
                        await writer.wait_closed()
                        break
                    except OSError:
                        await asyncio.sleep(.1)
                else:
                    self.fail("Disposable Chrome CDP port did not become ready")

                # _connect avoids unrelated native-profile discovery/probe bugs.
                # Reject its fallback launcher: only our registered child may launch.
                with patch("browser_mcp.core.session._launch_detached",
                           side_effect=AssertionError("Unexpected Chrome fallback launch")):
                    await asyncio.wait_for(session._connect(), timeout=20)
                    page = session.context.pages[0]
                    url = f"http://127.0.0.1:{server.server_port}/"
                    await page.goto(url, wait_until="domcontentloaded")
                    await page.get_by_role("link", name="native-before.csv", exact=True).click()
                    # No expect_download/save_as: assert native disk names and bytes.
                    await self._wait_for_file(downloads, "native-before.csv")
                    await session.close()
                    self.assertIsNone(process.poll(), "close() must detach, not stop Chrome")
                    self.assertEqual((downloads / "native-before.csv").read_bytes(),
                                     _FILES["native-before.csv"])

                    await asyncio.wait_for(session._connect(), timeout=20)
                    self.assertIsNone(process.poll(), "Reconnect must reuse the owned Chrome")
                    page = next(p for p in session.context.pages if p.url == url)
                    self.assertEqual((downloads / "native-before.csv").read_bytes(),
                                     _FILES["native-before.csv"])
                    await page.get_by_role("link", name="native-after.csv", exact=True).click()
                    await self._wait_for_file(downloads, "native-after.csv")
                    await session.close()
                    self.assertIsNone(process.poll(), "Final close must still only detach")
                    self.assertEqual(sorted(p.name for p in downloads.iterdir()), sorted(_FILES))
                    for name, body in _FILES.items():
                        self.assertEqual((downloads / name).read_bytes(), body)
            finally:
                await session.close()
                await asyncio.to_thread(server.shutdown)
                server.server_close()
                await asyncio.to_thread(thread.join, 5)


if __name__ == "__main__":
    unittest.main()
