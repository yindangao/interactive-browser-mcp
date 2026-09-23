# interactive-browser-mcp Best Practices & Guidelines

## 1. Architectural Philosophy: API-First via Browser Runtime
This MCP server controls an active Chromium instance connected over Chrome DevTools Protocol (CDP) or Playwright. The browser maintains active corporate Single Sign-On (SSO / MFA / PingFederate) session cookies.

**Key Rule:** **Always prefer direct REST API calls via `evaluate_js` over manual DOM clicking or scraping.**
- Internal enterprise tools (Jira, Confluence, ServiceNow, ADAM) expose rich JSON REST APIs.
- When `evaluate_js` runs `window.fetch()`, the browser automatically includes all necessary authentication cookies, CSRF tokens (`JSESSIONID`, `atlassian.xsrf.token`), and headers.
- REST queries are instantaneous (~200ms), 100% deterministic, and consume 10x fewer context window tokens than raw DOM dumps.

---

## 2. Standard Workflow Pattern

### Step A: Verify or Establish Domain Context
1. Check `session_status` to see if the browser is running and which page/tab is active.
2. If the browser is on `about:blank` or a different domain, use `browse_page` with `url="https://<target-domain>"` to navigate to the origin and mount SSO cookies.
   *Note: `browse_page` defaults to `wait_until="domcontentloaded"`, returning in <1s without freezing on background telemetry.*

### Step B: Execute API Calls via `evaluate_js`
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

For mutating calls (PUT / POST / DELETE):
```javascript
(async () => {
  const res = await fetch('/rest/api/2/issue/MYAT-10310', {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'X-Atlassian-Token': 'no-check'
    },
    body: JSON.stringify({
      update: {
        comment: [{ add: { body: "My automated comment" } }]
      }
    })
  });
  return { status: res.status, ok: res.ok };
})()
```

### Step C: Structured DOM Reading (When API is Unavailable)
If no REST API is available, extract only targeted text/attributes via `evaluate_js`:
```javascript
(() => {
  const rows = Array.from(document.querySelectorAll('.data-row'));
  return rows.map(r => ({
    name: r.querySelector('.title')?.innerText.trim(),
    status: r.querySelector('.badge')?.innerText.trim()
  }));
})()
```
Never return raw HTML trees or huge unparsed DOM chunks into the chat context.

---

## 3. Tab Management Protocol
- **List open tabs**: `tab_list` returns 0-based index, title, URL, and active flag.
- **Switch tab**: `tab_switch(index=N)` focuses the target tab.
- **Open new tab**: `tab_new(url="https://...")` keeps workflows separate and avoids polluting existing work.
- **Close tab**: `tab_close(index=N)` cleans up disposable tabs after completion.

---

## 4. Authentication Recovery
- If an API or page returns `401 Unauthorized` or redirects to PingFederate / Okta / Azure AD:
  1. Call `authenticate(url="https://<target-domain>")` to surface the visible browser window for user MFA/SSO.
  2. The server monitors and auto-saves the authenticated session state upon completion.
