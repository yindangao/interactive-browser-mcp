"""Detached Chrome lifecycle and native-profile-scoped tab routing."""
import asyncio
import logging
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from browser_mcp.config import (
    CDP_PORT, CHROME_PROFILE_DIR, SESSION_STATE_FILE,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS, DEFAULT_AUTH_TIMEOUT_S, resolve_chrome_executable,
)
from browser_mcp.core.auth import AuthManager
from browser_mcp.core.profiles import (
    available_profiles, resolve_profile, native_context, identify_profile, profile_popup,
)
from browser_mcp.core.utils import safe_get_title, safe_bring_to_front

logger = logging.getLogger(__name__)


def _launch_detached(command):
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    # Reap singleton-forwarding launchers without waiting for the detached daemon.
    threading.Thread(target=process.wait, daemon=True).start()


class BrowserSession:
    """Playwright's CDP context flattens Chrome profiles; never route by that context alone."""

    def __init__(self, cdp_port: int = CDP_PORT, profile_dir: Optional[Path] = None,
                 state_file: Optional[Path] = None):
        self.cdp_port = cdp_port
        self.cdp_url = f"http://127.0.0.1:{cdp_port}"
        self.profile_dir = Path(profile_dir or CHROME_PROFILE_DIR)
        self._base_state_file = Path(state_file or SESSION_STATE_FILE)
        self.state_file = self._base_state_file
        self.auth_manager = AuthManager(state_file=self.state_file)
        self.playwright = self.browser = self.context = self.page = None
        self.is_cdp_connection = False
        self.selected_profile = None
        self._context_profiles = {}
        self._last_pages = {}

    def _resolve_profile_directory(self, profile):
        return resolve_profile(self.profile_dir, profile)

    def _build_launch_command(self, executable_path, headless, profile_directory):
        command = [executable_path, f"--remote-debugging-port={self.cdp_port}",
                   f"--user-data-dir={self.profile_dir}",
                   "--disable-blink-features=AutomationControlled", "--no-first-run",
                   "--no-default-browser-check"]
        if profile_directory:
            command.append(f"--profile-directory={profile_directory}")
        if headless:
            command.append("--headless=new")
        return command

    def _select(self, directory, page):
        self.selected_profile, self.page = directory, page
        self._last_pages[directory] = page
        base = self._base_state_file
        self.state_file = base.with_name(f"{base.stem}.{directory}{base.suffix}")
        self.auth_manager = AuthManager(state_file=self.state_file)

    async def _connect(self, headless=False):
        if self.browser and self.browser.is_connected():
            return
        self._context_profiles.clear()
        if not self.playwright:
            self.playwright = await async_playwright().start()
        # This is the user's browser: preserve native downloads, focus and media
        # settings instead of redirecting downloads into Playwright's temp files.
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_url, no_defaults=True)
        except Exception:
            executable = resolve_chrome_executable()
            if not executable:
                raise FileNotFoundError("Google Chrome or Chromium executable not found on host.")
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            command = self._build_launch_command(executable, headless, self.selected_profile)
            _launch_detached(command)
            for _ in range(24):
                await asyncio.sleep(.25)
                try:
                    self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_url, no_defaults=True)
                    break
                except Exception:
                    pass
            else:
                raise TimeoutError(f"Failed to connect to Chrome on port {self.cdp_port}.")
        self.is_cdp_connection = True
        if not self.browser.contexts:
            raise RuntimeError("Chrome has no native browser context.")
        self.context = self.browser.contexts[0]

    async def _discover(self):
        """Try multiple anchors before declaring a native context unidentifiable."""
        groups, unresolved = {}, {}
        if not self.context:
            return unresolved
        for page in list(self.context.pages):
            if not page.is_closed():
                groups.setdefault(await native_context(page), []).append(page)
        for context_id, anchors in groups.items():
            if context_id in self._context_profiles:
                continue
            for anchor in reversed(anchors):
                try:
                    self._context_profiles[context_id] = await identify_profile(anchor, self.profile_dir)
                    break
                except Exception as error:
                    unresolved[context_id] = str(error)
            if context_id in self._context_profiles:
                unresolved.pop(context_id, None)
        return unresolved

    async def _profile_pages(self, directory=None):
        directory = directory or self.selected_profile
        unresolved = await self._discover()
        pages = []
        for page in list(self.context.pages) if self.context else []:
            if not page.is_closed() and self._context_profiles.get(await native_context(page)) == directory:
                pages.append(page)
        if not pages and unresolved:
            raise RuntimeError("Cannot identify open Chrome profiles safely: " + "; ".join(unresolved.values()))
        return pages

    async def _open_profile(self, directory):
        """Ask Chrome to open a closed profile, then verify the resulting page's profile path."""
        executable = resolve_chrome_executable()
        if not executable:
            raise FileNotFoundError("Google Chrome or Chromium executable not found on host.")
        command = self._build_launch_command(executable, False, directory) + ["--new-tab", "about:blank"]
        _launch_detached(command)
        # Managed Chrome may replace CLI URLs with its new-tab page. Identify by
        # native context and a probe's actual profile path, never a marker URL.
        for _ in range(80):
            await asyncio.sleep(.1)
            pages = await self._profile_pages(directory)
            if pages:
                return pages[-1]
        raise TimeoutError(f"Chrome did not expose the new {directory!r} profile tab.")

    async def _activate_profile(self, directory):
        pages = await self._profile_pages(directory)
        page = self._last_pages.get(directory)
        if page not in pages:
            page = pages[-1] if pages else await self._open_profile(directory)
        self._select(directory, page)
        await safe_bring_to_front(page)

    async def start(self, url=None, headless=False):
        try:
            await self._connect(headless)
            # Observe focus before probes temporarily activate their opener tabs.
            focused = None
            if not self.selected_profile:
                for candidate in list(self.context.pages):
                    try:
                        if await asyncio.wait_for(candidate.evaluate("document.hasFocus()"), .5):
                            focused = candidate
                            break
                    except Exception:
                        pass
            await self._discover()
            if self.selected_profile:
                await self._activate_profile(self.selected_profile)
            else:
                # A failed probe of the focused profile must not redirect the
                # caller into an unrelated, successfully identified profile.
                if focused is not None and await native_context(focused) not in self._context_profiles:
                    raise RuntimeError("Cannot identify the focused Chrome profile safely.")
                pages = [p for p in self.context.pages if not p.is_closed()
                         and await native_context(p) in self._context_profiles]
                if not pages:
                    await self._activate_profile("Default")
                else:
                    page = focused if focused in pages else pages[-1]
                    self._select(self._context_profiles[await native_context(page)], page)
            if url:
                await self.page.goto(url, wait_until="domcontentloaded")
            return True
        except Exception as error:
            logger.error("Failed to start browser session: %s", error)
            return False

    async def browser_launcher(self, action=None, profile=None):
        if action not in ("list_profiles", "open"):
            return {"success": False, "error": "Action must be 'list_profiles' or 'open'."}
        if action == "list_profiles":
            # Read disk even when detached; do not connect or launch as a side effect.
            open_profiles = set()
            connected = bool(self.browser and self.browser.is_connected())
            if connected:
                await self._discover()
                for page in list(self.context.pages):
                    if not page.is_closed():
                        open_profiles.add(self._context_profiles.get(await native_context(page)))
            return {"success": True, "selected_profile": self.selected_profile, "connected": connected,
                    "profiles": [{"directory": d, "name": i.get("name", d),
                                  "selected": d == self.selected_profile,
                                  "is_open": d in open_profiles if connected else None}
                                 for d, i in available_profiles(self.profile_dir).items()]}
        old_profile, old_page = self.selected_profile, self.page
        old_state_file, old_auth_manager = self.state_file, self.auth_manager
        old_last_pages = self._last_pages.copy()
        try:
            directory = self._resolve_profile_directory(profile)
            # If Chrome isn't running, launch the requested profile, not last-used.
            self.selected_profile = directory
            await self._connect()
            await self._activate_profile(directory)
            return {"success": True, "selected_profile": directory,
                    "profile_directory": directory, "url": self.page.url,
                    "open_tabs": len(await self._profile_pages())}
        except BaseException as error:
            # Roll back synchronously, including the existing AuthManager's
            # in-memory state. Cancellation must not leave a half-switch behind.
            self.selected_profile, self.page = old_profile, old_page
            self.state_file, self.auth_manager = old_state_file, old_auth_manager
            self._last_pages.clear()
            self._last_pages.update(old_last_pages)
            if not isinstance(error, Exception):
                raise
            return {"success": False, "error": str(error)}

    async def ensure_active(self):
        try:
            if self.browser and self.browser.is_connected():
                pages = await self._profile_pages()
                if self.page in pages:
                    return True
                if pages:
                    self._select(self.selected_profile, pages[-1])
                    return True
                await self._activate_profile(self.selected_profile or "Default")
                return True
        except Exception as error:
            # Fail closed on mapping errors, never fall back to another profile's page.
            logger.warning("Cannot verify selected Chrome profile: %s", error)
            return False
        return await self.start()

    async def list_tabs(self):
        if not await self.ensure_active():
            return {"success": False, "error": "Browser is not running or profile cannot be verified."}
        pages = await self._profile_pages()
        return {"success": True, "selected_profile": self.selected_profile, "total_tabs": len(pages),
                "tabs": [{"index": i, "title": await safe_get_title(p), "url": p.url,
                          "is_active": p == self.page} for i, p in enumerate(pages)],
                "timestamp": datetime.now().isoformat()}

    async def switch_tab(self, index):
        if not await self.ensure_active():
            return {"success": False, "error": "Browser is not running."}
        pages = await self._profile_pages()
        if not isinstance(index, int) or not 0 <= index < len(pages):
            return {"success": False, "error": f"Tab index {index} out of range (0-{len(pages)-1})"}
        self._select(self.selected_profile, pages[index])
        await safe_bring_to_front(self.page)
        return {"success": True, "message": f"Switched to tab {index}",
                "title": await safe_get_title(self.page), "url": self.page.url}

    async def new_tab(self, url="about:blank", wait_until="domcontentloaded"):
        if not await self.ensure_active():
            return {"success": False, "error": "Browser is not running."}
        try:
            page = await profile_popup(self.page)
            self._select(self.selected_profile, page)
            if url and url != "about:blank":
                await page.goto(url, wait_until=wait_until, timeout=DEFAULT_PAGE_LOAD_TIMEOUT_MS)
            pages = await self._profile_pages()
            return {"success": True, "message": "Opened new tab", "tab_index": pages.index(page),
                    "url": page.url, "title": await safe_get_title(page)}
        except Exception as error:
            return {"success": False, "error": f"Failed to open new tab: {error}"}

    async def close_tab(self, index=None):
        if not await self.ensure_active():
            return {"success": False, "error": "Browser is not running."}
        pages = await self._profile_pages()
        target = self.page if index is None else (pages[index] if isinstance(index, int) and 0 <= index < len(pages) else None)
        if target not in pages:
            return {"success": False, "error": f"Invalid tab index {index}"}
        try:
            url = target.url
            await target.close()
            remaining = await self._profile_pages()
            if self.page == target:
                self.page = remaining[-1] if remaining else None
                self._last_pages[self.selected_profile] = self.page
                if self.page:
                    await safe_bring_to_front(self.page)
            return {"success": True, "message": "Closed tab", "closed_url": url,
                    "remaining_tabs": len(remaining)}
        except Exception as error:
            return {"success": False, "error": f"Failed to close tab: {error}"}

    async def session_status(self):
        status = {"saved_session_exists": self.auth_manager.has_saved_session(),
                  "state_file": str(self.state_file), "authenticated_active": False,
                  "active_url": None, "active_title": None, "open_tabs": 0,
                  "selected_profile": self.selected_profile,
                  "is_cdp_connection": self.is_cdp_connection,
                  "timestamp": datetime.now().isoformat()}
        if self.browser and self.browser.is_connected():
            try:
                pages = await self._profile_pages()
                status["open_tabs"] = len(pages)
                if self.page in pages:
                    status.update(active_url=self.page.url, active_title=await safe_get_title(self.page),
                                  authenticated_active=not self.auth_manager.is_auth_domain(self.page.url))
            except Exception as error:
                status["error"] = str(error)
        return status

    async def authenticate(self, url=None, timeout_seconds=DEFAULT_AUTH_TIMEOUT_S):
        if not await self.ensure_active():
            return {"success": False, "error": "Failed to launch browser for authentication."}
        if url:
            await self.page.goto(url, wait_until="domcontentloaded")
        await safe_bring_to_front(self.page)
        success = await self.auth_manager.monitor_auth(self.page, self.context, timeout_seconds=timeout_seconds)
        return {"success": success, "authenticated": success, "selected_profile": self.selected_profile,
                "current_url": self.page.url, "title": await safe_get_title(self.page),
                "timestamp": datetime.now().isoformat()}

    async def close(self):
        """Stop our transport, leaving detached Chrome and all user windows alive."""
        try:
            if self.context and self.page and not self.page.is_closed():
                await self.auth_manager.save_storage_state(self.context, page=self.page)
            if self.browser and not self.is_cdp_connection:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as error:
            logger.warning("Error during browser close: %s", error)
        finally:
            self.browser = self.context = self.page = self.playwright = None
            self.is_cdp_connection = False
            self._context_profiles.clear()
