from __future__ import annotations

import json
import time

from autodlctl.parsing import (
    extract_container_id,
    filter_instance_summaries,
    inspect_storage_state_cookie_expiry,
    normalize_space,
    parse_gpu_quota,
    parse_gpu_spec_summary,
    sort_instance_summaries,
    summarize_instance_tables,
)


def test_normalize_space_and_container_id() -> None:
    assert normalize_space("  hello   world ") == "hello world"
    assert extract_container_id("北京 / host-a 8d4e4393c8-fe777ef1 测试实例") == "8d4e4393c8-fe777ef1"
    assert extract_container_id("北京 / host-a shared-1234 测试实例") is None


def test_gpu_parsing_helpers() -> None:
    assert parse_gpu_quota(" 2 / 8 ") == {"gpu_free": 2, "gpu_total": 8}
    assert parse_gpu_spec_summary("RTX 4090 * 2卡") == {
        "gpu_model": "RTX 4090",
        "gpu_cards": 2,
    }


def test_storage_state_cookie_expiry_statuses(tmp_path) -> None:
    fresh_path = tmp_path / "fresh.json"
    expired_path = tmp_path / "expired.json"
    now = time.time()

    fresh_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "fresh",
                        "domain": ".autodl.com",
                        "path": "/",
                        "expires": now + (10 * 24 * 3600),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    expired_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "expired",
                        "domain": ".autodl.com",
                        "path": "/",
                        "expires": now - 3600,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert inspect_storage_state_cookie_expiry(str(fresh_path))["status"] == "fresh"
    assert inspect_storage_state_cookie_expiry(str(expired_path))["status"] == "expired"


def test_filter_and_sort_instance_summaries() -> None:
    instances = [
        {
            "container_id": "alpha-1111",
            "gpu_model": "RTX 4090",
            "gpu_cards": 1,
            "identity": {"site": "北京", "host": "host-a", "instance_id": "alpha-1111", "name": "train-a"},
            "status": {"power": "运行中", "gpu_supply": "GPU充足"},
            "billing": "按时",
            "lifecycle": "2026-04-09",
            "actions": {"labels": ["查看详情"], "keys": ["detail"]},
            "host_info": {
                "host_name": "北京 / host-a",
                "gpu_free": 2,
                "gpu_total": 8,
                "data_disk_expandable_gb": 500,
                "rentable_until": "2026-04-09",
            },
        },
        {
            "container_id": "beta-2222",
            "gpu_model": "RTX 3090",
            "gpu_cards": 1,
            "identity": {"site": "上海", "host": "host-b", "instance_id": "beta-2222", "name": "train-b"},
            "status": {"power": "已关机", "gpu_supply": None},
            "billing": "包日",
            "lifecycle": "2026-04-08",
            "actions": {"labels": ["开机"], "keys": ["start"]},
            "host_info": {
                "host_name": "上海 / host-b",
                "gpu_free": 1,
                "gpu_total": 4,
                "data_disk_expandable_gb": 100,
                "rentable_until": "2026-04-08",
            },
        },
    ]

    filtered = filter_instance_summaries(
        instances,
        query="train",
        gpu_model="4090",
        min_gpu_free=2,
    )
    assert [item["container_id"] for item in filtered] == ["alpha-1111"]

    sorted_items = sort_instance_summaries(instances, "rentable_until", "asc")
    assert [item["container_id"] for item in sorted_items] == ["beta-2222", "alpha-1111"]


def test_summarize_instance_tables() -> None:
    payload = {
        "tables": [
            {
                "headers": [
                    "实例ID /名称",
                    "状态",
                    "规格详情",
                    "本地磁盘",
                    "健康状态",
                    "付费方式",
                    "释放时间/停机时间",
                    "SSH登录",
                    "快捷工具",
                    "操作",
                ],
                "rows": [
                    {
                        "cells": [
                            "北京 / host-a 8d4e4393c8-fe777ef1 实例A",
                            "运行中 GPU充足",
                            "RTX 4090 * 2卡 查看详情",
                            "100G",
                            "正常",
                            "按时",
                            "2026-04-10 设置定时关机",
                            "ssh",
                            "jupyter",
                            "查看详情 关机",
                        ],
                        "text": "北京 / host-a 8d4e4393c8-fe777ef1 实例A 运行中 GPU 充足 RTX 4090 * 2卡 查看详情 100G 正常 按时 2026-04-10 设置定时关机 ssh jupyter 查看详情 关机",
                    }
                ],
            }
        ]
    }

    summary = summarize_instance_tables(payload)
    assert summary[0]["container_id"] == "8d4e4393c8-fe777ef1"
    assert summary[0]["identity"]["site"] == "北京"
    assert summary[0]["gpu_model"] == "RTX 4090"
    assert summary[0]["gpu_cards"] == 2
