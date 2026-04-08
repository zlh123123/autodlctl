from __future__ import annotations

import argparse
import asyncio
import json
import sys

from autodlctl.commands.account import run_balance
from autodlctl.commands.generic import load_steps, open_and_inspect, run_status, run_steps
from autodlctl.commands.instances import run_auth, run_instance_action, run_list
from autodlctl.constants import (
    BALANCE_URL,
    DEFAULT_AUTH_PROFILE_DIR,
    DEFAULT_URL,
    DEFAULT_STORAGE_STATE_PATH,
    LIST_SORT_CHOICES,
    START_LABELS,
    STOP_LABELS,
)
from autodlctl.parsing import inspect_storage_state_cookie_expiry, parse_bool
from autodlctl.runtime import ensure_browser_installed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autodlctl",
        description="AutoDL console browser helper.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a JSON step list against the AutoDL console")
    run_parser.add_argument("--url", default=DEFAULT_URL, help="Console URL to open")
    run_parser.add_argument("--steps", help="JSON array of steps")
    run_parser.add_argument("--steps-file", help="Path to a JSON file with steps")
    run_parser.add_argument("--headless", type=parse_bool, default=True)
    run_parser.add_argument("--timeout-ms", type=int, default=30_000)
    run_parser.add_argument("--screenshot", help="Optional screenshot output path")
    run_parser.add_argument(
        "--storage-state",
        default=DEFAULT_STORAGE_STATE_PATH,
        help="Load Playwright storage state before opening the page",
    )
    run_parser.add_argument("--save-storage-state", help="Write Playwright storage state after the run")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect visible controls on the AutoDL console page")
    inspect_parser.add_argument("--url", default=DEFAULT_URL, help="Console URL to open")
    inspect_parser.add_argument("--headless", type=parse_bool, default=True)
    inspect_parser.add_argument("--timeout-ms", type=int, default=30_000)
    inspect_parser.add_argument("--screenshot", help="Optional screenshot output path")
    inspect_parser.add_argument(
        "--storage-state",
        default=DEFAULT_STORAGE_STATE_PATH,
        help="Load Playwright storage state before opening the page",
    )
    inspect_parser.add_argument("--save-storage-state", help="Write Playwright storage state after the run")
    inspect_parser.add_argument("--max-items", type=int, default=80)

    start_parser = subparsers.add_parser("start", help="Start a selected AutoDL instance")
    start_parser.add_argument("--url", default=DEFAULT_URL, help="Console URL to open")
    start_parser.add_argument("--instance", required=True, help="Text that identifies the target instance row")
    start_parser.add_argument("--mode", choices=("gpu", "nocard"), default="gpu", help="Start mode: gpu or nocard")
    start_parser.add_argument("--headless", type=parse_bool, default=True)
    start_parser.add_argument("--timeout-ms", type=int, default=30_000)
    start_parser.add_argument("--screenshot", help="Optional screenshot output path")
    start_parser.add_argument(
        "--storage-state",
        default=DEFAULT_STORAGE_STATE_PATH,
        help="Load Playwright storage state before opening the page",
    )
    start_parser.add_argument("--wait-label", help="Override the label to wait for after the click")

    stop_parser = subparsers.add_parser("stop", help="Stop a selected AutoDL instance by clicking the stop button")
    stop_parser.add_argument("--url", default=DEFAULT_URL, help="Console URL to open")
    stop_parser.add_argument("--instance", required=True, help="Text that identifies the target instance row")
    stop_parser.add_argument("--headless", type=parse_bool, default=True)
    stop_parser.add_argument("--timeout-ms", type=int, default=30_000)
    stop_parser.add_argument("--screenshot", help="Optional screenshot output path")
    stop_parser.add_argument(
        "--storage-state",
        default=DEFAULT_STORAGE_STATE_PATH,
        help="Load Playwright storage state before opening the page",
    )
    stop_parser.add_argument("--wait-label", help="Override the label to wait for after the click")

    detail_parser = subparsers.add_parser("detail", help="Open the detail panel for a selected AutoDL instance")
    detail_parser.add_argument("--url", default=DEFAULT_URL, help="Console URL to open")
    detail_parser.add_argument("--instance", required=True, help="Text that identifies the target instance row")
    detail_parser.add_argument("--headless", type=parse_bool, default=True)
    detail_parser.add_argument("--timeout-ms", type=int, default=30_000)
    detail_parser.add_argument("--screenshot", help="Optional screenshot output path")
    detail_parser.add_argument(
        "--storage-state",
        default=DEFAULT_STORAGE_STATE_PATH,
        help="Load Playwright storage state before opening the page",
    )

    status_parser = subparsers.add_parser("status", help="Capture a status snapshot of the AutoDL console page")
    status_parser.add_argument("--url", default=DEFAULT_URL, help="Console URL to open")
    status_parser.add_argument("--headless", type=parse_bool, default=True)
    status_parser.add_argument("--timeout-ms", type=int, default=30_000)
    status_parser.add_argument("--screenshot", help="Optional screenshot output path")
    status_parser.add_argument(
        "--storage-state",
        default=DEFAULT_STORAGE_STATE_PATH,
        help="Load Playwright storage state before opening the page",
    )
    status_parser.add_argument("--save-storage-state", help="Write Playwright storage state after the run")
    status_parser.add_argument("--max-items", type=int, default=80)

    balance_parser = subparsers.add_parser("balance", help="Query the current AutoDL account balance")
    balance_parser.add_argument("--url", default=BALANCE_URL, help="Income/expense page URL to open")
    balance_parser.add_argument("--headless", type=parse_bool, default=True)
    balance_parser.add_argument("--timeout-ms", type=int, default=30_000)
    balance_parser.add_argument("--screenshot", help="Optional screenshot output path")
    balance_parser.add_argument(
        "--storage-state",
        default=DEFAULT_STORAGE_STATE_PATH,
        help="Load Playwright storage state before opening the page",
    )

    list_parser = subparsers.add_parser("list", help="List visible instance tables from the AutoDL console page")
    list_parser.add_argument("--url", default=DEFAULT_URL, help="Console URL to open")
    list_parser.add_argument("--headless", type=parse_bool, default=True)
    list_parser.add_argument("--timeout-ms", type=int, default=30_000)
    list_parser.add_argument("--screenshot", help="Optional screenshot output path")
    list_parser.add_argument(
        "--storage-state",
        default=DEFAULT_STORAGE_STATE_PATH,
        help="Load Playwright storage state before opening the page",
    )
    list_parser.add_argument("--save-storage-state", help="Write Playwright storage state after the run")
    list_parser.add_argument("--max-tables", type=int, default=8)
    list_parser.add_argument(
        "--query",
        "--filter",
        dest="query",
        help="Broad substring filter across instance id, name, status, spec, billing, lifecycle, and host info",
    )
    list_parser.add_argument("--site", help="Substring filter for the region/site")
    list_parser.add_argument("--host", help="Substring filter for the host name")
    list_parser.add_argument("--gpu-model", help="Substring filter for the GPU model")
    list_parser.add_argument("--gpu-driver", help="Substring filter for the GPU driver version")
    list_parser.add_argument("--cuda-version", help="Substring filter for the CUDA version")
    list_parser.add_argument("--status", help="Substring filter for the instance power state or GPU supply state")
    list_parser.add_argument("--min-gpu-free", type=int, help="Require at least this many free GPUs on the host")
    list_parser.add_argument(
        "--min-data-disk-expandable-gb",
        type=int,
        help="Require at least this many expandable data disk gigabytes on the host",
    )
    list_parser.add_argument("--sort-by", choices=LIST_SORT_CHOICES, help="Sort the filtered list by a normalized field")
    list_parser.add_argument("--sort-order", choices=("asc", "desc"), default="asc", help="Sort direction")
    list_parser.add_argument("--limit", type=int, help="Return at most this many matched instances")

    auth_parser = subparsers.add_parser(
        "auth",
        help="Open the AutoDL console, wait for manual login, and save storage state",
    )
    auth_parser.add_argument("--url", default=DEFAULT_URL, help="Console URL to open")
    auth_parser.add_argument("--headless", type=parse_bool, default=False)
    auth_parser.add_argument(
        "--pause-seconds",
        type=int,
        default=120,
        help="Maximum time to wait for login confirmation before saving storage state",
    )
    auth_parser.add_argument("--timeout-ms", type=int, default=30_000)
    auth_parser.add_argument(
        "--profile-dir",
        default=DEFAULT_AUTH_PROFILE_DIR,
        help="Persistent browser profile directory used for auth",
    )
    auth_parser.add_argument(
        "--storage-state",
        default=DEFAULT_STORAGE_STATE_PATH,
        help="Load an existing Playwright storage state before opening the page",
    )
    auth_parser.add_argument(
        "--save-storage-state",
        default=DEFAULT_STORAGE_STATE_PATH,
        help="Write Playwright storage state after the pause",
    )

    return parser


