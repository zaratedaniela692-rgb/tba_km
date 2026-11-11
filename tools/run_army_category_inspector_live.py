#!/usr/bin/env python3
"""Capture and inspect the currently selected desktop Barracks category without clicks."""

import json
import os
import re
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.run_live_test_git import prepare_live_checkout, publish_failure_reports

GIT_SYNC_RESULT = {"status": "not_run"}
if __name__ == "__main__" and len(sys.argv) == 1:
    GIT_SYNC_RESULT = prepare_live_checkout(ROOT_DIR, Path(__file__))

from army_training_inspector import EXPECTED_SIZE, inspect_image
from army_training_navigation import ensure_army_training_screen
from army_training_live_e2e import capture_primary_monitor
from army_training_scanner import ArmyTrainingScannerError
from ui_variants import UIVariantError, resolve_variant
from client_router import observe_foreground_profile

RUNS_DIR = ROOT_DIR / "device_runs"
EXPECTED_UNIT_TYPE = None
OPEN_BARRACKS_IF_NEEDED = True


def _device_name():
    raw = os.environ.get("COMPUTERNAME") or "device"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_") or "device"


def _create_run_dir(now=None):
    now = now or datetime.now()
    parent = RUNS_DIR / _device_name() / "army_category_inspector"
    parent.mkdir(parents=True, exist_ok=True)
    run_dir = parent / now.strftime("%Y%m%d_%H%M%S_%f")
    run_dir.mkdir()
    return run_dir


def _write_report(run_dir, report, output):
    report_path = run_dir / "report.json"
    report["run_dir"] = str(run_dir.resolve())
    report["report_file"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") != "INSPECTED_READ_ONLY":
        publish_failure_reports(ROOT_DIR, run_dir, output)


def _route_dict(route):
    if is_dataclass(route):
        return asdict(route)
    if isinstance(route, dict):
        return route
    return vars(route)


def run_live_inspection(capture_fn=None, run_dir_factory=None, output=print, route_fn=None, ensure_fn=None):
    """Navigate to Barracks if needed, then inspect one frame without category or training input."""
    capture_fn = capture_fn or capture_primary_monitor
    run_dir_factory = run_dir_factory or _create_run_dir
    route_fn = route_fn or observe_foreground_profile
    ensure_fn = ensure_fn or ensure_army_training_screen
    run_dir = run_dir_factory()
    report = {
        "mode": "army_category_inspector_navigation_live",
        "status": "BLOCKED_ROUTE",
        "actions_executed": False,
        "queue_modified": False,
        "expected_unit_type": EXPECTED_UNIT_TYPE,
        "git_sync": GIT_SYNC_RESULT,
    }
    try:
        route = _route_dict(route_fn(register_missing=False))
        report["route"] = route
        profile_id = route.get("profile_id")
        if (
            route.get("status") != "routed"
            or route.get("client_id") != "desktop"
            or not isinstance(profile_id, str)
            or not profile_id.strip()
        ):
            report["reason"] = "foreground_route_must_resolve_one_desktop_profile"
            _write_report(run_dir, report, output)
            return 2

        env_keys = ("TBA_RUN_DIR", "TBA_PROFILE_ID")
        previous = {key: os.environ.get(key) for key in env_keys}
        os.environ["TBA_RUN_DIR"] = str(run_dir)
        os.environ["TBA_PROFILE_ID"] = profile_id
        try:
            screen = ensure_fn(
                execute=OPEN_BARRACKS_IF_NEEDED,
                capture_fn=capture_fn,
                variant=resolve_variant(),
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        report["navigation"] = screen.get("navigation")
        report["actions_executed"] = bool(screen.get("actions_executed", False))
        report["queue_modified"] = False
        if screen.get("status") != "BARRACKS_READY":
            report["status"] = screen.get("status", "BLOCKED_BARRACKS")
            report["reason"] = screen.get("layout_reason") or screen.get("reason") or report["status"]
            _write_report(run_dir, report, output)
            return 2

        frame, origin = screen["frame"], screen["origin"]
        report["frame_size"] = [int(frame.shape[1]), int(frame.shape[0])]
        report["monitor_origin"] = list(origin)
        if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
            report.update(status="BLOCKED_FRAME_SIZE", reason=f"expected_{EXPECTED_SIZE[0]}x{EXPECTED_SIZE[1]}")
        else:
            inspection = inspect_image(frame, expected_unit_type=EXPECTED_UNIT_TYPE, variant=resolve_variant())
            inspection["actions_executed"] = bool(report["actions_executed"] or inspection.get("actions_executed", False))
            report.update(inspection)
    except Exception as error:
        report["reason"] = f"inspection_failed:{type(error).__name__}:{error}"
    _write_report(run_dir, report, output)
    return 0 if report["status"] == "INSPECTED_READ_ONLY" else 2


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        print("This live wrapper takes no arguments; edit EXPECTED_UNIT_TYPE at the top if needed.", file=sys.stderr)
        return 2
    return run_live_inspection()


if __name__ == "__main__":
    raise SystemExit(main())