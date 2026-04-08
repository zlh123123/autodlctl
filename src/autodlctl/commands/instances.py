from __future__ import annotations

import asyncio
import re
from typing import Any

from autodlctl.constants import (
    NO_CARD_START_LABEL,
    START_SUCCESS_MARKERS,
    STOP_SUCCESS_MARKERS,
)
from autodlctl.page_ops import (
    capture_instance_host_info,
    advance_list_page,
    click_row_action,
    click_row_with_text,
    click_visible_overlay_action,
    copy_running_instance_credentials,
    list_instances,
    wait_for_access_summary,
    wait_for_detail_panel,
    wait_for_row_state,
    wait_for_visible_selectors,
)
from autodlctl.parsing import (
    contains_any,
    extract_container_id,
    filter_instance_summaries,
    limit_instance_summaries,
    normalize_space,
    parse_identity_cell,
    sort_instance_summaries,
    summarize_instance_tables,
)
from autodlctl.runtime import browser_page, save_storage_state


async def run_instance_action(args, labels: tuple[str, ...], action_name: str) -> dict[str, Any]:
    permissions = ["clipboard-read", "clipboard-write"] if action_name == "start" else None
    async with browser_page(
        headless=bool(args.headless),
        timeout_ms=args.timeout_ms,
        storage_state_path=args.storage_state,
        permissions=permissions,
    ) as (_context, page):
        await page.goto(args.url, wait_until="domcontentloaded")
        await wait_for_instance_list_ready(page, timeout_ms=max(3000, args.timeout_ms))
        row_info = await click_row_with_text(page, args.instance)
        row_locator = row_info["row_locator"]
        row_text_before = row_info["row_text"]

        container_id = extract_container_id(row_text_before, args.instance)
        identity = parse_identity_cell(row_text_before)

        if action_name == "stop" and contains_any(row_text_before, STOP_SUCCESS_MARKERS):
            if args.screenshot:
                await page.screenshot(path=args.screenshot, full_page=True)
            return {"success": True, "container_id": container_id}

        if action_name == "start" and getattr(args, "mode", "gpu") == "nocard":
            if "运行中" in row_text_before:
                if args.screenshot:
                    await page.screenshot(path=args.screenshot, full_page=True)
                return {"success": True, "container_id": container_id}
            await click_row_action(page, args.instance, labels)
            menu_click = await click_visible_overlay_action(
                page,
                (NO_CARD_START_LABEL,),
                timeout_ms=max(3000, args.timeout_ms),
            )
            if menu_click is None:
                raise RuntimeError(f"Could not find {NO_CARD_START_LABEL} in the More menu")
        else:
            await click_row_action(page, args.instance, labels)

        if action_name == "detail":
            detail_panel = await wait_for_detail_panel(page, timeout_ms=max(5000, args.timeout_ms))
            if not detail_panel.get("found"):
                raise RuntimeError("Detail panel did not appear")
            if args.screenshot:
                await page.screenshot(path=args.screenshot, full_page=True)
            expected_host_name = None
            if identity.get("site") and identity.get("host"):
                expected_host_name = f"{identity.get('site')} / {identity.get('host')}"
            host_info = await capture_instance_host_info(
                page,
                row_locator,
                timeout_ms=max(5000, args.timeout_ms),
                expected_host_name=expected_host_name,
            )
            return {
                "success": True,
                "container_id": container_id,
                "host_info": host_info,
                "identity": {
                    "site": identity.get("site"),
                    "host": identity.get("host"),
                    "instance_id": identity.get("instance_id") or container_id,
                },
                "detail": detail_panel.get("field_map", {}),
            }

        if action_name == "stop" or "运行中" not in row_text_before:
            confirmation_info = await click_visible_overlay_action(
                page,
                ("确定", "确认"),
                timeout_ms=max(3000, args.timeout_ms),
            )
            if confirmation_info is None:
                raise RuntimeError("Confirmation dialog did not appear or could not be confirmed")

        expected_markers = START_SUCCESS_MARKERS if action_name == "start" else STOP_SUCCESS_MARKERS
        await wait_for_row_state(
            row_locator,
            expected_markers,
            timeout_ms=max(5000, args.timeout_ms),
        )

        if args.screenshot:
            await page.screenshot(path=args.screenshot, full_page=True)
        if action_name == "start":
            await wait_for_access_summary(row_locator, timeout_ms=max(15000, args.timeout_ms))
            credentials = await copy_running_instance_credentials(page, row_locator)
            return {
                "success": True,
                "container_id": container_id,
                "access": {
                    "ssh_command": credentials.get("ssh_command"),
                    "ssh_password": credentials.get("ssh_password"),
                },
            }
        return {"success": True, "container_id": container_id}


