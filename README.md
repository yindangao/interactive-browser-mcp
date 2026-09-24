# Interactive Browser MCP Server

An API-first, production-grade Model Context Protocol (MCP) server for enterprise web automation and session persistence using Playwright and Chrome DevTools Protocol (CDP).

---

## Core Philosophy: The Shared Interactive Browser

This server is designed around a single guiding principle: **the browser is a shared workspace for the human user and the AI agent.**

Unlike traditional web scraping or automated test runners that spin up isolated, hidden browsers, this MCP server connects directly to the user's live browser where both can collaborate seamlessly:
- **Quiet Background Automation by Default**: The agent performs fast, low-overhead tasks silently in the background (such as querying internal REST APIs via `evaluate_js`, parsing DOM nodes, or inspecting tabs) without hijacking focus or disrupting the user's flow.
- **Visible Interactivity on Demand**: The browser is always accessible when human interaction matters. When a flow encounters a complex CAPTCHA, hardware security key (YubiKey), Symantec VIP MFA, or ambiguous step, the user steps into the open window to assist, and the agent picks up immediately once completed.
- **Shared Credentials and Muscle Memory**: The browser retains the user's authentic enterprise profile, bookmarks, corporate single sign-on (SSO), and Google Password Manager.

---

## Architectural Tenets

To preserve this collaborative philosophy, the infrastructure layer strictly adheres to three non-negotiable rules:

### Official Google Chrome Over Test Chromium
- The server resolves and launches the official enterprise **Google Chrome** binary (`/Applications/Google Chrome.app`), never Playwright's bundled "Google Chrome for Testing".
- Automated test binaries strip out Google account sync, corporate single sign-on, and Google Password Manager. Official Google Chrome preserves all three.
- The persistent profile directory (`.data/chrome_profile`) stores full user settings, extensions, bookmarks, and sessions across machine reboots.

### Detached Background Daemon
- The browser process is spawned as a detached system daemon using `start_new_session=True`.
- It lives independently from the Python runtime or MCP server process.
- Restarting, upgrading, or crashing the MCP server **never closes the browser window** or terminates active tabs. The user's work is never interrupted.

### Chrome DevTools Protocol (CDP) Exclusively
- Automation connects strictly via CDP on port `9222` (`http://127.0.0.1:9222`).
- On server shutdown, the client only disconnects the CDP socket (`browser.disconnect()`) without killing the host process.
- **Never replace this with `launch_persistent_context()`**: Playwright's internal persistent context API assumes CI/CD ownership, spawns test-runner binaries, and kills the browser process upon exit. Tool refactoring must never alter this daemon architecture.

---

## Highlights

- **Lean 12-Tool Architecture**: Modular, declarative design separating perception, interaction, tab management, and script execution.
- **Smart DOM Perception (`browse_page`)**: Automated DOM boilerplate pruning (headers, footers, mega-menus, modals) with outline and link discovery modes.
- **API-First Automation (`evaluate_js`)**: Directly queries internal REST endpoints (Jira, Confluence, ServiceNow) via `window.fetch()` leveraging active SSO session cookies.
- **SSO / MFA Persistence**: Performs interactive login once; persists session storage state (cookies, local storage) in `.data/` for subsequent headless/visible runs.
- **Isolated Runtime Storage**: Chrome profile caches and session states reside in `.data/`, keeping the repository root pristine.

---

## Tool Catalog

| Category | Tool | Parameters | Description |
| :--- | :--- | :--- | :--- |
| **Perception** | `browse_page` | `url?: str`, `wait_until?: str`, `selector?: str`, `mode?: str`, `max_length?: int` | Extracts clean Markdown text (`mode="content"`), heading hierarchy (`mode="outline"`), or deduplicated link list (`mode="links"`). |
| | `take_screenshot` | `output_path?: str` | Captures a high-resolution screenshot of the visible page viewport. |
| **Interaction** | `click_element` | `selector: str`, `timeout_ms?: int` | Clicks elements by CSS selector or plain text match (`text="Next"`). Pulses visual highlight before clicking. |
| | `fill_input` | `selector: str`, `text: str`, `press_enter?: bool`, `timeout_ms?: int` | Fills input fields with text and optionally simulates pressing Enter to submit in a single turn. |
| | `scroll_page` | `direction?: str`, `amount?: int`, `selector?: str` | Scrolls active window or nested virtualized containers (Teams chats, Slack feeds, Jira boards). |
| **API Engine** | `evaluate_js` | `script: str` | Executes JavaScript in the page context. Run `window.fetch()` to query internal REST APIs with corporate SSO cookies. |
| **Tab Routing** | `tab_list` | _none_ | Lists all open tabs with their index, title, URL, and active status. |
| | `tab_new` | `url?: str`, `wait_until?: str` | Opens a new browser tab and navigates to the given URL. |
| | `tab_switch` | `index: int` | Switches active focus to the tab at the specified 0-based index. |
| | `tab_close` | `index?: int` | Closes a tab by index (or the currently active tab if omitted). |
| **Session & Auth**| `session_status` | _none_ | Returns current browser health, CDP socket state, active URL, title, and saved tokens. |
| | `authenticate` | `url?: str`, `timeout_seconds?: int` | Opens an interactive browser window for corporate SSO / MFA / PingFederate login, auto-saving session state upon redirect. |

---

## Project Structure

```text
personal_agent/interactive-browser-mcp/
├── mcp_server.py             # Top-level MCP server entrypoint
├── pyproject.toml            # Python packaging metadata
├── requirements.txt          # Pip dependencies
├── instructions.md           # LLM agent usage guidelines
├── schemas/                  # Exported MCP tool JSON schemas
│
├── browser_mcp/              # Core Python package
│   ├── config.py             # Path resolution and environment defaults
│   ├── server.py             # MCP server lifecycle and stdio transport
│   ├── core/
│   │   ├── session.py        # Playwright lifecycle, CDP reconnect, tab routing
│   │   └── auth.py           # SSO/MFA detection and cookie persistence
│   ├── dom/
│   │   ├── reader.py         # Noise-pruned DOM-to-markdown conversion
│   │   └── actions.py        # Click, fill, scroll, and screenshot actions
│   └── tools/
│       ├── __init__.py       # Declarative registry and dispatch router
│       ├── navigation.py     # browse_page, tab_*, session_status, authenticate
│       ├── interaction.py    # click_element, fill_input, scroll_page
│       └── script.py         # evaluate_js, take_screenshot
│
├── tests/
│   └── test_browser_suite.py # Regression test suite
└── .data/                    # Isolated runtime data (ignored in git)
    ├── chrome_profile/
    └── browser_session_state.json
```

---

## Installation & Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Run the test suite
python tests/test_browser_suite.py

# 3. Start MCP server over stdio
python mcp_server.py
```
