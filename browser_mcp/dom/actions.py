"""DOM actions engine: element locators, clicks, typing, scrolling, and JS execution."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from playwright.async_api import Page

from browser_mcp.config import DEFAULT_TIMEOUT_MS, DEFAULT_SCREENSHOT_PATH
from browser_mcp.core.utils import is_internal_url, safe_evaluate

logger = logging.getLogger("browser_mcp.dom.actions")


class DOMActions:
    """Dispatches click, fill, scroll, screenshot, and JS execution actions on a Page."""

    @staticmethod
    async def highlight_element(page: Page, selector: str) -> None:
        """Briefly pulse an amber outline on the target element before interaction."""
        try:
            url = getattr(page, "url", "")
            if is_internal_url(url):
                return
            loc = page.locator(selector).first
            if await loc.count() > 0:
                await asyncio.wait_for(
                    loc.evaluate(r"""(el) => {
                        const originalBorder = el.style.border;
                        el.style.border = '3px solid #ff9900';
                        setTimeout(() => {
                            try { el.style.border = originalBorder; } catch(e){}
                        }, 800);
                    }"""),
                    timeout=2.0,
                )
        except Exception:
            pass

    @classmethod
    async def click(cls, page: Page, selector: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> Dict[str, Any]:
        """Click an element, supporting accessibility roles, visible filtering, and fallback dispatch."""
        if not page:
            return {"success": False, "error": "No active page available."}

        url = getattr(page, "url", "")
        if is_internal_url(url):
            return {
                "success": False,
                "error": f"Cannot click element on internal browser page ({url or 'about:blank'}). Switch to a valid web page first.",
            }

        candidates = []
        is_plain_text = not any(char in selector for char in ['#', '.', '[', '>', ':', '='])

        if selector.startswith("role="):
            candidates.append(f"{selector} >> visible=true")
            candidates.append(selector)
        elif is_plain_text:
            candidates.append(f'text="{selector}" >> visible=true')
            candidates.append(f'text="{selector}"')
            candidates.append(selector)
        else:
            candidates.append(selector)
            candidates.append(f"{selector} >> visible=true")

        last_error = None
        for cand in candidates:
            try:
                loc = page.locator(cand).first
                if await loc.count() > 0:
                    await cls.highlight_element(page, cand)
                    try:
                        await loc.click(timeout=min(timeout_ms, 5000))
                        return {
                            "success": True,
                            "selector": cand,
                            "method": "pointer",
                            "timestamp": datetime.now().isoformat(),
                        }
                    except Exception as click_err:
                        logger.info("Pointer click failed on '%s' (%s), trying JS click / container bubble...", cand, click_err)
                        js_clicked = await loc.evaluate(r"""(el) => {
                            const parent = el.closest('button, a, tr, [role="button"], [role="row"], [role="checkbox"], [tabindex]');
                            const target = parent || el;
                            target.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}));
                            target.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window}));
                            target.click();
                            return true;
                        }""")
                        if js_clicked:
                            return {
                                "success": True,
                                "selector": cand,
                                "method": "js_dispatch",
                                "timestamp": datetime.now().isoformat(),
                            }
            except Exception as cand_err:
                last_error = cand_err
                continue

        try:
            await page.click(selector, timeout=timeout_ms)
            return {
                "success": True,
                "selector": selector,
                "method": "direct",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as final_err:
            error_to_report = last_error or final_err
            logger.error("Click error on selector '%s': %s", selector, error_to_report)
            return {"success": False, "error": f"Failed to click element: {error_to_report}"}

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

        url = getattr(page, "url", "")
        if is_internal_url(url):
            return {
                "success": False,
                "error": f"Cannot fill input on internal browser page ({url or 'about:blank'}). Switch to a valid web page first.",
            }

        try:
            await cls.highlight_element(page, selector)
            await asyncio.wait_for(
                page.fill(selector, text, timeout=timeout_ms),
                timeout=(timeout_ms / 1000.0) + 2.0,
            )
            if press_enter:
                await asyncio.wait_for(page.keyboard.press("Enter"), timeout=2.0)

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

        url = getattr(page, "url", "")
        if is_internal_url(url):
            return {"success": False, "error": f"Cannot scroll internal browser page ({url or 'about:blank'})."}

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

            res = await safe_evaluate(page, js_script, arg={
                "direction": direction,
                "amount": amount,
                "selector": selector,
            }, timeout=10.0)

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
    async def evaluate_js(cls, page: Page, script: str, timeout_seconds: float = 30.0) -> Dict[str, Any]:
        """Execute arbitrary JavaScript in active page context."""
        if not page:
            return {"success": False, "error": "No active page available."}

        url = getattr(page, "url", "")
        if is_internal_url(url):
            return {
                "success": False,
                "error": f"Cannot evaluate JavaScript on internal browser page ({url or 'about:blank'}). Switch to a valid web page first.",
            }

        try:
            result = await safe_evaluate(page, script, timeout=timeout_seconds)
            return {
                "success": True,
                "result": result,
                "timestamp": datetime.now().isoformat(),
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": f"evaluate_js timed out after {timeout_seconds}s"}
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
            await asyncio.wait_for(page.screenshot(path=str(target_path)), timeout=15.0)
            return {
                "success": True,
                "path": str(target_path),
                "url": getattr(page, "url", ""),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as error:
            logger.error("Screenshot error: %s", error)
            return {"success": False, "error": f"Failed to take screenshot: {error}"}
