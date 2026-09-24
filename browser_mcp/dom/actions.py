"""DOM actions engine: element locators, clicks, typing, scrolling, and JS execution."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from playwright.async_api import Page

from browser_mcp.config import DEFAULT_TIMEOUT_MS, DEFAULT_SCREENSHOT_PATH

logger = logging.getLogger("browser_mcp.dom.actions")


class DOMActions:
    """Dispatches click, fill, scroll, screenshot, and JS execution actions on a Page."""

    @staticmethod
    async def highlight_element(page: Page, selector: str) -> None:
        """Briefly pulse an amber outline on the target element before interaction."""
        try:
            await page.evaluate(r"""(sel) => {
                let el = document.querySelector(sel);
                if (!el && sel.startsWith('text=')) {
                    const text = sel.slice(5).replace(/^["']|["']$/g, '');
                    const all = Array.from(document.querySelectorAll('button, a, input, div, span'));
                    el = all.find(e => e.innerText && e.innerText.trim() === text);
                }
                if (el) {
                    const originalBorder = el.style.border;
                    el.style.border = '3px solid #ff9900';
                    setTimeout(() => {
                        try { el.style.border = originalBorder; } catch(e){}
                    }, 800);
                }
            }""", selector)
        except Exception:
            pass

    @classmethod
    async def click(cls, page: Page, selector: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> Dict[str, Any]:
        """Click an element, falling back from CSS selector to text locator if needed."""
        if not page:
            return {"success": False, "error": "No active page available."}

        try:
            resolved_sel = selector
            await cls.highlight_element(page, resolved_sel)
            try:
                await page.click(resolved_sel, timeout=timeout_ms)
            except Exception as direct_err:
                # If direct click fails and selector doesn't look like standard CSS, fallback to text locator
                if not any(char in selector for char in ['#', '.', '[', '>', ':', '=']):
                    text_sel = f'text="{selector}"'
                    await cls.highlight_element(page, text_sel)
                    await page.click(text_sel, timeout=timeout_ms)
                    resolved_sel = text_sel
                else:
                    raise direct_err

            return {
                "success": True,
                "selector": resolved_sel,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as error:
            logger.error("Click error on selector '%s': %s", selector, error)
            return {"success": False, "error": f"Failed to click element: {error}"}

    @classmethod
    async def fill(
        cls,
        page: Page,
        selector: str,
        text: str,
        press_enter: bool = False,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> Dict[str, Any]:
        """Fill an input field with text and optionally press Enter."""
        if not page:
            return {"success": False, "error": "No active page available."}

        try:
            await cls.highlight_element(page, selector)
            await page.fill(selector, text, timeout=timeout_ms)
            if press_enter:
                await page.keyboard.press("Enter")

            return {
                "success": True,
                "selector": selector,
                "text_length": len(text),
                "pressed_enter": press_enter,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as error:
            logger.error("Fill error on selector '%s': %s", selector, error)
            return {"success": False, "error": f"Failed to fill input: {error}"}

    @classmethod
    async def scroll(
        cls,
        page: Page,
        direction: str = "down",
        amount: int = 500,
        selector: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Scroll active window or nested virtualized container (Teams, Jira, Slack)."""
        if not page:
            return {"success": False, "error": "No active page available."}

        try:
            js_script = r"""(arg) => {
                let targets = [];
                if (arg.selector) {
                    const el = document.querySelector(arg.selector);
                    if (el) targets = [el];
                    else return "selector_not_found";
                } else {
                    const divs = Array.from(document.querySelectorAll('div, section, ul, ol'));
                    for (const d of divs) {
                        const style = window.getComputedStyle(d);
                        if (['auto', 'scroll'].includes(style.overflowY) && d.scrollHeight > d.clientHeight) {
                            targets.push(d);
                        }
                    }
                }

                const delta = (arg.direction === 'up' ? -arg.amount : arg.amount);
                let scrolledCount = 0;
                for (const t of targets) {
                    t.scrollBy({ top: delta, behavior: 'smooth' });
                    scrolledCount++;
                }

                if (scrolledCount === 0 || !arg.selector) {
                    window.scrollBy({ top: delta, behavior: 'smooth' });
                }

                return scrolledCount > 0 ? `scrolled_${scrolledCount}_containers` : 'scrolled_window';
            }"""

            res = await page.evaluate(js_script, {
                "direction": direction,
                "amount": amount,
                "selector": selector,
            })

            if res == "selector_not_found":
                return {"success": False, "error": f"Scroll target '{selector}' was not found in the DOM."}

            return {
                "success": True,
                "direction": direction,
                "amount": amount,
                "selector": selector,
                "scroll_mode": res,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as error:
            logger.error("Scroll error: %s", error)
            return {"success": False, "error": f"Failed to scroll page: {error}"}

    @classmethod
    async def evaluate_js(cls, page: Page, script: str) -> Dict[str, Any]:
        """Execute arbitrary JavaScript in active page context."""
        if not page:
            return {"success": False, "error": "No active page available."}

        try:
            result = await page.evaluate(script)
            return {
                "success": True,
                "result": result,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as error:
            logger.error("evaluate_js error: %s", error)
            return {"success": False, "error": f"Failed to evaluate JS: {error}"}

    @classmethod
    async def take_screenshot(cls, page: Page, output_path: Optional[str] = None) -> Dict[str, Any]:
        """Capture screenshot and save to disk."""
        if not page:
            return {"success": False, "error": "No active page available."}

        try:
            target_path = Path(output_path).resolve() if output_path else DEFAULT_SCREENSHOT_PATH
            target_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(target_path))
            return {
                "success": True,
                "path": str(target_path),
                "url": page.url,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as error:
            logger.error("Screenshot error: %s", error)
            return {"success": False, "error": f"Failed to take screenshot: {error}"}
