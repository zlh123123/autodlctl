from __future__ import annotations

import asyncio
from typing import Any

from autodlctl.runtime import browser_page


BALANCE_TABLE_EVALUATION_SCRIPT = r"""
() => {
    const normalize = (text) => (text || '').trim().replace(/\s+/g, ' ');
    const isVisible = (el) => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };

    const tables = Array.from(document.querySelectorAll('table')).filter(isVisible);
    let lastHeaders = [];
    for (const table of tables) {
        const tableHeaders = Array.from(table.querySelectorAll('thead th, tr th')).map((th) => normalize(th.innerText || th.textContent)).filter(Boolean);
        if (tableHeaders.length > 0) {
            lastHeaders = tableHeaders;
        }

        const headers = tableHeaders.length > 0 ? tableHeaders : lastHeaders;
        const headerText = headers.join(' ');
        const dataRows = Array.from(table.querySelectorAll('tbody tr')).filter(isVisible);
        if (!headerText.includes('账户余额') || dataRows.length === 0) continue;

        const firstRow = dataRows[0];
        const cells = Array.from(firstRow.querySelectorAll('td')).map((td) => normalize(td.innerText || td.textContent));
        const balanceIndex = headers.indexOf('账户余额');
        if (balanceIndex < 0 || !cells[balanceIndex]) continue;
        return {
            found: true,
            headers,
            row: cells,
            balance: cells[balanceIndex],
        };
    }

    return {found: false};
}
"""


async def _capture_balance_info(page) -> dict[str, Any]:
    return await page.evaluate(BALANCE_TABLE_EVALUATION_SCRIPT)


async def _wait_for_balance_info(page, timeout_ms: int) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + max(0.5, timeout_ms / 1000)
    last_balance_info: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() <= deadline:
        try:
            last_balance_info = await _capture_balance_info(page)
            if last_balance_info.get("found") and last_balance_info.get("balance"):
                return last_balance_info
        except Exception:
            pass
        await asyncio.sleep(0.25)

    return last_balance_info or {"found": False}


async def run_balance(args) -> dict[str, object]:
    async with browser_page(
        headless=bool(args.headless),
        timeout_ms=args.timeout_ms,
        storage_state_path=args.storage_state,
    ) as (_context, page):
        await page.goto(args.url, wait_until="domcontentloaded")
        balance_info = await _wait_for_balance_info(page, timeout_ms=max(3000, args.timeout_ms))

        if args.screenshot:
            await page.screenshot(path=args.screenshot, full_page=True)

        if not balance_info.get("found") or not balance_info.get("balance"):
            return {
                "success": False,
                "reason": "Could not locate account balance on the income/expense page",
            }

        return {
            "success": True,
            "balance": balance_info.get("balance"),
            "record_time": balance_info.get("row", [None, None])[1] if balance_info.get("row") else None,
            "source_url": page.url,
        }