async def augment_instances_with_host_info(
    page,
    instances: list[dict[str, Any]],
    timeout_ms: int,
) -> list[dict[str, Any]]:
    for instance in instances:
        container_id = instance.get("container_id")
        if not container_id:
            continue
        row_locator = page.get_by_role("row").filter(has_text=container_id).first
        identity = instance.get("identity") or {}
        expected_host_name = None
        if identity.get("site") and identity.get("host"):
            expected_host_name = f"{identity.get('site')} / {identity.get('host')}"
        try:
            host_info = await capture_instance_host_info(
                page,
                row_locator,
                timeout_ms=timeout_ms,
                expected_host_name=expected_host_name,
            )
        except Exception:
            host_info = None
        if host_info:
            instance["host_info"] = host_info
    return instances


async def wait_for_instance_list_ready(page, timeout_ms: int, settle_ms: int = 5000) -> bool:
    deadline = asyncio.get_running_loop().time() + max(0.5, timeout_ms / 1000)
    empty_seen_at: float | None = None
    settle_seconds = max(0.5, settle_ms / 1000)

    while asyncio.get_running_loop().time() <= deadline:
        try:
            tables = await list_instances(page, max_tables=8)
            if summarize_instance_tables(tables):
                return True

            body_text = normalize_space(tables.get("bodyText"))
            now = asyncio.get_running_loop().time()
            match = re.search(r"共\s*(\d+)\s*条", body_text)
            if match:
                if int(match.group(1)) > 0:
                    return True
                if empty_seen_at is None:
                    empty_seen_at = now
                elif now - empty_seen_at >= settle_seconds:
                    return False
            elif "暂无数据" in body_text:
                if empty_seen_at is None:
                    empty_seen_at = now
                elif now - empty_seen_at >= settle_seconds:
                    return False
        except Exception:
            pass
        await asyncio.sleep(0.25)

    return False


