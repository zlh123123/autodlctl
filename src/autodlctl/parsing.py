from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from autodlctl.constants import (
    ACTION_LABEL_KEY_MAP,
    DETAIL_FIELD_KEY_MAP,
    GPU_QUOTA_RE,
    HOST_HOVER_FIELD_KEY_MAP,
    INSTANCE_ID_RE,
    LIST_COLUMN_KEY_MAP,
    LIST_FALLBACK_HEADERS,
    SESSION_COOKIE_DOMAIN_SUFFIX,
    SESSION_COOKIE_EXPIRY_WARNING_SECONDS,
)


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected a boolean value, got: {value}")


def normalize_space(text: str | None) -> str:
    return " ".join((text or "").split())


def stable_key(label: str | None, mapping: dict[str, str]) -> str | None:
    if not label:
        return None
    normalized = label.strip().rstrip("：:").strip()
    return mapping.get(normalized, normalized)


def strip_markers(text: str | None, markers: tuple[str, ...]) -> str:
    result = text or ""
    for marker in markers:
        result = result.replace(marker, "")
    return normalize_space(result)


def normalize_cost_value(text: str | None) -> str | None:
    normalized = normalize_space(text)
    if not normalized:
        return None

    matches = re.findall(r"￥\s*([0-9]+(?:\.[0-9]+)?)\s*(/时|/小时|/h|元/时)?", normalized)
    if not matches:
        return normalized

    amounts = [float(amount) for amount, _suffix in matches]
    if not amounts:
        return normalized

    suffix = next((suffix for _amount, suffix in matches if suffix), "")
    if not suffix and "时" in normalized:
        suffix = "/时"

    minimum = min(amounts)
    amount_text = f"{minimum:g}"
    return f"￥{amount_text}{suffix}"


def contains_any(text: str | None, markers: tuple[str, ...]) -> bool:
    normalized = text or ""
    return any(marker in normalized for marker in markers)