def _labels_for_action(args: argparse.Namespace) -> tuple[str, ...]:
    if args.command == "start":
        return START_LABELS if args.mode == "gpu" else ("更多",)
    if args.command == "stop":
        return STOP_LABELS
    if args.command == "detail":
        return ("查看详情",)
    raise ValueError(f"Unsupported action command: {args.command}")


def _run_run_command(args: argparse.Namespace) -> dict[str, object]:
    steps = load_steps(args.steps, args.steps_file)
    return asyncio.run(
        run_steps(
            url=args.url,
            steps=steps,
            headless=bool(args.headless),
            timeout_ms=args.timeout_ms,
            screenshot_path=args.screenshot,
            storage_state_path=args.storage_state,
            save_storage_state_path=args.save_storage_state,
        )
    )


def _run_inspect_command(args: argparse.Namespace) -> dict[str, object]:
    return asyncio.run(
        open_and_inspect(
            url=args.url,
            headless=bool(args.headless),
            timeout_ms=args.timeout_ms,
            screenshot_path=args.screenshot,
            storage_state_path=args.storage_state,
            max_items=args.max_items,
            save_storage_state_path=args.save_storage_state,
        )
    )


def _run_instance_action_command(args: argparse.Namespace) -> dict[str, object]:
    return asyncio.run(run_instance_action(args, _labels_for_action(args), args.command))


