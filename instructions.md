# interactive-browser-mcp Best Practices & Tool Reference

## 1. Architectural Philosophy: The Shared Interactive Browser
This MCP server provides a high-performance, human-and-agent shared browser environment running on official Google Chrome over Chrome DevTools Protocol (CDP) with active corporate Single Sign-On (SSO / MFA / PingFederate) session cookies.

- **Quiet Background Automation by Default**: The agent performs fast, low-overhead tasks silently in the background (querying REST APIs via `evaluate_js`, parsing DOM structures) without hijacking user focus.
- **Visible Interactivity on Demand**: The browser is always accessible when human interaction matters. The user can assist with hardware MFA tokens (YubiKey), push approvals, or CAPTCHAs directly in the open window.
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

### Pattern C: Form Filling and Interactive Clicking
1. **Form Submission in One Turn**: Use `fill_input` with `press_enter=True` to fill and submit searches:
```json
{
  "selector": "input[type='search']",
  "text": "BYOD mobile enrollment",
  "press_enter": true
}
```
2. **Clicking Buttons or Links**: Use `click_element` with either standard CSS selectors or plain text:
```json
{
  "selector": "button:has-text('Enroll Now')"
}
```
Or simply by label:
```json
{
  "selector": "iOS Setup Guide"
}
```
*Note: `click_element` automatically flashes an amber border on the target element before clicking, providing visual feedback to the user.*

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

### Pattern E: Multi-Tab Investigation and Isolation
When you need to investigate a link or documentation without losing your current form or working state:
1. **Open New Tab**: `tab_new(url="https://one.walmart.com/...")`
2. **Inspect Open Tabs**: `tab_list()` to verify open tabs and their indices.
3. **Switch Between Contexts**: `tab_switch(index=1)`
4. **Clean Up Disposable Tabs**: `tab_close(index=1)` when research is complete to conserve system resources.

### Pattern F: Session Verification & Human-in-the-Loop Authentication
1. **Check Session Health**: Call `session_status()` to inspect active URL, page title, and authentication state.
2. **Escalate to User for MFA**: If a corporate portal redirects to PingFederate, Okta, or a 2FA prompt:
   - Call `authenticate(url="https://login.walmart.com/...")` to ensure the window is visible.
   - Prompt the user directly to complete their hardware key, push notification, or biometric verification.
   - The tool waits until the login redirect succeeds and automatically serializes the updated session tokens.

### Pattern G: Visual Inspection & Media Capture
Use `take_screenshot` when visual verification is essential:
- Capturing enrollment QR codes (e.g., BYOD enrollment setup on mobile).
- Verifying data visualizations, charts, or complex layouts that cannot be represented in plain text.
- Inspecting rendered DOM state when selectors are ambiguous.
```json
{
  "output_path": ".data/enrollment_qr_code.png"
}
```

---

## 4. Behavioral Guidelines for Agents

- **Respect the Shared Space**: Never close tabs that the user is actively working in. Only close disposable tabs that you explicitly opened via `tab_new`.
- **Avoid Screen Thrashing**: Prefer reading clean content via `browse_page` or querying REST endpoints via `evaluate_js` rather than clicking through 10 intermediate UI screens.
- **Never Brute-Force Auth**: When encountering SSO / MFA / CAPTCHA barriers, immediately escalate to the user with `authenticate` rather than guessing or looping on login forms.