def extract_container_id(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        match = INSTANCE_ID_RE.search(normalize_space(value))
        if match:
            return match.group(0)
    return None


def parse_int_from_text(text: str | None) -> int | None:
    normalized = normalize_space(text)
    if not normalized:
        return None
    match = re.search(r"\d+", normalized)
    return int(match.group(0)) if match else None


def parse_gpu_spec_summary(spec: str | None) -> dict[str, Any]:
    normalized = normalize_space(spec)
    if not normalized:
        return {"gpu_model": None, "gpu_cards": None}

    match = re.match(r"^(?P<model>.+?)(?:\s*\*\s*(?P<count>\d+)\s*卡)?$", normalized)
    if not match:
        return {"gpu_model": normalized, "gpu_cards": None}

    model = normalize_space(match.group("model"))
    count = match.group("count")
    return {
        "gpu_model": model or None,
        "gpu_cards": int(count) if count else None,
    }


def matches_substring(value: str | None, needle: str | None) -> bool:
    if not needle:
        return True
    return normalize_space(needle).casefold() in normalize_space(value).casefold()


def parse_iso_date(text: str | None) -> date | None:
    normalized = normalize_space(text)
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def parse_gpu_quota(text: str | None) -> dict[str, int] | None:
    normalized = normalize_space(text)
    if not normalized:
        return None
    match = GPU_QUOTA_RE.match(normalized)
    if not match:
        return None
    return {"gpu_free": int(match.group(1)), "gpu_total": int(match.group(2))}


def cookie_matches_domain(
    domain: str | None,
    suffix: str = SESSION_COOKIE_DOMAIN_SUFFIX,
) -> bool:
    if not domain:
        return False
    normalized_domain = domain.lstrip(".").casefold()
    normalized_suffix = suffix.lstrip(".").casefold()
    return normalized_domain == normalized_suffix or normalized_domain.endswith(f".{normalized_suffix}")


def inspect_storage_state_cookie_expiry(
    storage_state_path: str,
    warning_seconds: int = SESSION_COOKIE_EXPIRY_WARNING_SECONDS,
) -> dict[str, Any]:
    path = Path(storage_state_path)
    if not path.is_file():
        return {
            "checked": False,
            "status": "missing",
            "reason": f"Storage state file not found: {storage_state_path}",
            "path": storage_state_path,
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "checked": False,
            "status": "invalid",
            "reason": f"Could not parse storage state JSON: {exc}",
            "path": storage_state_path,
        }

    cookies = payload.get("cookies") or []
    autodl_cookies = [cookie for cookie in cookies if cookie_matches_domain(cookie.get("domain"))]
    inspected_cookies = autodl_cookies or cookies
    scope = "autodl_domain" if autodl_cookies else "all_cookies"
    checked_at = datetime.now(timezone.utc)
    checked_at_unix = checked_at.timestamp()

    expiring_cookies: list[dict[str, Any]] = []
    for cookie in inspected_cookies:
        expires = cookie.get("expires")
        if not isinstance(expires, (int, float)) or expires <= 0:
            continue

        expires_in_seconds = int(expires - checked_at_unix)
        expiring_cookies.append(
            {
                "name": cookie.get("name"),
                "domain": cookie.get("domain"),
                "path": cookie.get("path"),
                "expires_at_utc": datetime.fromtimestamp(expires, tz=timezone.utc).isoformat(),
                "expires_in_seconds": expires_in_seconds,
                "expired": expires_in_seconds <= 0,
            }
        )

    if not inspected_cookies:
        return {
            "checked": True,
            "status": "empty",
            "reason": "No cookies found in storage state",
            "path": storage_state_path,
            "scope": scope,
            "cookie_count": len(cookies),
            "autodl_cookie_count": len(autodl_cookies),
            "checked_at_utc": checked_at.isoformat(),
        }

    if not expiring_cookies:
        return {
            "checked": True,
            "status": "session_only",
            "reason": "No persistent cookies with expires timestamps were found",
            "path": storage_state_path,
            "scope": scope,
            "cookie_count": len(cookies),
            "autodl_cookie_count": len(autodl_cookies),
            "checked_at_utc": checked_at.isoformat(),
        }

    expired_cookies = [cookie for cookie in expiring_cookies if cookie["expired"]]
    expiring_soon_cookies = [
        cookie
        for cookie in expiring_cookies
        if not cookie["expired"] and cookie["expires_in_seconds"] <= warning_seconds
    ]
    next_expiry = min(expiring_cookies, key=lambda cookie: cookie["expires_in_seconds"])

    if expired_cookies:
        status = "expired"
    elif expiring_soon_cookies:
        status = "expiring_soon"
    else:
        status = "fresh"

    return {
        "checked": True,
        "status": status,
        "path": storage_state_path,
        "scope": scope,
        "cookie_count": len(cookies),
        "autodl_cookie_count": len(autodl_cookies),
        "expiring_cookie_count": len(expiring_cookies),
        "expired_cookie_count": len(expired_cookies),
        "expiring_soon_cookie_count": len(expiring_soon_cookies),
        "next_expiry": next_expiry,
        "expired_cookies": expired_cookies[:5],
        "expiring_soon_cookies": expiring_soon_cookies[:5],
        "checked_at_utc": checked_at.isoformat(),
    }


def normalize_host_hover_info(fields: list[dict[str, Any]]) -> dict[str, Any]:
    host_info: dict[str, Any] = {}
    for field in fields:
        label = field.get("label")
        value = field.get("value")
        key = stable_key(label, HOST_HOVER_FIELD_KEY_MAP)
        if key == "host_name":
            host_info[key] = normalize_space(value)
        elif key == "rentable_until":
            host_info[key] = normalize_space(value)
        elif key == "data_disk_expandable_gb":
            host_info[key] = parse_int_from_text(value)
        elif key == "gpu_free_total":
            quota = parse_gpu_quota(value)
            if quota:
                host_info.update(quota)
        elif key == "gpu_driver":
            host_info[key] = normalize_space(value)
        elif key == "cuda_version":
            host_info[key] = normalize_space(value)

    return host_info


def extract_start_access_summary(row_text: str | None) -> dict[str, Any] | None:
    normalized = normalize_space(row_text)
    if not normalized or "运行中" not in normalized:
        return None

    return {
        "available": True,
        "row_text": normalized,
    }


def normalize_actions(text: str) -> dict[str, Any]:
    scan_text = text.replace("设置定时关机", "")
    labels = []
    if "查看详情" in scan_text:
        labels.append("查看详情")
    if "开机" in scan_text:
        labels.append("开机")
    if re.search(r"(?<!已)关机", scan_text):
        labels.append("关机")
    if re.search(r"(?<!已)停止", scan_text):
        labels.append("停止")
    if re.search(r"(?<!已)关闭", scan_text):
        labels.append("关闭")
    if "设置定时关机" in text:
        labels.append("设置定时关机")
    if "更多" in scan_text:
        labels.append("更多")
    keys = [ACTION_LABEL_KEY_MAP[label] for label in labels]
    return {
        "labels": labels,
        "keys": keys,
        "detail_label": "查看详情" if "查看详情" in text else None,
        "start_stop_label": next(
            (label for label in ("开机", "关机", "停止", "关闭") if label in text),
            None,
        ),
        "schedule_shutdown_label": "设置定时关机" if "设置定时关机" in text else None,
        "more_label": "更多" if "更多" in text else None,
    }


def parse_identity_cell(text: str) -> dict[str, Any]:
    normalized = normalize_space(text)
    match = INSTANCE_ID_RE.search(normalized)
    instance_id = match.group(0) if match else None
    location = normalized.split(instance_id, 1)[0].strip() if instance_id else None
    site = None
    host = None
    if location and " / " in location:
        site, host = [part.strip() for part in location.split(" / ", 1)]

    name = None
    if instance_id:
        trailing = normalized.split(instance_id, 1)[1].strip()
        trailing = trailing.replace("设置名称", "").strip()
        if trailing:
            name = trailing

    return {
        "display_text": text,
        "site": site,
        "host": host,
        "instance_id": instance_id,
        "name": name,
    }


def normalize_list_record(record: dict[str, Any], row_index: int) -> dict[str, Any]:
    headers = record.get("headers", [])
    cells = record.get("cells", [])
    row_text = record.get("text", "")
    columns = {
        stable_key(headers[index], LIST_COLUMN_KEY_MAP): cells[index]
        for index in range(min(len(headers), len(cells)))
        if stable_key(headers[index], LIST_COLUMN_KEY_MAP)
    }

    identity = parse_identity_cell(columns.get("identity", "")) if columns.get("identity") else {}
    raw_actions_text = row_text or (columns.get("actions", "") or "")
    status_text = columns.get("status", "") or ""
    power_state = strip_markers(status_text, ("GPU充足",)) or None
    gpu_supply = "GPU充足" if "GPU充足" in status_text else None
    spec_summary = strip_markers(columns.get("spec", ""), ("查看详情",)) or None
    lifecycle_text = strip_markers(columns.get("lifecycle", ""), ("设置定时关机",)) or None

    return {
        "row_index": row_index,
        "identity": identity,
        "status": {"power": power_state, "gpu_supply": gpu_supply, "text": status_text or None},
        "spec": {"summary": spec_summary, "text": columns.get("spec") or None},
        "storage": {"summary": columns.get("storage")},
        "health": {"status": columns.get("health")},
        "billing": {"method": columns.get("billing")},
        "lifecycle": {"text": lifecycle_text, "raw_text": columns.get("lifecycle") or None},
        "access": {
            "ssh_login": columns.get("ssh_login"),
            "quick_tools": columns.get("quick_tools"),
        },
        "actions": normalize_actions(raw_actions_text),
        "columns": columns,
        "raw": {
            "headers": headers,
            "cells": cells,
            "row_text": row_text,
        },
    }


def build_instance_summary(record: dict[str, Any]) -> dict[str, Any]:
    identity = record.get("identity") or {}
    container_id = identity.get("instance_id") or extract_container_id(identity.get("display_text"))
    gpu_spec = parse_gpu_spec_summary(record.get("spec", {}).get("summary"))
    return {
        "container_id": container_id,
        "host_info": None,
        "gpu_model": gpu_spec.get("gpu_model"),
        "gpu_cards": gpu_spec.get("gpu_cards"),
        "identity": {
            "site": identity.get("site"),
            "host": identity.get("host"),
            "instance_id": identity.get("instance_id"),
            "name": identity.get("name"),
        },
        "status": record.get("status"),
        "spec": record.get("spec", {}).get("summary"),
        "billing": record.get("billing", {}).get("method"),
        "lifecycle": record.get("lifecycle", {}).get("text"),
        "actions": {
            "labels": record.get("actions", {}).get("labels", []),
            "keys": record.get("actions", {}).get("keys", []),
        },
    }


def instance_listing_text(instance: dict[str, Any]) -> str:
    identity = instance.get("identity") or {}
    actions = instance.get("actions") or {}
    status = instance.get("status") or {}
    host_info = instance.get("host_info") or {}
    parts = [
        instance.get("container_id"),
        identity.get("site"),
        identity.get("host"),
        identity.get("instance_id"),
        identity.get("name"),
        status.get("power"),
        status.get("gpu_supply"),
        instance.get("gpu_model"),
        instance.get("gpu_cards"),
        instance.get("spec"),
        instance.get("billing"),
        instance.get("lifecycle"),
        host_info.get("host_name"),
        host_info.get("rentable_until"),
        host_info.get("data_disk_expandable_gb"),
        host_info.get("gpu_free"),
        host_info.get("gpu_total"),
        host_info.get("gpu_driver"),
        host_info.get("cuda_version"),
        " ".join(actions.get("labels", [])),
        " ".join(actions.get("keys", [])),
    ]
    return normalize_space(" ".join(str(part) for part in parts if part not in (None, ""))).casefold()


def filter_instance_summaries(
    instances: list[dict[str, Any]],
    *,
    query: str | None = None,
    site: str | None = None,
    host: str | None = None,
    gpu_model: str | None = None,
    gpu_driver: str | None = None,
    cuda_version: str | None = None,
    status: str | None = None,
    min_gpu_free: int | None = None,
    min_data_disk_expandable_gb: int | None = None,
) -> list[dict[str, Any]]:
    normalized_query = normalize_space(query)
    normalized_site = normalize_space(site)
    normalized_host = normalize_space(host)
    normalized_gpu_model = normalize_space(gpu_model)
    normalized_gpu_driver = normalize_space(gpu_driver)
    normalized_cuda_version = normalize_space(cuda_version)
    normalized_status = normalize_space(status)

    filtered: list[dict[str, Any]] = []
    for instance in instances:
        identity = instance.get("identity") or {}
        status_info = instance.get("status") or {}
        host_info = instance.get("host_info") or {}

        if normalized_query and normalized_query.casefold() not in instance_listing_text(instance):
            continue
        if normalized_site and not matches_substring(identity.get("site"), normalized_site) and not matches_substring(
            host_info.get("host_name"),
            normalized_site,
        ):
            continue
        if normalized_host and not matches_substring(identity.get("host"), normalized_host) and not matches_substring(
            host_info.get("host_name"),
            normalized_host,
        ):
            continue
        if normalized_gpu_model and not matches_substring(instance.get("gpu_model"), normalized_gpu_model):
            continue
        if normalized_gpu_driver and not matches_substring(host_info.get("gpu_driver"), normalized_gpu_driver):
            continue
        if normalized_cuda_version and not matches_substring(host_info.get("cuda_version"), normalized_cuda_version):
            continue
        if normalized_status and not matches_substring(status_info.get("power"), normalized_status) and not matches_substring(
            status_info.get("gpu_supply"),
            normalized_status,
        ):
            continue

        gpu_free = host_info.get("gpu_free")
        if min_gpu_free is not None and (gpu_free is None or int(gpu_free) < min_gpu_free):
            continue

        data_disk_expandable_gb = host_info.get("data_disk_expandable_gb")
        if min_data_disk_expandable_gb is not None and (
            data_disk_expandable_gb is None or int(data_disk_expandable_gb) < min_data_disk_expandable_gb
        ):
            continue

        filtered.append(instance)

    return filtered


def instance_sort_value(instance: dict[str, Any], sort_by: str) -> Any:
    identity = instance.get("identity") or {}
    host_info = instance.get("host_info") or {}
    status = instance.get("status") or {}

    if sort_by == "site":
        return normalize_space(identity.get("site")).casefold() or None
    if sort_by == "host":
        return normalize_space(identity.get("host")).casefold() or None
    if sort_by == "host_name":
        return normalize_space(host_info.get("host_name")).casefold() or None
    if sort_by == "name":
        return normalize_space(identity.get("name")).casefold() or None
    if sort_by == "instance_id":
        return normalize_space(identity.get("instance_id")).casefold() or None
    if sort_by == "gpu_model":
        return normalize_space(instance.get("gpu_model")).casefold() or None
    if sort_by == "gpu_cards":
        return instance.get("gpu_cards")
    if sort_by == "gpu_free":
        return host_info.get("gpu_free")
    if sort_by == "gpu_total":
        return host_info.get("gpu_total")
    if sort_by == "data_disk_expandable_gb":
        return host_info.get("data_disk_expandable_gb")
    if sort_by == "rentable_until":
        return parse_iso_date(host_info.get("rentable_until"))
    if sort_by == "gpu_driver":
        return normalize_space(host_info.get("gpu_driver")).casefold() or None
    if sort_by == "cuda_version":
        return normalize_space(host_info.get("cuda_version")).casefold() or None
    if sort_by == "status":
        return normalize_space(status.get("power")).casefold() or None
    if sort_by == "billing":
        return normalize_space(instance.get("billing")).casefold() or None
    if sort_by == "lifecycle":
        return normalize_space(instance.get("lifecycle")).casefold() or None
    raise ValueError(f"Unsupported list sort key: {sort_by}")


def sort_instance_summaries(
    instances: list[dict[str, Any]],
    sort_by: str | None,
    sort_order: str,
) -> list[dict[str, Any]]:
    if not sort_by:
        return instances

    decorated: list[tuple[bool, Any, dict[str, Any]]] = []
    for instance in instances:
        value = instance_sort_value(instance, sort_by)
        decorated.append((value is None, value, instance))

    reverse = sort_order == "desc"
    decorated.sort(key=lambda item: (item[0], item[1]), reverse=reverse)
    if reverse:
        present = [item for item in decorated if not item[0]]
        missing = [item for item in decorated if item[0]]
        decorated = present + missing

    return [item[2] for item in decorated]


def limit_instance_summaries(
    instances: list[dict[str, Any]],
    limit: int | None,
) -> list[dict[str, Any]]:
    if limit is None:
        return instances
    return instances[: max(0, limit)]


def summarize_instance_tables(list_payload: dict[str, Any]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    last_headers: list[str] = []
    for table in list_payload.get("tables", []):
        headers = table.get("headers", []) or last_headers
        rows = table.get("rows", [])
        if not headers and rows and len(rows[0].get("cells", [])) >= len(LIST_FALLBACK_HEADERS):
            headers = LIST_FALLBACK_HEADERS
        if not headers:
            continue

        if table.get("headers"):
            last_headers = table.get("headers", [])

        if len(headers) < 2:
            continue

        header_text = normalize_space(" ".join(headers))
        for row_index, row in enumerate(rows, start=1):
            cells = row.get("cells", [])
            if len(cells) < 2:
                continue
            row_text = normalize_space(row.get("text", ""))
            if row_text and row_text == header_text:
                continue
            effective_headers = headers if len(headers) >= len(cells) else headers[: len(cells)]
            record = {
                effective_headers[index]: cells[index]
                for index in range(min(len(effective_headers), len(cells)))
            }
            if not any(record.values()):
                continue
            summary.append(
                build_instance_summary(
                    normalize_list_record(
                        {"headers": headers, "cells": cells, "text": row.get("text", "")},
                        row_index,
                    )
                )
            )

    return summary
