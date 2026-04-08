from __future__ import annotations

from contextlib import asynccontextmanager
import json
import runpy
import time
from pathlib import Path

import pytest

from autodlctl.commands import instances
from autodlctl import cli
import autodlctl.parsing as parsing


def test_main_help(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    assert exc_info.value.code == 0
    assert "AutoDL console browser helper." in capsys.readouterr().out


def test_main_dispatches_run(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "ensure_browser_installed", lambda: None)

    async def fake_run_steps(**kwargs):
        return {"success": True, "command": "run", "steps": kwargs["steps"]}

    monkeypatch.setattr(cli, "run_steps", fake_run_steps)

    exit_code = cli.main(["run", "--steps", "[]"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["command"] == "run"
    assert payload["steps"] == []


def test_main_short_circuits_expired_storage_state(tmp_path, monkeypatch, capsys) -> None:
    state_path = tmp_path / "expired.json"
    state_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "expired",
                        "domain": ".autodl.com",
                        "path": "/",
                        "expires": time.time() - 60,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fail_if_called() -> None:
        raise AssertionError("ensure_browser_installed should not be called for expired storage state")

    monkeypatch.setattr(cli, "ensure_browser_installed", fail_if_called)

    exit_code = cli.main(["list", "--storage-state", str(state_path)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["success"] is False
    assert payload["storage_state_check"]["status"] == "expired"


def test_main_list_uses_default_storage_state(monkeypatch, capsys) -> None:
    observed = {"storage_state": None}

    monkeypatch.setattr(cli, "ensure_browser_installed", lambda: None)

    def fake_storage_state_check(path: str) -> dict[str, object]:
        observed["storage_state"] = path
        return {"checked": True, "status": "fresh", "path": path}

    async def fake_run_list(**kwargs):
        return {"success": True, "command": "list", "storage_state_path": kwargs["storage_state_path"]}

    monkeypatch.setattr(cli, "inspect_storage_state_cookie_expiry", fake_storage_state_check)
    monkeypatch.setattr(cli, "run_list", fake_run_list)

    exit_code = cli.main(["list"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert observed["storage_state"] == ".autodl/storage_state.json"
    assert payload["storage_state_path"] == ".autodl/storage_state.json"


def test_compat_wrapper_delegates_to_cli(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_main() -> int:
        calls["count"] += 1
        return 7

    monkeypatch.setattr("autodlctl.cli.main", fake_main)
    wrapper_path = Path(__file__).resolve().parents[1] / "tools" / "autodl_console.py"

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(wrapper_path), run_name="__main__")

    assert exc_info.value.code == 7
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_run_auth_waits_full_pause_window(monkeypatch, tmp_path) -> None:
    sleep_calls: list[float] = []
    saved_paths: list[str] = []
    browser_kwargs: list[dict[str, object]] = []
    fake_time = {"value": 0.0}

    class FakeLoop:
        def time(self) -> float:
            return fake_time["value"]

    class FakeBodyLocator:
        def __init__(self) -> None:
            self.calls = 0

        async def wait_for(self, state: str = "visible") -> None:
            return None

        async def inner_text(self) -> str:
            self.calls += 1
            if self.calls == 1:
                return "登录 注册"
            return "登录 注册 实例ID /名称 查看详情 关机"

    class FakePage:
        def __init__(self) -> None:
            self.url = "https://www.autodl.com/console/instance/"
            self._body = FakeBodyLocator()

        async def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
            self.url = url

        async def wait_for_timeout(self, ms: int) -> None:
            return None

        def locator(self, selector: str):
            assert selector == "body"
            return self._body

        async def title(self) -> str:
            return "AutoDL"

    class FakeContext:
        async def storage_state(self, path: str) -> None:
            saved_paths.append(path)
            Path(path).write_text(json.dumps({"cookies": []}), encoding="utf-8")

    @asynccontextmanager
    async def fake_browser_page(**kwargs):
        browser_kwargs.append(kwargs)
        yield FakeContext(), FakePage()

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        fake_time["value"] += seconds

    monkeypatch.setattr(instances, "browser_page", fake_browser_page)
    monkeypatch.setattr(instances.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(instances.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(
        parsing,
        "inspect_storage_state_cookie_expiry",
        lambda path: {"checked": True, "status": "fresh", "path": path},
    )

    result = await instances.run_auth(
        url="https://www.autodl.com/console/instance/",
        headless=False,
        pause_seconds=30,
        timeout_ms=30_000,
        storage_state_path=None,
        browser_profile_dir=".autodl/auth-profile",
        save_storage_state_path=str(tmp_path / "state.json"),
    )

    assert sleep_calls == [3, 1, 1, 1, 1, 1]
    assert browser_kwargs == [
        {
            "headless": False,
            "timeout_ms": 30_000,
            "storage_state_path": None,
            "browser_channel": "chrome",
            "browser_profile_dir": ".autodl/auth-profile",
        }
    ]
    assert saved_paths == [str(tmp_path / "state.json")]
    assert result["success"] is True
    assert result["detected_logged_in"] is True
    assert result["browser_profile_dir"] == ".autodl/auth-profile"
    assert result["storage_state_check"]["status"] == "fresh"


def test_main_auth_defaults_save_storage_state(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "ensure_browser_installed", lambda: None)

    async def fake_run_auth(**kwargs):
        return {"success": True, "saved_storage_state": kwargs["save_storage_state_path"]}

    monkeypatch.setattr(cli, "run_auth", fake_run_auth)

    exit_code = cli.main(["auth"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["saved_storage_state"] == ".autodl/storage_state.json"


@pytest.mark.asyncio
async def test_run_list_collects_all_pages(monkeypatch, tmp_path) -> None:
    page_state = {"index": 1}
    saved_paths: list[str] = []

    class FakePage:
        async def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
            return None

        async def wait_for_timeout(self, ms: int) -> None:
            return None

        async def screenshot(self, path: str, full_page: bool = True) -> None:
            return None

    class FakeContext:
        async def storage_state(self, path: str) -> None:
            saved_paths.append(path)
            Path(path).write_text(json.dumps({"cookies": []}), encoding="utf-8")

    @asynccontextmanager
    async def fake_browser_page(**kwargs):
        yield FakeContext(), FakePage()

    def make_row(container_id: str, name: str) -> dict[str, object]:
        cells = [
            f"北京 / host-a {container_id} {name}",
            "已关机",
            "RTX 4090 * 1卡 查看详情",
            "100G",
            "正常",
            "按量计费",
            "1天后释放",
            "ssh",
            "jupyter",
            "查看详情 开机",
        ]
        return {"cells": cells, "text": " ".join(cells)}

    page_tables = {
        1: {
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
                    "rows": [make_row(f"insta-{index:02d}", f"实例{index:02d}") for index in range(1, 11)],
                }
            ]
        },
        2: {
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
                    "rows": [make_row(f"insta-{index:02d}", f"实例{index:02d}") for index in range(11, 14)],
                }
            ]
        },
    }

    async def fake_list_instances(page, max_tables: int = 8):
        return page_tables[page_state["index"]]

    async def fake_advance_list_page(page, timeout_ms: int = 5000) -> bool:
        if page_state["index"] == 1:
            page_state["index"] = 2
            return True
        return False

    async def fake_augment_instances_with_host_info(page, instances, timeout_ms: int):
        for instance in instances:
            instance["host_info"] = {"host_name": "北京 / host-a"}
        return instances

    monkeypatch.setattr(instances, "browser_page", fake_browser_page)
    monkeypatch.setattr(instances, "list_instances", fake_list_instances)
    monkeypatch.setattr(instances, "advance_list_page", fake_advance_list_page)
    monkeypatch.setattr(instances, "augment_instances_with_host_info", fake_augment_instances_with_host_info)

    result = await instances.run_list(
        url="https://www.autodl.com/console/instance/list",
        headless=False,
        timeout_ms=30_000,
        screenshot_path=None,
        storage_state_path=None,
        max_tables=8,
        query=None,
        site=None,
        host=None,
        gpu_model=None,
        gpu_driver=None,
        cuda_version=None,
        status=None,
        min_gpu_free=None,
        min_data_disk_expandable_gb=None,
        sort_by=None,
        sort_order="asc",
        limit=None,
        save_storage_state_path=str(tmp_path / "state.json"),
    )

    assert result["count"] == 13
    assert len(result["instances"]) == 13
    assert result["instances"][0]["container_id"] == "insta-01"
    assert result["instances"][-1]["container_id"] == "insta-13"
    assert saved_paths == [str(tmp_path / "state.json")]
