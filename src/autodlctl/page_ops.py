from __future__ import annotations

import asyncio
from typing import Any

from autodlctl.constants import DETAIL_FIELD_KEY_MAP
from autodlctl.parsing import (
    extract_start_access_summary,
    normalize_cost_value,
    normalize_host_hover_info,
    normalize_space,
    stable_key,
    strip_markers,
)


async def read_clipboard_text(page) -> str:
    return await page.evaluate("navigator.clipboard.readText()")


async def copy_running_instance_credentials(page, row_locator) -> dict[str, Any]:
    await page.bring_to_front()
    login_sections = row_locator.locator(".login")
    if await login_sections.count() < 2:
        raise RuntimeError("Could not find SSH command/password copy controls")

    credentials: dict[str, str] = {}
    field_names = ("ssh_command", "ssh_password")
    for index, field_name in enumerate(field_names):
        section = login_sections.nth(index)
        copy_icon = section.locator(".icon-fuzhi").first
        if await copy_icon.count() == 0:
            raise RuntimeError(f"Could not find copy icon for {field_name}")
        await copy_icon.click()
        await page.wait_for_timeout(300)
        clipboard_text = (await read_clipboard_text(page)).strip()
        if not clipboard_text:
            raise RuntimeError(f"Clipboard was empty after copying {field_name}")
        credentials[field_name] = clipboard_text

    return credentials


async def wait_for_access_summary(row_locator, timeout_ms: int) -> dict[str, Any] | None:
    deadline = asyncio.get_running_loop().time() + max(0.5, timeout_ms / 1000)
    last_text = None
    while asyncio.get_running_loop().time() <= deadline:
        try:
            last_text = normalize_space(await row_locator.inner_text())
            summary = extract_start_access_summary(last_text)
            if summary is not None:
                return summary
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return extract_start_access_summary(last_text)


async def click_first_match(page, labels: tuple[str, ...]) -> dict[str, Any]:
    for label in labels:
        candidates = [
            page.get_by_role("button", name=label),
            page.get_by_role("link", name=label),
            page.get_by_text(label, exact=False),
            page.locator(f"text={label}"),
        ]
        for locator in candidates:
            try:
                if await locator.count() == 0:
                    continue
                await locator.first.click()
                return {"matched_label": label, "strategy": str(locator)}
            except Exception:
                continue
    raise RuntimeError(f"Unable to find a clickable control matching any of: {', '.join(labels)}")


async def click_row_with_text(page, needle: str) -> dict[str, Any]:
    rows = page.get_by_role("row")
    row_count = await rows.count()
    for index in range(row_count):
        row = rows.nth(index)
        text = normalize_space(await row.inner_text())
        if needle in text:
            try:
                await row.click()
            except Exception:
                pass
            return {"row_index": index, "row_text": text}
    raise RuntimeError(f"Could not find a row containing: {needle}")


async def click_row_action(page, needle: str, labels: tuple[str, ...]) -> dict[str, Any]:
    rows = page.get_by_role("row")
    row_count = await rows.count()
    for index in range(row_count):
        row = rows.nth(index)
        text = normalize_space(await row.inner_text())
        if needle not in text:
            continue

        for label in labels:
            candidates = [
                row.get_by_role("button", name=label, exact=True),
                row.get_by_role("link", name=label, exact=True),
                row.get_by_text(label, exact=True),
                row.locator(f"text={label}"),
            ]
            for locator in candidates:
                try:
                    if await locator.count() == 0:
                        continue
                    await locator.first.click()
                    return {
                        "row_index": index,
                        "row_text": text,
                        "matched_label": label,
                        "strategy": str(locator),
                    }
                except Exception:
                    continue

    raise RuntimeError(
        f"Could not find an action matching any of {labels} in row containing: {needle}"
    )


async def click_visible_overlay_action(
    page,
    labels: tuple[str, ...],
    timeout_ms: int = 5000,
) -> dict[str, Any] | None:
    overlay_selectors = (
        ".el-message-box",
        ".el-dialog",
        ".el-drawer",
        "[role='dialog']",
        ".el-popper[data-popper-placement]",
    )

    deadline = asyncio.get_running_loop().time() + max(0.5, timeout_ms / 1000)
    while asyncio.get_running_loop().time() <= deadline:
        for selector in overlay_selectors:
            try:
                overlays = page.locator(selector)
                count = await overlays.count()
                for index in range(count):
                    overlay = overlays.nth(index)
                    if not await overlay.is_visible():
                        continue
                    for label in labels:
                        candidates = [
                            overlay.get_by_role("button", name=label, exact=True),
                            overlay.get_by_role("link", name=label, exact=True),
                            overlay.get_by_text(label, exact=True),
                            overlay.locator(f"text={label}"),
                        ]
                        for locator in candidates:
                            try:
                                if await locator.count() == 0:
                                    continue
                                await locator.first.click()
                                return {
                                    "selector": selector,
                                    "index": index,
                                    "matched_label": label,
                                    "strategy": str(locator),
                                }
                            except Exception:
                                continue
            except Exception:
                continue
        await page.wait_for_timeout(250)

    return None


