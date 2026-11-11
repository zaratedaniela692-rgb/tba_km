#!/usr/bin/env python3
"""Run one parameterless, navigation-only live check for the desktop game."""

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

from army_training_navigation import open_army_training_screen
from client_router import observe_foreground_profile


RUNS_DIR = ROOT_DIR / "device_runs"


def _device_name():
    raw = os.environ.get("COMPUTERNAME") or "device"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_") or "device"


def _create_run_dir(now=None):
    now = now or datetime.now()
    parent = RUNS_DIR / _device_name() / "army_navigation"
    parent.mkdir(parents=True, exist_ok=True)
    run_dir = parent / now.strftime("%Y%m%d_%H%M%S_%f")
    run_dir.mkdir()
    return run_dir


def _route_dict(route):
    if is_dataclass(route):
        return asdict(route)
    if isinstance(route, dict):
        return route
    return vars(route)


def _write_report(run_dir, report, output):
    report_path = run_dir / "report.json"
    report["run_dir"] = str(run_dir.resolve())
    report["report_file"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") != "BARRACKS_OPENED":
        publish_failure_reports(ROOT_DIR, run_dir, output)


def _save_failure_screen(run_dir):
    result = {"file": "failure.png", "captured_at": datetime.now().astimezone().isoformat()}
    try:
        import cv2

        from army_training_live_e2e import capture_primary_monitor

        frame, origin = capture_primary_monitor()
        if not cv2.imwrite(str(run_dir / result["file"]), frame):
            raise OSError("image_write_failed")
        result.update(
            status="saved",
            frame_size=[int(frame.shape[1]), int(frame.shape[0])],
            monitor_origin=list(origin),
        )
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    return result


def _run_navigation_with_trace(navigate_fn, run_dir, profile_id):
    env_keys = ("TBA_RUN_DIR", "TBA_PROFILE_ID")
    previous = {key: os.environ.get(key) for key in env_keys}
    os.environ["TBA_RUN_DIR"] = str(run_dir)
    os.environ["TBA_PROFILE_ID"] = profile_id
    try:
        return navigate_fn(execute=True)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_live_navigation(
    route_fn=None,
    navigate_fn=None,
    run_dir_factory=None,
    output=print,
):
    """Route the foreground player, then attempt navigation once without queue work."""
    route_fn = route_fn or observe_foreground_profile
    navigate_fn = navigate_fn or open_army_training_screen
    run_dir_factory = run_dir_factory or _create_run_dir
    run_dir = run_dir_factory()
    report = {
        "mode": "army_navigation_live",
        "status": "BLOCKED_ROUTE",
        "actions_executed": False,
        "queue_modified": False,
        "git_sync": GIT_SYNC_RESULT,
        "route": None,
        "navigation": None,
    }

    try:
        route = route_fn()
    except Exception as error:
        report["reason"] = f"foreground_route_failed:{type(error).__name__}:{error}"
        _write_report(run_dir, report, output)
        return 2

    route_data = _route_dict(route)
    report["route"] = route_data
    profile_id = route_data.get("profile_id")
    if (
        route_data.get("status") != "routed"
        or route_data.get("client_id") != "desktop"
        or not isinstance(profile_id, str)
        or not profile_id.strip()
    ):
        report["reason"] = "foreground_route_must_resolve_one_desktop_profile"
        _write_report(run_dir, report, output)
        return 2

    try:
        navigation = _run_navigation_with_trace(navigate_fn, run_dir, profile_id)
    except Exception as error:
        if not any(run_dir.glob("checkpoint_*.png")):
            report["failure_screen"] = _save_failure_screen(run_dir)
        report.update(
            status="NAVIGATION_ERROR",
            actions_executed="unknown",
            reason=f"navigation_failed_do_not_retry:{type(error).__name__}:{error}",
        )
        _write_report(run_dir, report, output)
        return 2

    report["navigation"] = navigation
    report["actions_executed"] = bool(navigation.get("actions_executed", False))
    if navigation.get("status") == "BARRACKS_OPENED" and navigation.get("visible_slots", 0) > 0:
        report["status"] = "BARRACKS_OPENED"
    else:
        report["status"] = navigation.get("status", "NAVIGATION_UNCONFIRMED")
        report["reason"] = "navigation_did_not_confirm_barracks_slots_do_not_retry"
    _write_report(run_dir, report, output)
    return 0 if report["status"] == "BARRACKS_OPENED" else 2


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        print("This live wrapper takes no arguments; edit its constants in the source if needed.", file=sys.stderr)
        return 2
    return run_live_navigation()


if __name__ == "__main__":
    raise SystemExit(main())