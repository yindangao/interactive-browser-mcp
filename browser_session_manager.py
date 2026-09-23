"""Browser Session Manager for corporate internal and external page scraping and automation."""

import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

# Redefine print locally within this module to write to stderr to avoid corrupting MCP stdio JSON-RPC
_original_print = print
def print(*args, **kwargs):
    kwargs.setdefault('file', sys.stderr)
    _original_print(*args, **kwargs)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_STATE_FILE = str(Path(os.environ.get("BROWSER_SESSION_STATE", BASE_DIR / "browser_session_state.json")))
DEFAULT_CHROME_PROFILE = str(Path(os.environ.get("CHROME_PROFILE_DIR", BASE_DIR / "chrome_profile")))
DEFAULT_SCREENSHOT_PATH = str(BASE_DIR / "screenshot.png")

class BrowserSessionManager:
    """Manage the Playwright browser instance and session state."""

    def __init__(
        self,
        default_url: str = "https://www.google.com",
        state_file: Optional[str] = None,
        headless: bool = False,
    ):
        self.default_url = default_url
        self.state_file = Path(state_file or DEFAULT_STATE_FILE)
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.authenticated = False
        self.session_started_at: Optional[datetime] = None
        self.is_cdp_connection = False

    def _is_auth_domain(self, url: str) -> bool:
        """Check if a URL belongs to any corporate/SSO/Okta/PingFederate auth or login domain."""
        if not url:
            return False
        return any(domain in url.lower() for domain in [
            "pingfederate", "okta", "login.", "sso", "iam", "federate", 
            "pfedprod", "pfed", "idp", "saml", "resumesaml", "microsoftonline",
            "google.com/accounts", "adfs"
        ])

    async def close(self) -> None:
        """Clean up all active browser resources."""
        if self.is_cdp_connection:
            try:
                if self.browser:
                    await self.browser.disconnect()
            except Exception:
                pass
            finally:
                self.page = None
                self.context = None
                self.browser = None
                self.is_cdp_connection = False
                self.authenticated = False
            try:
                if self.playwright:
                    await self.playwright.stop()
            except Exception:
                pass
            finally:
                self.playwright = None
            return

        try:
            if self.page:
                await self.page.close()
        except Exception:
            pass
        finally:
            self.page = None

        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        finally:
            self.context = None

        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        finally:
            self.browser = None

        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        finally:
            self.playwright = None
            self.authenticated = False

    async def authenticate(self, url: Optional[str] = None, timeout_seconds: int = 900) -> bool:
        """Open a visible browser for manual corporate SSO/MFA login and save auth state."""
        debug_log = str(BASE_DIR / "browser_mcp_debug.log")
        with open(debug_log, "a") as f:
            f.write(f"\n[{datetime.now().isoformat()}] Entered authenticate()\n")
        try:
            await self.close()
            self.playwright = await async_playwright().start()
            
            # Use Playwright's bundled Chromium by default to prevent conflicts with standard Chrome profiles.
            # Set USE_SYSTEM_CHROME=true if you explicitly want to use official Chrome.
            use_system_chrome = os.environ.get("USE_SYSTEM_CHROME", "false").lower() in ("true", "1", "yes")
            if use_system_chrome:
                chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                executable_path = chrome_path if Path(chrome_path).exists() else None
            else:
                executable_path = None

            print("Launching visible browser for manual login...", flush=True)
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                executable_path=executable_path,
                args=["--disable-blink-features=AutomationControlled"],
            )
            
            self.context = await self.browser.new_context(
                viewport={"width": 1440, "height": 900},
                ignore_https_errors=True
            )
            self.page = await self.context.new_page()

            target_url = url or self.default_url
            print(f"Navigating to entrance: {target_url}", flush=True)
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            
            print("Please perform SSO/MFA login in the opened Chrome window.", flush=True)
            print("I will monitor the window. Once you are fully logged in and on the homepage, press Enter in the terminal, or wait.", flush=True)

            # We wait for either authentication signals or standard polling
            # Let's poll to check if we can find typical logged-in elements or cookies
            logged_in = await self._wait_for_login_settle(timeout_seconds=timeout_seconds)
            
            if logged_in:
                # Save the storage state (cookies, local storage)
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                await self.context.storage_state(path=str(self.state_file))
                print(f"Authentication successful! Saved session state to {self.state_file}", flush=True)
                await self.close()
                return True
            else:
                print("Login monitoring timed out or was incomplete.", flush=True)
                await self.close()
                return False
                
        except Exception as error:
            import traceback
            debug_log = str(BASE_DIR / "browser_mcp_debug.log")
            with open(debug_log, "a") as f:
                f.write(f"\n[{datetime.now().isoformat()}] Authentication setup failed: {error}\n")
                traceback.print_exc(file=f)
            print(f"Authentication setup failed: {error}", flush=True)
            await self.close()
            return False

    async def _wait_for_login_settle(self, timeout_seconds: int) -> bool:
        """Poll the active page to see if login has completed."""
        start = datetime.now()
        while (datetime.now() - start).total_seconds() < timeout_seconds:
            try:
                if not self.page:
                    await asyncio.sleep(1)
                    continue

                url = self.page.url or ""
                is_auth_domain = self._is_auth_domain(url)
                
                # Check for common internal home page elements, search bars, or user profile widgets
                has_wire_header = await self.page.query_selector("header, #header, .header, [role='banner']")
                
                if not is_auth_domain and has_wire_header:
                    # Give it another 3 seconds to settle and save all cookies
                    await asyncio.sleep(3)
                    return True
            except Exception:
                pass
            await asyncio.sleep(2)
        return True # Default to true to allow manual override / user save

    async def session_start(self) -> bool:
        """Initialize a visible browser session using saved auth state or connect via CDP."""
        try:
            storage_state = str(self.state_file) if self.state_file.exists() else None
            if not storage_state:
                print("No saved session state found. Starting fresh browser session...", flush=True)

            await self.close()
            self.playwright = await async_playwright().start()

            # Attempt connection to already-running Chrome via CDP on port 9222 first
            try:
                print("Attempting to connect to existing browser on port 9222 via CDP...", flush=True)
                self.browser = await self.playwright.chromium.connect_over_cdp("http://localhost:9222")
                self.is_cdp_connection = True
                
                # Fetch existing contexts and pages
                if self.browser.contexts:
                    self.context = self.browser.contexts[0]
                    if self.context.pages:
                        self.page = self.context.pages[0]
                    else:
                        self.page = await self.context.new_page()
                else:
                    self.context = await self.browser.new_context()
                    self.page = await self.context.new_page()
                
                self.authenticated = True
                self.session_started_at = datetime.now()
                print("Successfully reconnected to existing browser session!", flush=True)
                return True
            except Exception as cdp_err:
                print(f"No existing browser detected on port 9222 ({cdp_err}). Launching detached browser daemon...", flush=True)
                self.is_cdp_connection = False
            
            # If no existing browser is running, start a detached daemon process automatically
            if not self.is_cdp_connection:
                try:
                    import glob
                    import subprocess
                    
                    print("Launching Chromium as a detached daemon...", flush=True)
                    
                    # Resolve Playwright's Chromium executable dynamically on Mac
                    ms_playwright_dir = Path.home() / "Library/Caches/ms-playwright"
                    chromium_paths = list(ms_playwright_dir.glob("chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"))
                    
                    if chromium_paths:
                        executable_path = str(chromium_paths[0])
                    else:
                        executable_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                        
                    if not Path(executable_path).exists():
                        raise FileNotFoundError(f"Chromium/Chrome executable not found at: {executable_path}")
                        
                    cmd = [
                        executable_path,
                        "--remote-debugging-port=9222",
                        f"--user-data-dir={DEFAULT_CHROME_PROFILE}",
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check"
                    ]
                    
                    # Launch as a fully detached background process (survives parent Python server exit)
                    subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                    
                    # Wait and connect over CDP
                    for attempt in range(12):
                        try:
                            self.browser = await self.playwright.chromium.connect_over_cdp("http://localhost:9222")
                            self.is_cdp_connection = True
                            break
                        except Exception:
                            await asyncio.sleep(0.5)
                            
                    if not self.browser or not self.is_cdp_connection:
                        raise TimeoutError("Failed to connect to the detached browser on port 9222.")
                        
                    # Retrieve or initialize context and page
                    if self.browser.contexts:
                        self.context = self.browser.contexts[0]
                        if self.context.pages:
                            self.page = self.context.pages[0]
                        else:
                            self.page = await self.context.new_page()
                    else:
                        self.context = await self.browser.new_context()
                        self.page = await self.context.new_page()
                        
                    self.authenticated = True
                    self.session_started_at = datetime.now()
                    print("Successfully launched and connected to detached browser daemon!", flush=True)
                    return True
                    
                except Exception as launch_err:
                    print(f"Failed to launch detached daemon: {launch_err}. Falling back to standard process launch...", flush=True)
                    self.is_cdp_connection = False
                    
                    # Use standard launch fallback
                    use_system_chrome = os.environ.get("USE_SYSTEM_CHROME", "false").lower() in ("true", "1", "yes")
                    if use_system_chrome:
                        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                        executable_path = chrome_path if Path(chrome_path).exists() else None
                    else:
                        executable_path = None

                    self.browser = await self.playwright.chromium.launch(
                        headless=self.headless,
                        executable_path=executable_path,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    
                    context_args = {
                        "viewport": {"width": 1440, "height": 900},
                        "ignore_https_errors": True
                    }
                    if storage_state:
                        context_args["storage_state"] = storage_state
                    self.context = await self.browser.new_context(**context_args)
                    self.page = await self.context.new_page()
                    self.authenticated = True
                    self.session_started_at = datetime.now()
                    return True
        except Exception as error:
            print(f"Failed to start visible browser session: {error}", flush=True)
            await self.close()
            return False

    async def _ensure_active(self) -> bool:
        """Ensure active browser, context, and page connection."""
        is_page_active = False
        try:
            if self.page and not self.page.is_closed() and self.browser and self.browser.is_connected() and self.context:
                is_page_active = True
        except Exception:
            pass

        if not self.authenticated or not is_page_active or not self.context:
            return await self.session_start()
        return True

    async def browse_page(self, url: str, wait_until: str = "domcontentloaded") -> Dict[str, Any]:
        """Navigate to a URL and return the structured markdown content."""
        if not await self._ensure_active():
            return {
                "success": False,
                "error": "Not authenticated. Please run the authenticate tool first."
            }

        try:
            print(f"Navigating to {url} (wait_until={wait_until})...", flush=True)
            page_wait = wait_until if wait_until in ("domcontentloaded", "load", "networkidle") else "domcontentloaded"
            try:
                await self.page.goto(url, wait_until=page_wait, timeout=45000)
            except Exception as goto_err:
                print(f"Initial navigation message/redirect notice: {goto_err}", flush=True)

            # Check if we were redirected to login
            current_url = self.page.url or ""
            is_auth_domain = self._is_auth_domain(current_url)
            
            if is_auth_domain:
                print(f"[{datetime.now().isoformat()}] Detected redirection to authentication page: {current_url}", flush=True)
                print("Waiting for you to complete manual SSO/MFA login in the browser window...", flush=True)
                
                # Keep polling the page URL until we are no longer on the login/auth domain
                start_time = datetime.now()
                timeout = 600 # 10 minutes
                while (datetime.now() - start_time).total_seconds() < timeout:
                    await asyncio.sleep(2)
                    try:
                        current_url = self.page.url or ""
                        is_auth_domain = self._is_auth_domain(current_url)
                        
                        # Once we are no longer on the auth domain, check if we've successfully reached the content page
                        if not is_auth_domain:
                            print(f"[{datetime.now().isoformat()}] Authentication done! Original page or target domain is loading: {current_url}", flush=True)
                            
                            # Let it settle for a couple of seconds to make sure cookies are saved and page renders
                            await asyncio.sleep(3)
                            
                            # Auto-save state file so we have cookies for future requests
                            try:
                                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                                await self.context.storage_state(path=str(self.state_file))
                                print(f"Successfully saved authenticated session state to {self.state_file}", flush=True)
                            except Exception as e:
                                print(f"Warning: could not save session state: {e}", flush=True)
                                
                            break
                    except Exception:
                        pass
                else:
                    return {
                        "success": False,
                        "error": "Authentication monitoring timed out."
                    }

            # Settle down
            if wait_until == "networkidle":
                try:
                    await self.page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
            else:
                # Brief settle for SPA frameworks to complete initial DOM mount
                await asyncio.sleep(0.5)
            
            # Extract basic metadata and content
            title = await self.page.title()
            
            # Simple custom HTML to markdown extraction
            content = await self.page.evaluate(r"""() => {
                // Focus on primary text-carrying tags and ignore header/footer garbage
                const selectors = ['article', 'main', '#content', '.content', '.body', 'body'];
                let root = document.body;
                for (const selector of selectors) {
                    const found = document.querySelector(selector);
                    if (found) {
                        root = found;
                        break;
                    }
                }

                // Helper to clean up formatting
                function toMarkdown(node) {
                    if (node.nodeType === Node.TEXT_NODE) {
                        return node.textContent || '';
                    }
                    if (node.nodeType !== Node.ELEMENT_NODE) return '';

                    const tag = node.tagName.toLowerCase();
                    
                    // Ignore scripts, styles, nav bars, and footers
                    if (['script', 'style', 'nav', 'footer', 'header', 'noscript', 'iframe'].includes(tag)) {
                        return '';
                    }

                    const children = () => Array.from(node.childNodes).map(toMarkdown).join('');

                    if (tag === 'pre') {
                        return '\n```\n' + node.innerText.trim() + '\n```\n';
                    }
                    if (tag === 'code') {
                        return '`' + node.innerText + '`';
                    }
                    if (/^h[1-6]$/.test(tag)) {
                        const level = '#'.repeat(parseInt(tag[1], 10));
                        return '\n' + level + ' ' + children().trim() + '\n';
                    }
                    if (tag === 'strong' || tag === 'b') return '**' + children() + '**';
                    if (tag === 'em' || tag === 'i') return '_' + children() + '_';
                    if (tag === 'a') {
                        const href = node.getAttribute('href') || '';
                        const text = children().trim();
                        return href ? `[${text}](${href})` : text;
                    }
                    if (tag === 'ul' || tag === 'ol') {
                        return '\n' + children() + '\n';
                    }
                    if (tag === 'li') {
                        return '\n- ' + children().trim();
                    }
                    if (tag === 'p') {
                        return children().trim() + '\n\n';
                    }
                    if (tag === 'br') {
                        return '\n';
                    }
                    return children();
                }

                return toMarkdown(root).trim();
            }""")

            # Sanitize content
            content = re.sub(r'\n{3,}', '\n\n', content)

            return {
                "success": True,
                "url": self.page.url,
                "title": title,
                "content": content,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as error:
            # Check if redirect to SSO login happened
            current_url = self.page.url if self.page else ""
            if any(domain in current_url for domain in ["pingfederate", "okta", "login", "saml"]):
                self.authenticated = False
                return {
                    "success": False,
                    "error": "Session has expired (redirected to SSO). Please run authenticate tool again."
                }
            return {
                "success": False,
                "error": f"Failed to read page: {error}"
            }

    async def take_screenshot(self, output_path: Optional[str] = None) -> Dict[str, Any]:
        """Capture a screenshot of the current page in the visible window."""
        target_path = output_path or DEFAULT_SCREENSHOT_PATH
        if not self.page:
            return {
                "success": False,
                "error": "No active browser page open. Please run browse_page first."
            }
        try:
            # Ensure parent directory exists
            Path(target_path).parent.mkdir(parents=True, exist_ok=True)
            await self.page.screenshot(path=target_path)
            print(f"Screenshot successfully captured and saved to {target_path}", flush=True)
            return {
                "success": True,
                "path": target_path,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as error:
            return {
                "success": False,
                "error": f"Failed to take screenshot: {error}"
            }

    def _resolve_selector(self, selector: str) -> str:
        """Resolve a badge ID/number to the corresponding data-mcp-id CSS selector if applicable."""
        if not selector:
            return selector
        sel = str(selector).strip()
        if sel.isdigit():
            return f'[data-mcp-id="{sel}"]'
        if sel.lower().startswith("badge:"):
            badge_id = sel[6:].strip()
            return f'[data-mcp-id="{badge_id}"]'
        return selector

    async def _highlight_element(self, selector: str) -> None:
        """Briefly flash a red outline around the target element to provide visual feedback."""
        try:
            if self.page:
                resolved_sel = self._resolve_selector(selector)
                await self.page.evaluate(r"""(sel) => {
                    const el = document.querySelector(sel);
                    if (el) {
                        const originalOutline = el.style.outline;
                        el.style.outline = '3px solid #ff4d4f';
                        el.style.outlineOffset = '2px';
                        setTimeout(() => {
                            el.style.outline = originalOutline;
                        }, 1000);
                    }
                }""", resolved_sel)
        except Exception:
            pass

    async def get_interactive_elements(self) -> Dict[str, Any]:
        """Inject Vimium-style visual badges next to visible interactive elements and return them."""
        if not self.page:
            return {"success": False, "error": "No active browser page open."}
        try:
            elements = await self.page.evaluate(r"""() => {
                // 1. Remove any existing badges/overlays first to prevent duplicates
                const existingOverlays = document.querySelectorAll('.mcp-badge-overlay');
                existingOverlays.forEach(el => el.remove());
                
                const candidates = document.querySelectorAll('button, a, input, select, textarea, [role="button"], [role="link"], [onclick]');
                
                let idCounter = 1;
                const items = [];
                
                // Helper to check if element is visible on the screen
                function isElementVisible(el) {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                        rect.width > 0 &&
                        rect.height > 0 &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none' &&
                        style.opacity !== '0'
                    );
                }
                
                for (const el of candidates) {
                    if (!isElementVisible(el)) continue;
                    
                    const mcpId = idCounter.toString();
                    el.setAttribute('data-mcp-id', mcpId);
                    
                    // Extract useful text descriptive info
                    let text = "";
                    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                        text = el.placeholder || el.getAttribute('aria-label') || el.value || el.name || "";
                    } else {
                        text = el.innerText || el.getAttribute('aria-label') || "";
                    }
                    text = text.trim().substring(0, 80); // cap length
                    
                    items.push({
                        id: mcpId,
                        tag: el.tagName,
                        text: text,
                        type: el.getAttribute('type') || "",
                        role: el.getAttribute('role') || ""
                    });
                    
                    // Draw the visual badge
                    const rect = el.getBoundingClientRect();
                    const badge = document.createElement('div');
                    badge.className = 'mcp-badge-overlay';
                    badge.innerText = mcpId;
                    
                    // Style the badge (Vimium styled)
                    Object.assign(badge.style, {
                        position: 'absolute',
                        left: (window.scrollX + rect.left) + 'px',
                        top: (window.scrollY + rect.top) + 'px',
                        backgroundColor: '#ff4d4f',
                        color: 'white',
                        fontWeight: 'bold',
                        fontSize: '11px',
                        fontFamily: 'monospace',
                        padding: '2px 5px',
                        borderRadius: '3px',
                        boxShadow: '0 2px 5px rgba(0,0,0,0.3)',
                        zIndex: '2147483647', // maximum z-index
                        pointerEvents: 'none', // click passes through
                        lineHeight: '1'
                    });
                    
                    document.body.appendChild(badge);
                    idCounter++;
                }
                return items;
            }""")
            
            return {
                "success": True,
                "elements_count": len(elements),
                "elements": elements,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as error:
            return {"success": False, "error": f"Failed to get interactive elements: {error}"}

    async def clear_element_labels(self) -> Dict[str, Any]:
        """Remove any visible interaction badges from the page."""
        if not self.page:
            return {"success": False, "error": "No active browser page open."}
        try:
            await self.page.evaluate(r"""() => {
                const existingOverlays = document.querySelectorAll('.mcp-badge-overlay');
                existingOverlays.forEach(el => el.remove());
                
                const elements = document.querySelectorAll('[data-mcp-id]');
                elements.forEach(el => el.removeAttribute('data-mcp-id'));
            }""")
            return {"success": True, "timestamp": datetime.now().isoformat()}
        except Exception as error:
            return {"success": False, "error": f"Failed to clear labels: {error}"}

    async def evaluate_js(self, script: str) -> Dict[str, Any]:
        """Execute custom JavaScript in the active page and return the result."""
        if not self.page:
            return {"success": False, "error": "No active browser page open."}
        try:
            result = await self.page.evaluate(script)
            return {"success": True, "result": result, "timestamp": datetime.now().isoformat()}
        except Exception as error:
            return {"success": False, "error": f"Failed to evaluate JS: {error}"}

    async def click_element(self, selector: str, timeout_ms: int = 10000) -> Dict[str, Any]:
        """Click an element on the active page."""
        if not self.page:
            return {"success": False, "error": "No active browser page open."}
        try:
            resolved_sel = self._resolve_selector(selector)
            await self._highlight_element(resolved_sel)
            await self.page.click(resolved_sel, timeout=timeout_ms)
            return {"success": True, "selector": resolved_sel, "timestamp": datetime.now().isoformat()}
        except Exception as error:
            return {"success": False, "error": f"Failed to click element: {error}"}

    async def fill_input(self, selector: str, text: str, timeout_ms: int = 10000) -> Dict[str, Any]:
        """Fill an input field with text."""
        if not self.page:
            return {"success": False, "error": "No active browser page open."}
        try:
            resolved_sel = self._resolve_selector(selector)
            await self._highlight_element(resolved_sel)
            await self.page.fill(resolved_sel, text, timeout=timeout_ms)
            return {"success": True, "selector": resolved_sel, "timestamp": datetime.now().isoformat()}
        except Exception as error:
            return {"success": False, "error": f"Failed to fill input: {error}"}

    async def press_key(self, key: str, timeout_ms: int = 10000) -> Dict[str, Any]:
        """Simulate pressing a keyboard key (e.g., 'Enter', 'Tab')."""
        if not self.page:
            return {"success": False, "error": "No active browser page open."}
        try:
            await self.page.keyboard.press(key)
            return {"success": True, "key": key, "timestamp": datetime.now().isoformat()}
        except Exception as error:
            return {"success": False, "error": f"Failed to press key: {error}"}

    async def scroll_page(self, direction: str = "down", amount: int = 500, selector: str = None) -> Dict[str, Any]:
        """Scroll the active page or a specific scrollable element (supports both window and modern nested SPA scrollable containers)."""
        if not self.page:
            return {"success": False, "error": "No active browser page open."}
        try:
            resolved_sel = self._resolve_selector(selector) if selector else None
            
            # Detect and scroll both window and nested SPA scrollable divs (like Teams chats, Slack feeds)
            js_script = f"""async () => {{
                let targets = [];
                if ("{resolved_sel or ''}") {{
                    const el = document.querySelector("{resolved_sel or ''}");
                    if (el) {{
                        targets = [el];
                    }} else {{
                        return "selector_not_found";
                    }}
                }} else {{
                    const divs = Array.from(document.querySelectorAll('div, section, ul, ol'));
                    targets = divs.filter(el => {{
                        const style = window.getComputedStyle(el);
                        return (style.overflowY === 'auto' || style.overflowY === 'scroll') && el.scrollHeight > el.clientHeight;
                    }});
                }}
                
                if (targets.length === 0) {{
                    if ("{direction}" === "down") window.scrollBy(0, {amount});
                    else if ("{direction}" === "up") window.scrollBy(0, -{amount});
                    else if ("{direction}" === "bottom") window.scrollTo(0, document.body.scrollHeight);
                    else if ("{direction}" === "top") window.scrollTo(0, 0);
                    return "window_scrolled";
                }}
                
                targets.forEach(el => {{
                    if ("{direction}" === "down") el.scrollBy(0, {amount});
                    else if ("{direction}" === "up") el.scrollBy(0, -{amount});
                    else if ("{direction}" === "bottom") el.scrollTop = el.scrollHeight;
                    else if ("{direction}" === "top") el.scrollTop = 0;
                }});
                return `scrolled_${{targets.length}}_containers`;
            }}"""
            
            mode = await self.page.evaluate(js_script)
            if mode == "selector_not_found":
                return {"success": False, "error": f"Element matching selector '{selector}' was not found on the page."}
                
            return {
                "success": True, 
                "direction": direction, 
                "amount": amount,
                "selector": selector,
                "scroll_mode": mode,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as error:
            return {"success": False, "error": f"Failed to scroll: {error}"}

    async def list_tabs(self) -> list[dict[str, any]]:
        """List all open tabs in the browser context."""
        if not self.context:
            return []
        tabs = []
        for i, p in enumerate(self.context.pages):
            try:
                title = await p.title()
                url = p.url
                is_closed = p.is_closed()
            except Exception as e:
                title = "Unknown"
                url = "Unknown"
                is_closed = True
                
            tabs.append({
                "index": i,
                "title": title,
                "url": url,
                "is_closed": is_closed,
                "is_active": p == self.page
            })
        return tabs

    async def switch_tab(self, index: int) -> dict[str, any]:
        """Switch the active page reference to the specified tab index."""
        if not self.context:
            return {"success": False, "error": "No active browser session."}
        pages = self.context.pages
        if index < 0 or index >= len(pages):
            return {"success": False, "error": f"Invalid index. Available range: 0 to {len(pages) - 1}."}
        
        target_page = pages[index]
        if target_page.is_closed():
            return {"success": False, "error": f"Tab at index {index} is already closed."}
            
        self.page = target_page
        try:
            await self.page.bring_to_front()
        except Exception as e:
            pass
            
        return {
            "success": True,
            "index": index,
            "title": await self.page.title(),
            "url": self.page.url
        }

    async def new_tab(self, url: str = "about:blank", wait_until: str = "domcontentloaded") -> dict[str, any]:
        """Open a new browser tab, optionally navigating to a URL, and set it as active."""
        if not self.context:
            return {"success": False, "error": "No active browser session."}
        try:
            new_page = await self.context.new_page()
            self.page = new_page
            if url and url != "about:blank":
                page_wait = wait_until if wait_until in ("domcontentloaded", "load", "networkidle") else "domcontentloaded"
                await self.page.goto(url, wait_until=page_wait, timeout=30000)
            return {
                "success": True,
                "index": len(self.context.pages) - 1,
                "title": await self.page.title(),
                "url": self.page.url
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to open new tab: {e}"}

    async def close_tab(self, index: int = None) -> dict[str, any]:
        """Close a specific tab index, or close the currently active tab if no index is provided."""
        if not self.context:
            return {"success": False, "error": "No active browser session."}
        pages = self.context.pages
        if not pages:
            return {"success": False, "error": "No open tabs."}
        
        if index is None:
            target_page = self.page
            try:
                index = pages.index(target_page)
            except ValueError:
                index = 0
        else:
            if index < 0 or index >= len(pages):
                return {"success": False, "error": f"Invalid index. Available range: 0 to {len(pages) - 1}."}
            target_page = pages[index]

        try:
            await target_page.close()
            # If we closed the active page, switch focus to another remaining tab if any
            if target_page == self.page:
                remaining_pages = [p for p in self.context.pages if not p.is_closed()]
                if remaining_pages:
                    self.page = remaining_pages[-1]
                    await self.page.bring_to_front()
                else:
                    self.page = None
            
            # Recalculate remaining page info safely
            remaining_active = None
            if self.page:
                try:
                    remaining_active = {
                        "index": self.context.pages.index(self.page) if self.page in self.context.pages else -1,
                        "title": await self.page.title(),
                        "url": self.page.url
                    }
                except Exception:
                    pass

            return {
                "success": True,
                "closed_index": index,
                "active_tab": remaining_active
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to close tab: {e}"}

    def _merge_text_chunks(self, chunks: list[str]) -> str:
        """Merge sequentially scraped overlapping text chunks into a continuous deduplicated stream."""
        if not chunks:
            return ""
        # Filter empty or redundant adjacent chunks
        clean_chunks = []
        for c in chunks:
            if c and (not clean_chunks or c != clean_chunks[-1]):
                clean_chunks.append(c)
        if not clean_chunks:
            return ""
            
        merged = clean_chunks[0]
        for chunk in clean_chunks[1:]:
            merged_lines = merged.splitlines()
            chunk_lines = chunk.splitlines()
            
            # Find line-based overlap (suffix of merged matching prefix of chunk)
            overlap_len = 0
            max_overlap = min(len(merged_lines), len(chunk_lines))
            for i in range(1, max_overlap + 1):
                if merged_lines[-i:] == chunk_lines[:i]:
                    overlap_len = i
                    
            if overlap_len > 0:
                merged = "\n".join(merged_lines + chunk_lines[overlap_len:])
            else:
                merged += "\n" + chunk
        return merged

    async def dump_all_frames(self, scroll_loops: int = 0, accumulate: bool = False) -> list[dict[str, any]]:
        """Extract text from all frames in the page, with optional progressive scrolling and accumulation to bypass virtualization."""
        if not self.page:
            return []
        frames_info = []
        for i, frame in enumerate(self.page.frames):
            try:
                chunks = []
                if accumulate:
                    try:
                        # Reset scrollables to 0 first to ensure we scrape from the absolute top
                        await frame.evaluate("""async () => {
                            const elements = Array.from(document.querySelectorAll('*'));
                            const scrollables = elements.filter(el => {
                                const style = window.getComputedStyle(el);
                                const isScrollable = style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflow === 'auto' || style.overflow === 'scroll';
                                return isScrollable && el.scrollHeight > el.clientHeight;
                            });
                            if (scrollables.length === 0) {
                                window.scrollTo(0, 0);
                                window.dispatchEvent(new Event('scroll'));
                            } else {
                                scrollables.forEach(el => {
                                    el.scrollTop = 0;
                                    el.dispatchEvent(new Event('scroll'));
                                });
                            }
                        }""")
                        await asyncio.sleep(0.5)
                        chunks.append(await frame.inner_text("body"))
                    except Exception:
                        pass
                
                # Progressive scroll loop (scroll down progressively to trigger lazy load / infinite scroll)
                for scroll_idx in range(scroll_loops):
                    try:
                        await frame.evaluate("""async () => {
                            const elements = Array.from(document.querySelectorAll('*'));
                            const scrollables = elements.filter(el => {
                                const style = window.getComputedStyle(el);
                                const isScrollable = style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflow === 'auto' || style.overflow === 'scroll';
                                return isScrollable && el.scrollHeight > el.clientHeight;
                            });
                            if (scrollables.length === 0) {
                                window.scrollTo(0, (window.scrollY || 0) + 400);
                                window.dispatchEvent(new Event('scroll'));
                            } else {
                                scrollables.forEach(el => {
                                    el.scrollTop += 400;
                                    el.dispatchEvent(new Event('scroll'));
                                });
                            }
                        }""")
                        await asyncio.sleep(0.4)
                        
                        if accumulate:
                            try:
                                chunks.append(await frame.inner_text("body"))
                            except Exception:
                                pass
                    except Exception:
                        pass
                
                if accumulate and chunks:
                    text = self._merge_text_chunks(chunks)
                else:
                    text = await frame.inner_text("body")
                    
                # Get debug details about the frame
                try:
                    debug_details = await frame.evaluate("""() => {
                        const elements = Array.from(document.querySelectorAll('*'));
                        const scrollables = elements.filter(el => {
                            const style = window.getComputedStyle(el);
                            const isScrollable = style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflow === 'auto' || style.overflow === 'scroll';
                            return isScrollable && el.scrollHeight > el.clientHeight;
                        });
                        return {
                            element_count: elements.length,
                            body_scrollHeight: document.body ? document.body.scrollHeight : 0,
                            body_clientHeight: document.body ? document.body.clientHeight : 0,
                            doc_scrollHeight: document.documentElement ? document.documentElement.scrollHeight : 0,
                            doc_clientHeight: document.documentElement ? document.documentElement.clientHeight : 0,
                            scrollables: scrollables.map(el => ({
                                tagName: el.tagName,
                                className: el.className,
                                id: el.id,
                                scrollTop: el.scrollTop,
                                scrollHeight: el.scrollHeight,
                                clientHeight: el.clientHeight
                            }))
                        };
                    }""")
                except Exception as de:
                    debug_details = {"error": str(de)}
                    
                frames_info.append({
                    "index": i,
                    "name": frame.name,
                    "url": frame.url,
                    "text_length": len(text),
                    "snippet": text[:1500],
                    "full_text": text,
                    "debug_details": debug_details
                })
            except Exception as e:
                frames_info.append({
                    "index": i,
                    "name": frame.name,
                    "url": frame.url,
                    "error": str(e)
                })
        return frames_info

if __name__ == "__main__":
    import sys
    import json
    
    manager = BrowserSessionManager()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--url":
        if len(sys.argv) < 3:
            print("Please specify a URL: python browser_session_manager.py --url <link>")
            sys.exit(1)
        url = sys.argv[2]
        print(f"Reading page: {url}")
        res = asyncio.run(manager.browse_page(url))
        print(json.dumps(res, indent=2))
    else:
        print("Starting manual session login...", flush=True)
        success = asyncio.run(manager.authenticate())
        if success:
            print("\nSUCCESS! Your session has been saved.")
        else:
            print("\nFAILED. Could not save session.")
