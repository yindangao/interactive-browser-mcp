# interactive-browser-mcp Best Practices & Tool Reference

## 1. Architectural Philosophy: The Shared Interactive Browser
This MCP server provides a high-performance, human-and-agent shared browser environment running on official Google Chrome over Chrome DevTools Protocol (CDP) with active corporate Single Sign-On (SSO / MFA / PingFederate) session cookies.

- **Visual Co-Presence**: The user and agent share the exact same visible browser window in real-time.
- **Human-in-the-Loop Assist**: The user can assist with hardware MFA tokens (YubiKey), Push approvals, or CAPTCHAs in the open window.
- **Persistent Detached Daemon**: The browser runs as an independent daemon on port 9222; restarting or disconnecting the MCP server never terminates the user's active window or tabs.
- **Direct REST API Preference**: When interacting with Jira, Confluence, ServiceNow, or internal portals, prefer direct REST API calls via `evaluate_js` (`window.fetch()`) over manual DOM clicking or scraping.
  - Internal enterprise tools expose rich JSON REST APIs.
  - When `evaluate_js` runs `window.fetch()`, the browser automatically includes all necessary authentication cookies, CSRF tokens (`JSESSIONID`, `atlassian.xsrf.token`), and headers.
  - REST queries are instantaneous (~200ms), 100% deterministic, and consume 10x fewer tokens than full page reads.

---

## 2. The 12-Tool Topology

| Category | Tool | Best Used For |
| :--- | :--- | :--- |
| **Session & Auth** | `session_status` | Check active tab, title, CDP health, and cookie state. |
| | `authenticate` | Surface visible browser for manual SSO/MFA sign-in when redirected. |
| **Tab Management** | `tab_list` | Inspect all open browser tabs with index and active status. |
| | `tab_new` | Open disposable tab for a separate task without polluting current state. |
| | `tab_switch` | Focus a specific tab by 0-based index. |
| | `tab_close` | Close a finished tab to release browser memory. |
| **Perception** | `browse_page` | Noise-pruned markdown extraction. Strips headers/navs/modals. Supports `mode='outline'`, `mode='links'`, `mode='content'`, and `selector` scoping. |
| | `take_screenshot` | Viewport visual capture for layout, QR codes, or visual verification. |
| **Interaction** | `click_element` | Click buttons, tabs, accordions by CSS selector or plain text (e.g. `'#submit-btn'`, `'text="Android"'`). |
| | `fill_input` | Fill search boxes or forms; optional `press_enter=True` executes search in 1 call. |
| | `scroll_page` | Scroll window or nested scrollable containers (Teams chats, Slack feeds, Jira boards). |
| **API & Extraction Engine** | `evaluate_js` | Run arbitrary JS, `fetch()` internal REST APIs with SSO cookies, or query DOM nodes. |

---

## 3. High-Efficiency Workflow Patterns

### Pattern A: Inspecting & Reading Web Pages
1. **Quick Outline**: When landing on a large page, run `browse_page(mode="outline")` to see H1–H6 hierarchy in <100 tokens.
2. **Targeted Reading**: Scope directly to the section you need using `browse_page(selector="#section-id")`.
3. **Link Discovery**: Run `browse_page(mode="links")` to obtain a clean Markdown list of clickable links.
4. **Clean Reading**: Default `browse_page()` automatically strips mega-menus, headers, footers, popups, and scripts, returning clean article content under the 25,000 char threshold.

### Pattern B: REST API Querying via `evaluate_js`
Wrap asynchronous code in an Immediately Invoked Function Expression (IIFE):
```javascript
(async () => {
  const res = await fetch('/rest/api/2/issue/MYAT-10310', {
    method: 'GET',
    headers: { 'Accept': 'application/json' }
  });
  if (!res.ok) return { error: res.status, text: await res.text() };
  return await res.json();
})()
```

### Pattern C: Search & Form Submission
Use `fill_input` with `press_enter=True` to execute in one turn:
```json
{
  "selector": "input[type='search']",
  "text": "BYOD mobile enrollment",
  "press_enter": true
}
```

### Pattern D: Virtualized Infinite Feeds
For modern SPAs (Teams chat, Slack, Jira swimlanes) where older messages load on scroll:
```json
{
  "direction": "up",
  "amount": 800,
  "selector": ".chat-message-list"
}
```
If `selector` is omitted, `scroll_page` automatically searches for the primary nested scrollable container before falling back to the window.