async def wait_for_row_state(
    row_locator,
    markers: tuple[str, ...],
    timeout_ms: int,
) -> str:
    deadline = asyncio.get_running_loop().time() + max(0.5, timeout_ms / 1000)
    last_text = None
    while asyncio.get_running_loop().time() <= deadline:
        try:
            last_text = normalize_space(await row_locator.inner_text())
            if any(marker in last_text for marker in markers):
                return last_text
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError(f"Row state did not reach any of {markers}; last row text: {last_text or ''}")


async def wait_for_detail_panel(page, timeout_ms: int) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + max(0.5, timeout_ms / 1000)
    last_panel: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() <= deadline:
        try:
            last_panel = await capture_detail_panel(page)
            if last_panel.get("found"):
                return last_panel
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return last_panel or {"found": False}


async def capture_instance_host_tooltip(page) -> dict[str, Any]:
    tooltip_selectors = [
        ".instance-popper[role='tooltip']",
        ".instance-popper",
        ".el-popper[role='tooltip']",
        ".el-popover[role='tooltip']",
    ]

    candidates: list[dict[str, Any]] = []
    for selector in tooltip_selectors:
        try:
            locator = page.locator(selector)
            count = await locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                if not await candidate.is_visible():
                    continue
                payload = await candidate.evaluate(
                    r"""
                    (el) => {
                        const normalize = (text) => (text || '').trim().replace(/\s+/g, ' ');
                        const extractFields = (root) => {
                            const fields = [];
                            for (const item of root.querySelectorAll('.item')) {
                                const labelEl = item.querySelector('.label, .title');
                                const label = labelEl ? normalize(labelEl.innerText || labelEl.textContent) : '';
                                let value = '';
                                for (const child of Array.from(item.children)) {
                                    if (child === labelEl) {
                                        continue;
                                    }
                                    const childText = normalize(child.innerText || child.textContent);
                                    if (childText) {
                                        value = value ? `${value} ${childText}` : childText;
                                    }
                                }
                                const itemText = normalize(item.innerText || item.textContent);
                                fields.push({
                                    label: label || null,
                                    value: value || (label ? normalize(itemText.replace(label, '')) : itemText),
                                    text: itemText,
                                });
                            }
                            return fields;
                        };

                        return {
                            text: normalize(el.innerText || el.textContent),
                            fields: extractFields(el),
                            html: el.outerHTML,
                            ariaLabel: el.getAttribute('aria-label') || null,
                            role: el.getAttribute('role') || null,
                            className: el.className || null,
                        };
                    }
                    """
                )
                payload["selector"] = selector
                payload["index"] = index
                candidates.append(payload)
        except Exception:
            continue

    if not candidates:
        return {"found": False}

    def score(candidate: dict[str, Any]) -> float:
        text = candidate.get("text", "") or ""
        keyword_hits = 1 if "主机名称" in text else 0
        field_count = len(candidate.get("fields", []))
        return keyword_hits * 10 + field_count * 2 + min(len(text), 4000) / 4000

    best = max(candidates, key=score)
    host_info = normalize_host_hover_info(best.get("fields", []) or [])
    return {
        "found": True,
        "selector": best.get("selector"),
        "index": best.get("index"),
        "text": normalize_space(best.get("text", "")),
        "host_info": host_info,
    }


async def wait_for_instance_host_tooltip(page, timeout_ms: int) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + max(0.5, timeout_ms / 1000)
    last_tooltip: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() <= deadline:
        try:
            last_tooltip = await capture_instance_host_tooltip(page)
            if last_tooltip.get("found"):
                return last_tooltip
        except Exception:
            pass
        await asyncio.sleep(0.25)
    return last_tooltip or {"found": False}


