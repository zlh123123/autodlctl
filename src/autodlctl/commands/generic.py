from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autodlctl.models import StepResult
from autodlctl.page_ops import inspect_page, wait_for_visible_selectors
from autodlctl.runtime import browser_page, save_storage_state


def load_steps(raw_steps: str | None, steps_file: str | None) -> list[dict[str, Any]]:
    if raw_steps and steps_file:
        raise ValueError("Use either --steps or --steps-file, not both")
    if steps_file:
        return json.loads(Path(steps_file).read_text(encoding="utf-8"))
    if raw_steps:
        return json.loads(raw_steps)
    raise ValueError("Missing steps: provide --steps or --steps-file")


async def run_steps(
    *,
    url: str,
    steps: list[dict[str, Any]],
    headless: bool,
    timeout_ms: int,
    screenshot_path: str | None,
    storage_state_path: str | None,
    save_storage_state_path: str | None,
) -> dict[str, Any]:
    results: list[StepResult] = []

    async with browser_page(
        headless=headless,
        timeout_ms=timeout_ms,
        storage_state_path=storage_state_path,
    ) as (context, page):
        await page.goto(url, wait_until="domcontentloaded")
        await wait_for_visible_selectors(
            page,
            ("table", "button", "input", ".el-pagination"),
            timeout_ms=max(3000, timeout_ms),
            required=False,
        )

        for index, step in enumerate(steps, start=1):
            op = step.get("op")
            if not op:
                raise ValueError(f"Step {index} is missing op")

            if op == "goto":
                target = step["url"]
                await page.goto(target, wait_until=step.get("wait_until", "domcontentloaded"))
                results.append(StepResult(op=op, ok=True, detail={"url": target}))
            elif op == "click":
                await page.locator(step["selector"]).click()
                results.append(StepResult(op=op, ok=True, detail={"selector": step["selector"]}))
            elif op == "fill":
                await page.locator(step["selector"]).fill(str(step.get("value", "")))
                results.append(StepResult(op=op, ok=True, detail={"selector": step["selector"]}))
            elif op == "press":
                await page.locator(step["selector"]).press(step["key"])
                results.append(
                    StepResult(
                        op=op,
                        ok=True,
                        detail={"selector": step["selector"], "key": step["key"]},
                    )
                )
            elif op == "wait_for":
                if "selector" in step:
                    await page.locator(step["selector"]).wait_for(state=step.get("state", "visible"))
                    results.append(StepResult(op=op, ok=True, detail={"selector": step["selector"]}))
                else:
                    await page.wait_for_timeout(int(step.get("ms", 1000)))
                    results.append(
                        StepResult(op=op, ok=True, detail={"ms": int(step.get("ms", 1000))})
                    )
            elif op == "text":
                text = await page.locator(step["selector"]).inner_text()
                results.append(
                    StepResult(op=op, ok=True, detail={"selector": step["selector"], "text": text})
                )
            elif op == "title":
                results.append(StepResult(op=op, ok=True, detail={"title": await page.title()}))
            elif op == "screenshot":
                path = step.get("path") or screenshot_path or "browser-shot.png"
                await page.screenshot(path=path, full_page=bool(step.get("full_page", True)))
                results.append(StepResult(op=op, ok=True, detail={"path": path}))
            else:
                raise ValueError(f"Unsupported op: {op}")

        if screenshot_path and not any(item.op == "screenshot" for item in results):
            await page.screenshot(path=screenshot_path, full_page=True)

        await save_storage_state(context, save_storage_state_path)
        return {
            "success": True,
            "url": page.url,
            "title": await page.title(),
            "results": [item.__dict__ for item in results],
            "screenshot": screenshot_path,
        }


async def open_and_inspect(
    *,
    url: str,
    headless: bool,
    timeout_ms: int,
    screenshot_path: str | None,
    storage_state_path: str | None,
    max_items: int,
    save_storage_state_path: str | None = None,
) -> dict[str, Any]:
    async with browser_page(
        headless=headless,
        timeout_ms=timeout_ms,
        storage_state_path=storage_state_path,
    ) as (context, page):
        await page.goto(url, wait_until="domcontentloaded")
        await wait_for_visible_selectors(
            page,
            ("table", "button", "input", ".el-pagination"),
            timeout_ms=max(3000, timeout_ms),
            required=False,
        )
        inspection = await inspect_page(page, max_items=max_items)
        if screenshot_path:
            await page.screenshot(path=screenshot_path, full_page=True)
        await save_storage_state(context, save_storage_state_path)
        return {
            "success": True,
            "url": page.url,
            "title": await page.title(),
            "inspection": inspection,
            "screenshot": screenshot_path,
        }


async def run_status(args) -> dict[str, Any]:
    return await open_and_inspect(
        url=args.url,
        headless=bool(args.headless),
        timeout_ms=args.timeout_ms,
        screenshot_path=args.screenshot,
        storage_state_path=args.storage_state,
        max_items=args.max_items,
        save_storage_state_path=args.save_storage_state,
    )
