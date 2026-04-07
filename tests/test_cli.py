from __future__ import annotations

import json
import runpy
import time
from pathlib import Path

import pytest

from autodlctl import cli


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