async def capture_instance_host_info(
    page,
    row_locator,
    timeout_ms: int = 5000,
    expected_host_name: str | None = None,
) -> dict[str, Any] | None:
    host_locator = row_locator.locator(".region").first
    if await host_locator.count() == 0:
        return None

    expected_normalized = normalize_space(expected_host_name)
    attempts = 3
    try:
        await row_locator.scroll_into_view_if_needed()
    except Exception:
        pass

    last_host_info: dict[str, Any] | None = None
    for _ in range(attempts):
        await host_locator.hover()
        tooltip = await wait_for_instance_host_tooltip(page, timeout_ms)
        last_host_info = tooltip.get("host_info") if tooltip.get("found") else None

        if last_host_info and expected_normalized:
            actual_host_name = normalize_space(last_host_info.get("host_name"))
            if actual_host_name != expected_normalized:
                try:
                    await page.mouse.move(0, 0)
                except Exception:
                    pass
                await page.wait_for_timeout(200)
                continue

        try:
            await page.mouse.move(0, 0)
        except Exception:
            pass
        return last_host_info

    try:
        await page.mouse.move(0, 0)
    except Exception:
        pass
    return last_host_info


async def capture_detail_panel(page) -> dict[str, Any]:
    panel_selectors = [
        ".el-popper[data-popper-placement]",
        ".el-popper[aria-hidden='false']",
        ".el-popover[aria-hidden='false']",
        ".el-drawer__body",
        ".el-dialog__body",
        "[role='dialog']",
        ".el-drawer",
        ".el-dialog",
    ]
    interesting_keywords = (
        "镜像",
        "GPU",
        "CPU",
        "内存",
        "硬盘",
        "端口映射",
        "网络",
        "计费方式",
        "费用",
        "实例详情",
    )

    candidates: list[dict[str, Any]] = []
    for selector in panel_selectors:
        try:
            locator = page.locator(selector)
            count = await locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                if not await candidate.is_visible():
                    continue
                payload = await candidate.evaluate(
                    r"""
                    (el) => {
                        const normalize = (text) => (text || '').trim().replace(/\s+/g, ' ');
                        const extractFields = (root) => {
                            const fields = [];
                            for (const item of root.querySelectorAll('.item')) {
                                const labelEl = item.querySelector('.title, .label');
                                const label = labelEl ? normalize(labelEl.innerText || labelEl.textContent) : '';
                                let value = '';
                                for (const child of Array.from(item.children)) {
                                    if (child === labelEl) {
                                        continue;
                                    }
                                    const childText = normalize(child.innerText || child.textContent);
                                    if (childText) {
                                        value = value ? `${value} ${childText}` : childText;
                                    }
                                }
                                const itemText = normalize(item.innerText || item.textContent);
                                fields.push({
                                    label: label || null,
                                    value: value || (label ? normalize(itemText.replace(label, '')) : itemText),
                                    text: itemText,
                                });
                            }
                            return fields;
                        };

                        const extractButtons = (root) => Array.from(root.querySelectorAll('button'))
                            .map((button) => normalize(button.innerText || button.textContent))
                            .filter(Boolean);

                        const rootText = normalize(el.innerText || el.textContent);
                        return {
                            text: rootText,
                            html: el.outerHTML,
                            fields: extractFields(el),
                            buttons: extractButtons(el),
                            ariaLabel: el.getAttribute('aria-label') || null,
                            role: el.getAttribute('role') || null,
                            className: el.className || null,
                        };
                    }
                    """
                )
                payload["selector"] = selector
                payload["index"] = index
                candidates.append(payload)
        except Exception:
            continue

    if not candidates:
        return {"found": False}

    def score(candidate: dict[str, Any]) -> float:
        text = candidate.get("text", "") or ""
        field_count = len(candidate.get("fields", []))
        keyword_hits = sum(1 for keyword in interesting_keywords if keyword in text)
        return keyword_hits * 10 + field_count * 3 + min(len(text), 4000) / 4000

    best = max(candidates, key=score)
    best_text = normalize_space(best.get("text", ""))
    field_value_markers = {
        "image": ("更换",),
        "gpu": ("升降配置",),
        "disk": ("扩容", "缩容"),
        "custom_service_ports": ("修改",),
    }
    normalized_fields: list[dict[str, Any]] = []
    for field in best.get("fields", []) or []:
        label = field.get("label")
        value = field.get("value")
        text = field.get("text")
        key = stable_key(label, DETAIL_FIELD_KEY_MAP)
        if key == "网络":
            continue
        clean_value = strip_markers(value, field_value_markers.get(key, ()))
        if key == "cost":
            clean_value = normalize_cost_value(clean_value or value)
        normalized_fields.append(
            {
                "key": key,
                "label": label,
                "value": clean_value or value,
                "text": text,
            }
        )

    field_map = {
        field["key"]: field["value"]
        for field in normalized_fields
        if field.get("key") and field.get("value")
    }

    return {
        "found": True,
        "kind": "popover"
        if ".el-popper" in best.get("selector", "") or ".el-popover" in best.get("selector", "")
        else "panel",
        "selector": best.get("selector"),
        "index": best.get("index"),
        "aria_label": best.get("ariaLabel"),
        "role": best.get("role"),
        "class_name": best.get("className"),
        "text": best_text[:2000],
        "fields": normalized_fields,
        "field_map": field_map,
        "buttons": best.get("buttons", []),
    }


