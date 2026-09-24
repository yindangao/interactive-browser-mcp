"""Configuration and environment path resolution for browser_mcp."""

import os
from pathlib import Path
from typing import Tuple

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

# Authentication domains triggering MFA/SSO intercept
AUTH_DOMAINS: Tuple[str, ...] = (
    "pfedprod.wal-mart.com",
    "login.microsoftonline.com",
    "login.wal-mart.com",
    "identity.wal-mart.com",
    "auth.wal-mart.com",
    "pingfederate",
    "okta",
)
