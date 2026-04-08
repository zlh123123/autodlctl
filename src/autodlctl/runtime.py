from __future__ import annotations

import json
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterable


_BROWSER_CHECK_DONE = False


async def safe_close_playwright_resources(context, browser=None) -> None:
    for closer in (context.close, getattr(browser, "close", None)):
        if closer is None:
            continue
        try:
            await closer()
        except Exception:
            pass


def ensure_browser_installed(quiet: bool = False) -> None:
    """Ensure Playwright Chromium is available before launching the browser."""

    global _BROWSER_CHECK_DONE
    if _BROWSER_CHECK_DONE:
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright 未安装，请先执行: pip install playwright && playwright install chromium"
        ) from exc

    with sync_playwright() as playwright:
        chromium_path = Path(playwright.chromium.executable_path)
        if chromium_path.is_file():
            _BROWSER_CHECK_DONE = True
            return

    if not quiet:
        print("Chromium 未安装，正在自动安装 Playwright 浏览器...")

    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
    except subprocess.CalledProcessError:
        if not quiet:
            print("浏览器自动安装失败，请手动执行: playwright install chromium")
        raise SystemExit(1)
    except KeyboardInterrupt:
        if not quiet:
            print("浏览器安装已取消")
        raise SystemExit(1)

    if not quiet:
        print("Chromium 安装完成")
    _BROWSER_CHECK_DONE = True


async def save_storage_state(context, save_storage_state_path: str | None) -> None:
    if not save_storage_state_path:
        return
    Path(save_storage_state_path).parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=save_storage_state_path)


async def load_storage_state(context, storage_state_path: str | None) -> None:
    if not storage_state_path:
        return

    path = Path(storage_state_path)
    if not path.is_file():
        return

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Could not parse storage state JSON: {storage_state_path}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Storage state file is not a JSON object: {storage_state_path}")

    cookies = payload.get("cookies") or []
    if cookies:
        await context.add_cookies(cookies)

    origin_storage: dict[str, dict[str, Any]] = {}
    for origin_entry in payload.get("origins") or []:
        if not isinstance(origin_entry, dict):
            continue

        origin = origin_entry.get("origin")
        local_storage = origin_entry.get("localStorage") or []
        if not origin or not local_storage:
            continue

        entries: dict[str, Any] = {}
        for item in local_storage:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            entries[str(name)] = item.get("value")

        if entries:
            origin_storage[str(origin)] = entries

    if origin_storage:
        await context.add_init_script(
            f"""
(() => {{
  const storageState = {json.dumps(origin_storage)};
  const entries = storageState[window.location.origin];
  if (!entries) {{
    return;
  }}
  for (const [name, value] of Object.entries(entries)) {{
    window.localStorage.setItem(name, value);
  }}
}})();
"""
        )


@asynccontextmanager
async def browser_page(
    *,
    headless: bool,
    timeout_ms: int,
    storage_state_path: str | None = None,
    permissions: Iterable[str] | None = None,
    browser_channel: str | None = None,
    browser_profile_dir: str | None = None,
):
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        launch_kwargs: dict[str, object] = {"headless": headless}
        if browser_channel:
            launch_kwargs["channel"] = browser_channel
        context_kwargs = {"viewport": {"width": 1440, "height": 900}}
        if storage_state_path and not browser_profile_dir:
            context_kwargs["storage_state"] = storage_state_path

        if browser_profile_dir:
            profile_path = Path(browser_profile_dir)
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                context = await playwright.chromium.launch_persistent_context(
                    str(profile_path),
                    **launch_kwargs,
                    **context_kwargs,
                )
            except Exception:
                if not browser_channel:
                    raise
                context = await playwright.chromium.launch_persistent_context(
                    str(profile_path),
                    headless=headless,
                    **context_kwargs,
                )
            browser = context.browser
        else:
            try:
                browser = await playwright.chromium.launch(**launch_kwargs)
            except Exception:
                if not browser_channel:
                    raise
                browser = await playwright.chromium.launch(headless=headless)
            context = await browser.new_context(**context_kwargs)

        if permissions:
            await context.grant_permissions(list(permissions))
        if browser_profile_dir:
            await load_storage_state(context, storage_state_path)
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            yield context, page
        finally:
            await safe_close_playwright_resources(context, browser)