def _run_status_command(args: argparse.Namespace) -> dict[str, object]:
    return asyncio.run(run_status(args))


def _run_balance_command(args: argparse.Namespace) -> dict[str, object]:
    return asyncio.run(run_balance(args))


def _run_list_command(args: argparse.Namespace) -> dict[str, object]:
    return asyncio.run(
        run_list(
            url=args.url,
            headless=bool(args.headless),
            timeout_ms=args.timeout_ms,
            screenshot_path=args.screenshot,
            storage_state_path=args.storage_state,
            max_tables=args.max_tables,
            query=args.query,
            site=args.site,
            host=args.host,
            gpu_model=args.gpu_model,
            gpu_driver=args.gpu_driver,
            cuda_version=args.cuda_version,
            status=args.status,
            min_gpu_free=args.min_gpu_free,
            min_data_disk_expandable_gb=args.min_data_disk_expandable_gb,
            sort_by=args.sort_by,
            sort_order=args.sort_order,
            limit=args.limit,
            save_storage_state_path=args.save_storage_state,
        )
    )


def _run_auth_command(args: argparse.Namespace) -> dict[str, object]:
    return asyncio.run(
        run_auth(
            url=args.url,
            headless=bool(args.headless),
            pause_seconds=args.pause_seconds,
            timeout_ms=args.timeout_ms,
            storage_state_path=args.storage_state,
            browser_profile_dir=args.profile_dir,
            save_storage_state_path=args.save_storage_state,
        )
    )


COMMAND_HANDLERS = {
    "run": _run_run_command,
    "inspect": _run_inspect_command,
    "start": _run_instance_action_command,
    "stop": _run_instance_action_command,
    "detail": _run_instance_action_command,
    "status": _run_status_command,
    "balance": _run_balance_command,
    "list": _run_list_command,
    "auth": _run_auth_command,
}


def _command_error_payload(exc: Exception) -> dict[str, object]:
    error_type = type(exc).__name__
    retryable = error_type in {"TimeoutError", "PlaywrightTimeoutError"}
    return {
        "success": False,
        "error": {
            "type": error_type,
            "message": str(exc),
            "retryable": retryable,
        },
    }


def run_command(args: argparse.Namespace) -> dict[str, object]:
    try:
        handler = COMMAND_HANDLERS[args.command]
    except KeyError as exc:
        raise ValueError(f"Unsupported command: {args.command}") from exc
    return handler(args)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    storage_state_check: dict[str, object] | None = None
    if args.command != "auth" and getattr(args, "storage_state", None):
        storage_state_check = inspect_storage_state_cookie_expiry(args.storage_state)
        if storage_state_check.get("status") in {"missing", "invalid", "expired"}:
            result = {
                "success": False,
                "reason": storage_state_check.get("reason") or "Storage state cookie check failed",
                "storage_state_check": storage_state_check,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1

        if storage_state_check.get("status") == "expiring_soon":
            next_expiry = storage_state_check.get("next_expiry") or {}
            print(
                "Warning: AutoDL storage_state cookies are expiring soon: "
                f"{next_expiry.get('name')} at {next_expiry.get('expires_at_utc')}",
                file=sys.stderr,
            )

    try:
        ensure_browser_installed()
        result = run_command(args)
    except Exception as exc:
        result = _command_error_payload(exc)

    if storage_state_check is not None and isinstance(result, dict):
        result["storage_state_check"] = storage_state_check

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and result.get("success") is False:
        return 1
    return 0
