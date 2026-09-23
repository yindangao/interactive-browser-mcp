# Interactive Browser MCP Server

An API-first, production-grade Model Context Protocol (MCP) server for enterprise web automation and session persistence using Playwright and Chrome DevTools Protocol (CDP).

---

## Highlights

- **API-First Automation**: Interacts with enterprise web apps (Jira, Confluence, ServiceNow, ADAM) by executing authenticated `window.fetch()` calls in the browser context via `evaluate_js`. No slow or fragile DOM clicking.
- **SSO / MFA Persistence**: Performs interactive login once; persists session storage state (cookies, local storage) for subsequent headless/visible runs.
- **Ultra-Low Latency**: Defaults to `domcontentloaded` wait strategy, bypassing prolonged background telemetry hangs on complex Single Page Applications (SPAs).
- **Tab & Window Management**: Native tools to list, switch, create, and close browser tabs across multiple contexts.

---

## Tool Catalog

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| `authenticate` | `url?: string`, `timeout_seconds?: int` | Opens a visible browser window to let the user complete corporate SSO / MFA / PingFederate login, then saves session cookies. |
| `browse_page` | `url: string`, `wait_until?: string` | Navigates to a target URL to mount origin context and load cookies. Defaults to `domcontentloaded` for fast SPA rendering. |
| `evaluate_js` | `script: string` | **Primary tool**. Executes JavaScript in the active page. Wraps async `fetch()` in an IIFE to query or mutate authenticated REST APIs with corporate SSO session cookies. |
| `session_status` | _none_ | Returns current browser health, active URL, active page title, open tab count, and authentication state. |
| `tab_close` | `index?: int` | Closes a tab by index (or the currently active tab if omitted). |
| `tab_list` | _none_ | Lists all open tabs with their index, title, URL, and active status. |
| `tab_new` | `url?: string`, `wait_until?: string` | Opens a new browser tab and navigates to the given URL. |
| `tab_switch` | `index: int` | Switches active focus to the tab at the specified 0-based index. |
| `take_screenshot` | `output_path?: string` | Captures a high-resolution screenshot of the visible page context for visual verification. |

---

## Setup & Installation

### 1. Prerequisites
- Python 3.10+
- Playwright Chromium dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configuration (`mcp_config.json`)
Register the server in your MCP client configuration:

```json
{
  "mcpServers": {
    "interactive-browser-mcp": {
      "command": "/path/to/venv/bin/python",
      "args": [
        "/path/to/interactive-browser-mcp/mcp_server.py"
      ],
      "env": {
        "AUTO_START_BROWSER": "false"
      }
    }
  }
}
```

### 3. Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `AUTO_START_BROWSER` | `true` | When `true`, automatically re-attaches to the browser session at server launch if a saved session state exists. |
| `BROWSER_SESSION_STATE` | `./browser_session_state.json` | Path to Playwright storage state JSON containing saved cookies. |
| `CHROME_PROFILE_DIR` | `./chrome_profile` | User data directory for persistent browser profile and cache. |
| `USE_SYSTEM_CHROME` | `false` | When `true`, launches system `/Applications/Google Chrome.app` instead of bundled Chromium. |

---

## Development & Usage Guidelines

See [`instructions.md`](instructions.md) for detailed guidelines on writing asynchronous `evaluate_js` snippets, structuring REST API payloads, and managing browser sessions.