async def collect_all_list_instances(
    page,
    *,
    max_tables: int,
    timeout_ms: int,
    screenshot_path: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    collected_instances: list[dict[str, Any]] = []
    seen_container_ids: set[str] = set()
    page_index = 1
    pagination_warning: str | None = None

    while True:
        tables = await list_instances(page, max_tables=max_tables)
        page_instances = summarize_instance_tables(tables)
        page_instances = await augment_instances_with_host_info(page, page_instances, timeout_ms=max(3000, timeout_ms))

        for instance in page_instances:
            container_id = instance.get("container_id")
            if container_id and container_id in seen_container_ids:
                continue
            if container_id:
                seen_container_ids.add(container_id)
            collected_instances.append(instance)

        if screenshot_path and page_index == 1:
            await page.screenshot(path=screenshot_path, full_page=True)

        try:
            advanced = await advance_list_page(page, timeout_ms=max(3000, timeout_ms))
        except Exception as exc:
            pagination_warning = str(exc)
            break

        if not advanced:
            break

        page_index += 1

    return collected_instances, pagination_warning


async def run_list(
    *,
    url: str,
    headless: bool,
    timeout_ms: int,
    screenshot_path: str | None,
    storage_state_path: str | None,
    max_tables: int,
    query: str | None,
    site: str | None,
    host: str | None,
    gpu_model: str | None,
    gpu_driver: str | None,
    cuda_version: str | None,
    status: str | None,
    min_gpu_free: int | None,
    min_data_disk_expandable_gb: int | None,
    sort_by: str | None,
    sort_order: str,
    limit: int | None,
    save_storage_state_path: str | None = None,
) -> dict[str, Any]:
    async with browser_page(
        headless=headless,
        timeout_ms=timeout_ms,
        storage_state_path=storage_state_path,
    ) as (context, page):
        await page.goto(url, wait_until="domcontentloaded")
        await wait_for_instance_list_ready(page, timeout_ms=max(3000, timeout_ms))
        instances, pagination_warning = await collect_all_list_instances(
            page,
            max_tables=max_tables,
            timeout_ms=timeout_ms,
            screenshot_path=screenshot_path,
        )
        matched_instances = filter_instance_summaries(
            instances,
            query=query,
            site=site,
            host=host,
            gpu_model=gpu_model,
            gpu_driver=gpu_driver,
            cuda_version=cuda_version,
            status=status,
            min_gpu_free=min_gpu_free,
            min_data_disk_expandable_gb=min_data_disk_expandable_gb,
        )
        sorted_instances = sort_instance_summaries(matched_instances, sort_by, sort_order)
        limited_instances = limit_instance_summaries(sorted_instances, limit)
        await save_storage_state(context, save_storage_state_path)
        has_filter = any(
            value not in (None, "")
            for value in (
                query,
                site,
                host,
                gpu_model,
                gpu_driver,
                cuda_version,
                status,
                min_gpu_free,
                min_data_disk_expandable_gb,
                limit,
            )
        )
        return {
            "success": True,
            "count": len(limited_instances),
            "instances": limited_instances,
            **({"pagination_warning": pagination_warning} if pagination_warning else {}),
            "pagination_complete": pagination_warning is None,
            **(
                {
                    "filter": {
                        "query": query,
                        "site": site,
                        "host": host,
                        "gpu_model": gpu_model,
                        "gpu_driver": gpu_driver,
                        "cuda_version": cuda_version,
                        "status": status,
                        "min_gpu_free": min_gpu_free,
                        "min_data_disk_expandable_gb": min_data_disk_expandable_gb,
                        "limit": limit,
                        "matched": len(matched_instances),
                        "returned": len(limited_instances),
                        "total": len(instances),
                    }
                }
                if has_filter
                else {}
            ),
            **({"sort": {"by": sort_by, "order": sort_order}} if sort_by else {}),
        }


async def run_auth(
    *,
    url: str,
    headless: bool,
    pause_seconds: int,
    timeout_ms: int,
    storage_state_path: str | None,
    browser_profile_dir: str,
    save_storage_state_path: str,
) -> dict[str, Any]:
    from autodlctl.parsing import inspect_storage_state_cookie_expiry

    async with browser_page(
        headless=headless,
        timeout_ms=timeout_ms,
        storage_state_path=storage_state_path,
        browser_channel="chrome",
        browser_profile_dir=browser_profile_dir,
    ) as (context, page):
        await page.goto(url, wait_until="domcontentloaded")
        await page.locator("body").wait_for(state="visible")
        await wait_for_visible_selectors(
            page,
            ("input", "button", ".login", "form"),
            timeout_ms=max(3000, timeout_ms),
            required=False,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(1, pause_seconds)
        login_url_markers = ("/login", "/register")
        console_markers = (
            "实例ID /名称",
            "查看详情",
            "开机",
            "关机",
            "SSH登录",
            "快捷工具",
            "释放时间/停机时间",
        )
        settle_seconds = 5
        logged_in_since: float | None = None
        looks_logged_in = False
        while loop.time() < deadline:
            current_url = page.url
            body_text = normalize_space(await page.locator("body").inner_text())
            current_logged_in = not any(marker in current_url for marker in login_url_markers) and any(
                marker in body_text for marker in console_markers
            )
            if current_logged_in:
                looks_logged_in = True
                if logged_in_since is None:
                    logged_in_since = loop.time()
                elif loop.time() - logged_in_since >= settle_seconds:
                    break
            else:
                logged_in_since = None
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(1 if current_logged_in else 3, remaining))
        await save_storage_state(context, save_storage_state_path)
        storage_state_check = inspect_storage_state_cookie_expiry(save_storage_state_path)
        return {
            "success": True,
            "saved_storage_state": save_storage_state_path,
            "detected_logged_in": looks_logged_in,
            "browser_profile_dir": browser_profile_dir,
            "storage_state_check": storage_state_check,
        }
