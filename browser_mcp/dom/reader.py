"""DOM perception engine: content extraction, noise pruning, outlines, and links."""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from playwright.async_api import Page

from browser_mcp.core.utils import is_internal_url, safe_get_title, safe_evaluate

logger = logging.getLogger("browser_mcp.dom.reader")


class DOMReader:
    """Extracts clean, noise-pruned content from Playwright pages."""

    @staticmethod
    async def browse(
        page: Page,
        url: Optional[str] = None,
        wait_until: str = "domcontentloaded",
        wait_for_selector: Optional[str] = None,
        wait_for_timeout_ms: int = 10000,
        selector: Optional[str] = None,
        mode: str = "content",
        max_length: int = 25000,
    ) -> Dict[str, Any]:
        """Navigate to or inspect page, returning noise-pruned markdown or structural outlines."""
        if not page:
            return {"success": False, "error": "No active page available."}

        try:
            if url and url != page.url:
                await page.goto(url, wait_until=wait_until, timeout=45000)

            current_url = getattr(page, "url", "") or ""
            if is_internal_url(current_url) or not current_url:
                title = await safe_get_title(page)
                return {
                    "success": True,
                    "url": current_url,
                    "title": title,
                    "mode": mode,
                    "selector": selector,
                    "content": f"Browser internal page: {current_url or 'about:blank'}. No DOM content to extract.",
                    "timestamp": datetime.now().isoformat(),
                }

            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=wait_for_timeout_ms)
                except Exception as wait_err:
                    logger.warning("wait_for_selector '%s' timed out after %sms: %s", wait_for_selector, wait_for_timeout_ms, wait_err)

            title = await safe_get_title(page)
            content = ""

            for attempt in range(2):
                try:
                    if mode == "outline":
                        headings = await safe_evaluate(page, r"""() => {
                            const nodes = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6'));
                            return nodes
                                .filter(n => n.innerText && n.innerText.trim().length > 0 && n.offsetParent !== null)
                                .map(n => ({
                                     level: parseInt(n.tagName.substring(1)),
                                     text: n.innerText.trim().replace(/\s+/g, ' ')
                                }));
                        }""")
                        outline_lines = [
                            f"{'  ' * (h['level'] - 1)}- {'#' * h['level']} {h['text']}"
                            for h in headings
                        ]
                        content = "\n".join(outline_lines) if outline_lines else "No visible headings found."

                    elif mode == "links":
                        links = await safe_evaluate(page, r"""(sel) => {
                            const root = sel ? document.querySelector(sel) : document.body;
                            if (!root) return [];
                            const anchors = Array.from(root.querySelectorAll('a[href]'));
                            const seen = new Set();
                            const results = [];
                            for (const a of anchors) {
                                const href = a.href;
                                const text = a.innerText.trim().replace(/\s+/g, ' ') || a.getAttribute('aria-label') || '';
                                if (href && !href.startsWith('javascript:') && !seen.has(href)) {
                                    seen.add(href);
                                    results.push({ text: text || 'Link', href: href });
                                }
                            }
                            return results;
                        }""", arg=selector, timeout=15.0)
                        link_lines = [f"- [{l['text']}]({l['href']})" for l in links]
                        content = "\n".join(link_lines) if link_lines else "No links found."

                    elif mode == "accessibility":
                        try:
                            if selector:
                                content = await asyncio.wait_for(page.locator(selector).aria_snapshot(), timeout=10.0)
                            else:
                                content = await asyncio.wait_for(page.aria_snapshot(), timeout=10.0)
                            if not content or not content.strip():
                                content = "Empty accessibility tree."
                        except Exception as ax_err:
                            logger.warning("aria_snapshot error: %s", ax_err)
                            content = f"Failed to capture accessibility snapshot: {ax_err}"

                    else:
                        # mode == "content": Clean DOM reading with custom Web Component & Shadow DOM support
                        markdown = await safe_evaluate(page, r"""(sel) => {
                            const root = sel ? document.querySelector(sel) : (document.querySelector('main, article, [role="main"]') || document.body);
                            if (!root) return "";

                            const noiseSelectors = [
                                'script', 'style', 'noscript', 'svg', 'iframe',
                                'header', 'footer', 'nav',
                                '.cmp-experiencefragment--header', '#header-container',
                                '.cmp-experiencefragment--footer', '#footer-container',
                                '.mega-menu', '.desktop-nav', '.mobile-nav', '.global-nav',
                                '.cookie-banner', '.banner-notice',
                                '.off-the-clock-popup', '.user-menu-dropdown', '.quick-links-dropdown'
                            ];

                            function isHidden(el) {
                                if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
                                if (el.getAttribute('aria-hidden') === 'true') return true;
                                const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
                                if (style && (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0')) return true;
                                return false;
                            }

                            function isNoise(el) {
                                if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
                                for (const s of noiseSelectors) {
                                    if (el.matches && el.matches(s)) return true;
                                }
                                return false;
                            }

                            function nodeToMarkdown(node) {
                                if (!node) return "";
                                if (node.nodeType === Node.TEXT_NODE) {
                                    return node.nodeValue.replace(/\s+/g, ' ');
                                }
                                if (node.nodeType !== Node.ELEMENT_NODE) return "";
                                if (isHidden(node) || isNoise(node)) return "";

                                const tag = node.tagName.toLowerCase();

                                if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tag)) {
                                    const lvl = parseInt(tag[1]);
                                    return '\n\n' + '#'.repeat(lvl) + ' ' + (node.innerText || node.textContent).trim() + '\n\n';
                                }
                                if (tag === 'p') {
                                    let inner = "";
                                    for (const child of node.childNodes) inner += nodeToMarkdown(child);
                                    return '\n\n' + inner.trim() + '\n\n';
                                }
                                if (tag === 'br') return '\n';
                                if (['ul', 'ol'].includes(tag)) {
                                    let inner = "";
                                    for (const child of node.childNodes) inner += nodeToMarkdown(child);
                                    return '\n' + inner + '\n';
                                }
                                if (tag === 'li') {
                                    let inner = "";
                                    for (const child of node.childNodes) inner += nodeToMarkdown(child);
                                    return '\n- ' + inner.trim();
                                }
                                if (tag === 'a') {
                                    const href = node.getAttribute('href');
                                    let inner = "";
                                    for (const child of node.childNodes) inner += nodeToMarkdown(child);
                                    inner = inner.trim();
                                    return (href && inner) ? (' [' + inner + '](' + href + ') ') : inner;
                                }
                                if (['strong', 'b'].includes(tag)) {
                                    let inner = "";
                                    for (const child of node.childNodes) inner += nodeToMarkdown(child);
                                    return ' **' + inner.trim() + '** ';
                                }
                                if (['em', 'i'].includes(tag)) {
                                    let inner = "";
                                    for (const child of node.childNodes) inner += nodeToMarkdown(child);
                                    return ' *' + inner.trim() + '* ';
                                }
                                if (tag === 'code') {
                                    return ' `' + (node.innerText || node.textContent).trim() + '` ';
                                }
                                if (tag === 'pre') {
                                    return '\n```\n' + (node.innerText || node.textContent).trim() + '\n```\n';
                                }
                                if (tag === 'table') {
                                    const rows = Array.from(node.querySelectorAll('tr')).map(r => 
                                        Array.from(r.querySelectorAll('th, td')).map(c => (c.innerText || c.textContent).trim()).join(' | ')
                                    ).filter(r => r.length > 0);
                                    return rows.length > 0 ? ('\n\n| ' + rows.join(' |\n| ') + ' |\n\n') : '';
                                }

                                const isBlock = ['div', 'section', 'article', 'main', 'aside'].includes(tag) || tag.includes('-');
                                let childrenText = "";
                                if (node.shadowRoot) {
                                    for (const child of node.shadowRoot.childNodes) childrenText += nodeToMarkdown(child);
                                }
                                for (const child of node.childNodes) {
                                    childrenText += nodeToMarkdown(child);
                                }

                                if (isBlock && childrenText.trim().length > 0) {
                                    return '\n' + childrenText + '\n';
                                }
                                return childrenText;
                            }

                            const raw = nodeToMarkdown(root);
                            return raw.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
                        }""", arg=selector, timeout=30.0)

                        content = markdown if markdown else "No readable text content found."
                        if len(content) > max_length:
                            content = (
                                content[:max_length]
                                + f"\n\n... [Content truncated at {max_length} characters. Use selector or outline mode to inspect specific sections.]"
                            )

                    title = await safe_get_title(page)
                    current_url = getattr(page, "url", "")
                    break

                except Exception as eval_err:
                    if attempt == 0 and "Execution context was destroyed" in str(eval_err):
                        logger.info("Execution context destroyed during navigation redirect; waiting 1.5s...")
                        await asyncio.sleep(1.5)
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=10000)
                        except Exception:
                            pass
                        continue
                    raise eval_err

            return {
                "success": True,
                "url": current_url,
                "title": title,
                "mode": mode,
                "selector": selector,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as error:
            logger.error("Failed to browse page: %s", error)
            return {"success": False, "error": f"Failed to browse page: {error}"}
