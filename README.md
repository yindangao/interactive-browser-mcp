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

## Architectural Tenets and Design Rationale

To support the shared interactive philosophy, the infrastructure layer strictly adheres to three foundational choices. Understanding why these choices were made prevents accidental regressions during future refactorings.

### Official Google Chrome Over Test Chromium

**The Rationale**:
An enterprise AI assistant cannot function effectively in a sterile sandbox. It must operate within the user's authentic corporate environment, inheriting existing identities, security permissions, and trusted certificates.

**Key Benefits**:
- **Seamless Enterprise Authentication**: Corporate Single Sign-On (PingFederate, Okta, Microsoft Online) relies on device enrollment, trusted root certificates, and domain tokens. Official Google Chrome integrates with macOS keychain and enterprise certificates natively.
- **Google Password Manager and Auto-fill**: Saved credentials and password manager integration remain active, avoiding repetitive manual credential prompts.
- **Extensions and Bookmarks**: The user's bookmarks, internal intranet shortcuts, and enterprise Chrome extensions are readily available.

**Failure Mode Prevented**:
Playwright's bundled "Google Chrome for Testing" and upstream Chromium binaries intentionally disable Google account sync, password managers, and enterprise policy integrations. Using test binaries creates an alienated sandbox where corporate logins fail and sessions cannot persist.

---

### Detached Background Daemon

**The Rationale**:
The browser belongs to the user, not to the ephemeral Python process. Tool execution, server reloads, and AI agent lifecycles are inherently transient, while the user's research session is continuous.

**Key Benefits**:
- **Lifecycle Decoupling**: The MCP server can restart, crash, or be updated during active development without closing the user's browser window, terminating open tabs, or dropping active sessions.
- **Sub-Second Tool Re-attachment**: Instead of paying a 5 to 10 second startup cost to cold-boot a new browser on every tool invocation, connecting to an already-warm daemon over CDP takes under 50 milliseconds.
- **Uninterrupted Human Workflow**: The user can continue reading, typing, or inspecting pages in the open Chrome window even when the agent is idle or stopped.

**Failure Mode Prevented**:
Binding the browser process directly as a child of the Python runtime causes every server restart or script termination to abruptly kill the browser, losing all open tabs, unsaved text, and active session states.

---

### Chrome DevTools Protocol Exclusively

**The Rationale**:
The relationship between the agent and the browser is that of an "inspector and assistant", not an "owner and conqueror". Communication must happen over a standard remote inspection protocol that permits clean attachment and detachment.

**Key Benefits**:
- **Non-Destructive Teardown**: When the MCP server closes or the agent finishes a turn, calling `browser.disconnect()` cleanly detaches the socket while leaving Chrome, its tabs, and its runtime memory untouched.
- **Concurrent Inspection**: Multiple automation tools, Python scripts, or Chrome DevTools windows can attach to the same running browser on port 9222 simultaneously without process contention.
- **Standardized Foundation**: Tools interact through standard CDP primitives, decoupling the MCP server logic from Playwright's specific internal release cycle.

**Failure Mode Prevented**:
Playwright's high-level `launch_persistent_context()` API assumes exclusive process ownership designed for automated test suites. It passes restrictive command-line flags, overrides default profiles, and terminates the entire browser process upon script exit. Restricting Playwright to `connect_over_cdp()` ensures non-destructive, persistent collaboration.

---

## Highlights

- **Shared Collaborative Workspace**: Designed for human-and-agent co-browsing, balancing quiet background execution with visible interaction when needed.
- **Detached Native Chrome Daemon**: Automatically resolves official enterprise Google Chrome, spawns an independent daemon on port 9222, and attaches via CDP so server restarts never close active tabs.
- **Lean 12-Tool Architecture**: Modular, declarative design separating perception, interaction, tab management, and script execution.
- **Smart DOM Perception (`browse_page`)**: Automated DOM boilerplate pruning (headers, footers, mega-menus, modals) with outline and link discovery modes.
- **API-First Automation (`evaluate_js`)**: Directly queries internal REST endpoints (Jira, Confluence, ServiceNow) via `window.fetch()` leveraging active SSO session cookies.
- **SSO and MFA Persistence**: Performs interactive login once; persists session storage state (cookies, local storage) in `.data/` and maintains persistent corporate identity across runs.
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
├── mcp_server.py             # Top-level MCP server entrypoint with runtime fallbacks
├── pyproject.toml            # Python packaging metadata
├── requirements.txt          # Pip dependencies (mcp, playwright)
├── instructions.md           # LLM agent usage guidelines and workflow patterns
├── schemas/                  # Exported MCP tool JSON schemas
│
├── browser_mcp/              # Core Python package
│   ├── config.py             # Chrome path resolution, profile paths, and environment defaults
│   ├── server.py             # MCP server lifecycle and stdio transport
│   ├── core/
│   │   ├── session.py        # Detached Chrome daemon lifecycle, CDP reconnect, tab routing
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
│   └── test_browser_suite.py # 5-phase test suite (schema, live session, DOM, actions, tools)
└── .data/                    # Isolated runtime data (ignored in git)
    ├── chrome_profile/       # Persistent user profile (bookmarks, credentials, cookies)
    └── browser_session_state.json # Serialized session state metadata
```

---

## Installation & Setup

### 1. Environment Setup

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# (Optional) Install Playwright Chromium fallback if official Google Chrome is not installed
playwright install chromium
```

### 2. Run the Verification Suite

Run the automated 5-phase test suite to verify tool schema registration, daemon launching, CDP attachment, and DOM extraction:

```bash
python tests/test_browser_suite.py
```

### 3. MCP Server Registration

Add the server entry to your client configuration (e.g., `mcp_config.json`, Claude Desktop, or Cursor):

```json
{
  "mcpServers": {
    "interactive-browser-mcp": {
      "command": "/path/to/venv/bin/python",
      "args": [
        "/path/to/personal_agent/interactive-browser-mcp/mcp_server.py"
      ]
    }
  }
}
```

Or start the server directly over stdio:

```bash
python mcp_server.py
```
