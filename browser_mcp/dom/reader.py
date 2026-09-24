"""DOM perception engine: content extraction, noise pruning, outlines, and links."""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from playwright.async_api import Page

logger = logging.getLogger("browser_mcp.dom.reader")


class DOMReader:
    """Extracts clean, noise-pruned content from Playwright pages."""

    @staticmethod
    async def browse(
        page: Page,
        url: Optional[str] = None,
        wait_until: str = "domcontentloaded",
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

            title = await page.title()
            current_url = page.url
            content = ""

            for attempt in range(2):
                try:
                    if mode == "outline":
                        headings = await page.evaluate(r"""() => {
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
                        links = await page.evaluate(r"""(sel) => {
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
                        }""", selector)
                        link_lines = [f"- [{l['text']}]({l['href']})" for l in links]
                        content = "\n".join(link_lines) if link_lines else "No links found."

                    else:
                        # mode == "content": Clean DOM reading with boilerplate scrubbing
                        markdown = await page.evaluate(r"""(sel) => {
                            const root = sel ? document.querySelector(sel) : (document.querySelector('main, article, [role="main"]') || document.body);
                            if (!root) return "";

                            const clone = root.cloneNode(true);

                            // Aggressive noise pruning: headers, navs, mega-menus, footers, modals, tracking
                            const noiseSelectors = [
                                'script', 'style', 'noscript', 'svg', 'iframe',
                                'header', 'footer', 'nav',
                                '.cmp-experiencefragment--header', '#header-container',
                                '.cmp-experiencefragment--footer', '#footer-container',
                                '.mega-menu', '.desktop-nav', '.mobile-nav', '.global-nav',
                                '.modal', '.dialog', '[role="dialog"]', '[role="alertdialog"]',
                                '.cookie-banner', '.banner-notice', '[aria-hidden="true"]',
                                '.off-the-clock-popup', '.user-menu-dropdown', '.quick-links-dropdown'
                            ];
                            
                            noiseSelectors.forEach(s => {
                                clone.querySelectorAll(s).forEach(el => el.remove());
                            });

                            function elementToMarkdown(element) {
                                let text = "";
                                for (const child of element.childNodes) {
                                    if (child.nodeType === Node.TEXT_NODE) {
                                        const val = child.nodeValue.replace(/\s+/g, ' ');
                                        text += val;
                                    } else if (child.nodeType === Node.ELEMENT_NODE) {
                                        const tag = child.tagName.toLowerCase();
                                        const style = window.getComputedStyle ? window.getComputedStyle(child) : null;
                                        if (style && (style.display === 'none' || style.visibility === 'hidden')) {
                                            continue;
                                        }

                                        if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tag)) {
                                            const lvl = parseInt(tag[1]);
                                            text += '\n\n' + '#'.repeat(lvl) + ' ' + child.innerText.trim() + '\n\n';
                                        } else if (tag === 'p') {
                                            text += '\n\n' + elementToMarkdown(child).trim() + '\n\n';
                                        } else if (tag === 'br') {
                                            text += '\n';
                                        } else if (['ul', 'ol'].includes(tag)) {
                                            text += '\n' + elementToMarkdown(child) + '\n';
                                        } else if (tag === 'li') {
                                            text += '\n- ' + elementToMarkdown(child).trim();
                                        } else if (tag === 'a') {
                                            const href = child.getAttribute('href');
                                            const linkText = elementToMarkdown(child).trim();
                                            if (href && linkText) {
                                                text += ` [${linkText}](${href}) `;
                                            } else {
                                                text += linkText;
                                            }
                                        } else if (['strong', 'b'].includes(tag)) {
                                            text += ' **' + elementToMarkdown(child).trim() + '** ';
                                        } else if (['em', 'i'].includes(tag)) {
                                            text += ' *' + elementToMarkdown(child).trim() + '* ';
                                        } else if (tag === 'code') {
                                            text += ' `' + child.innerText + '` ';
                                        } else if (tag === 'pre') {
                                            text += '\n```\n' + child.innerText + '\n```\n';
                                        } else if (tag === 'table') {
                                            text += '\n\n[Table content omitted]\n\n';
                                        } else {
                                            text += elementToMarkdown(child);
                                        }
                                    }
                                }
                                return text;
                            }

                            const rawMarkdown = elementToMarkdown(clone);
                            return rawMarkdown
                                .replace(/[ \t]+/g, ' ')
                                .replace(/\n{3,}/g, '\n\n')
                                .trim();
                        }""", selector)

                        content = markdown if markdown else "No readable text content found."
                        if len(content) > max_length:
                            content = (
                                content[:max_length]
                                + f"\n\n... [Content truncated at {max_length} characters. Use selector or outline mode to inspect specific sections.]"
                            )

                    title = await page.title()
                    current_url = page.url
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
