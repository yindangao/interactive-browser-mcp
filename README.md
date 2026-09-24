# Interactive Browser MCP Server

An API-first, production-grade Model Context Protocol (MCP) server for enterprise web automation and session persistence using Playwright and Chrome DevTools Protocol (CDP).

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
