"""Resolve native Chrome profiles and label flattened CDP page contexts safely."""
import asyncio
import json
from pathlib import Path


def available_profiles(root):
    """Read only Local State; listing must never launch Chrome."""
    try:
        state = json.loads((root / "Local State").read_text())
        profile = state.get("profile", {}) if isinstance(state, dict) else {}
        cache = profile.get("info_cache", {}) if isinstance(profile, dict) else {}
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError, AttributeError):
        cache = {}
    return {directory: details for directory, details in cache.items()
            if isinstance(details, dict) and Path(directory).name == directory
            and directory not in (".", "..")}


def resolve_profile(root, requested):
    if not isinstance(requested, str) or not requested.strip():
        raise ValueError("Profile must be a non-empty Chrome profile name or directory.")
    requested = requested.strip()
    profiles = available_profiles(root)
    if requested in profiles:
        return requested
    matches = [d for d, info in profiles.items()
               if str(info.get("name", "")).casefold() == requested.casefold()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError(f"Profile name {requested!r} is ambiguous; use its Chrome profile directory instead.")
    choices = ", ".join(f"{i.get('name', d)} ({d})" for d, i in profiles.items())
    raise ValueError(f"Chrome profile {requested!r} was not found. Available profiles: {choices or 'none found'}.")


async def native_context(page):
    session = await page.context.new_cdp_session(page)
    try:
        info = (await session.send("Target.getTargetInfo"))["targetInfo"]
        context_id = info.get("browserContextId")
        if not context_id:
            raise RuntimeError("Chrome did not expose a native profile context ID.")
        return context_id
    finally:
        await session.detach()


async def _bounded_cleanup(awaitable):
    """Run best-effort cleanup independently, without unbounded cancellation waits."""
    task = asyncio.ensure_future(awaitable)

    def consume_result(done):
        if not done.cancelled():
            done.exception()

    try:
        try:
            await asyncio.wait({task}, timeout=.5)
        except asyncio.CancelledError:
            # Shield the owned cleanup from a caller's cancellation, but bound
            # the extra grace period and always propagate cancellation afterward.
            await asyncio.wait({task}, timeout=.5)
            raise
    finally:
        if not task.done():
            task.cancel()
        task.add_done_callback(consume_result)


async def profile_popup(anchor):
    """Blank popups inherit the opener's native profile, unlike context.new_page()."""
    page = None

    def created(popup_page):
        nonlocal page
        page = popup_page

    # Capture ownership before evaluating: cancellation may interrupt creation
    # after Chrome emits the popup but before expect_popup/value returns it.
    anchor.on("popup", created)
    try:
        async with anchor.expect_popup(timeout=5000) as popup:
            await asyncio.wait_for(anchor.evaluate("window.open('about:blank', '_blank')"), 5)
        page = await popup.value
        if await native_context(page) != await native_context(anchor):
            raise RuntimeError("Chrome opened a tab in a different native profile.")
        return page
    except BaseException:
        if page is not None:
            await _bounded_cleanup(page.close())
        raise
    finally:
        anchor.remove_listener("popup", created)


async def identify_profile(anchor, root):
    """Navigate only our disposable probe, never the user's original tab."""
    probe = await profile_popup(anchor)
    try:
        await probe.goto("chrome://version/", wait_until="domcontentloaded", timeout=5000)
        profile_path = Path((await probe.locator("#profile_path").inner_text(timeout=5000)).strip())
        if profile_path.parent.resolve() != root.resolve():
            raise RuntimeError("CDP browser uses a different Chrome user-data directory.")
        return profile_path.name
    finally:
        try:
            await _bounded_cleanup(probe.close())
        finally:
            # Restore focus changed by the temporary probe, even after close fails.
            await _bounded_cleanup(anchor.bring_to_front())