async def inspect_page(page, max_items: int = 80) -> dict[str, Any]:
    return await page.evaluate(
        r"""
        (maxItems) => {
            const collect = (doc, prefix, items, limit) => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };

                const simplify = (el) => ({
                    frame: prefix,
                    tag: el.tagName.toLowerCase(),
                    id: el.id || null,
                    text: (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 200),
                    ariaLabel: el.getAttribute('aria-label') || null,
                    placeholder: el.getAttribute('placeholder') || null,
                    title: el.getAttribute('title') || null,
                    type: el.getAttribute('type') || null,
                    href: el.getAttribute('href') || null,
                    name: el.getAttribute('name') || null,
                    role: el.getAttribute('role') || null,
                    className: el.className || null,
                });

                const selectors = [
                    'button',
                    'a',
                    'input',
                    'select',
                    'textarea',
                    '[role="button"]',
                    '[role="link"]',
                    '[role="tab"]',
                    '[role="row"]',
                ].join(',');

                for (const el of doc.querySelectorAll(selectors)) {
                    if (!isVisible(el)) continue;
                    const item = simplify(el);
                    if (!item.text && !item.ariaLabel && !item.placeholder && !item.title) continue;
                    items.push(item);
                    if (items.length >= limit) return;
                }

                for (const frame of Array.from(window.frames)) {
                    try {
                        const childDoc = frame.document;
                        if (!childDoc) continue;
                        collect(childDoc, `${prefix}/frame`, items, limit);
                        if (items.length >= limit) return;
                    } catch (error) {
                        continue;
                    }
                }
            };

            const items = [];
            collect(document, 'main', items, maxItems);

            return {
                url: location.href,
                title: document.title,
                bodyText: (document.body && document.body.innerText ? document.body.innerText : '').trim().replace(/\s+/g, ' ').slice(0, 1200),
                controls: items,
            };
        }
        """,
        max_items,
    )


async def list_instances(page, max_tables: int = 8) -> dict[str, Any]:
    return await page.evaluate(
        r"""
        (maxTables) => {
            const collect = (doc, prefix, tables, limit) => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };

                const textOf = (el) => (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');

                for (const table of doc.querySelectorAll('table')) {
                    if (!isVisible(table)) continue;
                    const headers = Array.from(table.querySelectorAll('thead th, tr th')).map((th) => textOf(th)).filter(Boolean);
                    const rows = [];
                    for (const row of table.querySelectorAll('tbody tr, tr')) {
                        const cells = Array.from(row.querySelectorAll('td, th')).map((cell) => textOf(cell));
                        if (cells.length === 0) continue;
                        const rowText = textOf(row);
                        if (!rowText) continue;
                        rows.push({ cells, text: rowText });
                    }
                    if (rows.length === 0) continue;
                    tables.push({
                        frame: prefix,
                        headers,
                        rows,
                        text: textOf(table).slice(0, 2000),
                    });
                    if (tables.length >= limit) break;
                }

                for (const frame of Array.from(window.frames)) {
                    try {
                        const childDoc = frame.document;
                        if (!childDoc) continue;
                        collect(childDoc, `${prefix}/frame`, tables, limit);
                        if (tables.length >= limit) break;
                    } catch (error) {
                        continue;
                    }
                }
            };

            const tables = [];
            collect(document, 'main', tables, maxTables);

            const bodyText = (document.body && document.body.innerText ? document.body.innerText : '').trim().replace(/\s+/g, ' ').slice(0, 4000);

            return {
                url: location.href,
                title: document.title,
                tables,
                bodyText,
            };
        }
        """,
        max_tables,
    )
