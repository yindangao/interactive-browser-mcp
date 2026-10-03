"""Configuration and environment path resolution for browser_mcp."""

import os
from pathlib import Path
from typing import Tuple, Optional

# Project root: personal_agent/interactive-browser-mcp
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / ".data"

# Ensure runtime data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# CDP Port for persistent remote debugging
CDP_PORT: int = int(os.environ.get("CDP_PORT", "9222"))
CDP_URL: str = f"http://127.0.0.1:{CDP_PORT}"

# Chrome profile path resolution (prefers .data/, falls back to repo root if existing)
_env_profile = os.environ.get("CHROME_PROFILE_DIR")
if _env_profile:
    CHROME_PROFILE_DIR = Path(_env_profile).resolve()
elif (DATA_DIR / "chrome_profile").exists():
    CHROME_PROFILE_DIR = DATA_DIR / "chrome_profile"
elif (BASE_DIR / "chrome_profile").exists():
    CHROME_PROFILE_DIR = BASE_DIR / "chrome_profile"
else:
    CHROME_PROFILE_DIR = DATA_DIR / "chrome_profile"

def resolve_chrome_executable() -> Optional[str]:
    """Resolve path to official Google Chrome, Chromium, or Playwright bundled binary."""
    # 1. Explicit env override
    env_path = os.environ.get("CHROME_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    # 2. Native Google Chrome on macOS (official enterprise app)
    mac_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if mac_chrome.exists():
        return str(mac_chrome)

    # 3. Linux official Google Chrome or Chromium
    for linux_path in (
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ):
        if Path(linux_path).exists():
            return linux_path

    # 4. Windows Google Chrome
    for win_path in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if Path(win_path).exists():
            return win_path

    # 5. Fallback to Playwright's cached Chromium if system Chrome not installed
    ms_playwright_dir = Path.home() / "Library/Caches/ms-playwright"
    if ms_playwright_dir.exists():
        chromium_paths = list(ms_playwright_dir.glob("chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium"))
        if not chromium_paths:
            chromium_paths = list(ms_playwright_dir.glob("chromium-*/chrome-mac*/*.app/Contents/MacOS/*"))
        if chromium_paths:
            return str(chromium_paths[0])

    return None

# Browser session state file resolution
_env_state = os.environ.get("BROWSER_SESSION_STATE")
if _env_state:
    SESSION_STATE_FILE = Path(_env_state).resolve()
elif (DATA_DIR / "browser_session_state.json").exists():
    SESSION_STATE_FILE = DATA_DIR / "browser_session_state.json"
elif (BASE_DIR / "browser_session_state.json").exists():
    SESSION_STATE_FILE = BASE_DIR / "browser_session_state.json"
else:
    SESSION_STATE_FILE = DATA_DIR / "browser_session_state.json"

# Screenshot path resolution
DEFAULT_SCREENSHOT_PATH = DATA_DIR / "screenshot.png"

# Timeouts
DEFAULT_TIMEOUT_MS: int = 10000
DEFAULT_AUTH_TIMEOUT_S: int = 900
DEFAULT_PAGE_LOAD_TIMEOUT_MS: int = 45000

# Authentication domains triggering MFA/SSO intercept (extend via MCP_AUTH_DOMAINS env var)
DEFAULT_AUTH_DOMAINS: Tuple[str, ...] = (
    "login.microsoftonline.com",
    "pingfederate",
    "okta",
    "auth0",
)
_extra_domains: Tuple[str, ...] = tuple(
    d.strip() for d in os.environ.get("MCP_AUTH_DOMAINS", "").split(",") if d.strip()
)
AUTH_DOMAINS: Tuple[str, ...] = DEFAULT_AUTH_DOMAINS + _extra_domains
