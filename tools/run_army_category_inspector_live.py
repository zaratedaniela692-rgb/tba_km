#!/usr/bin/env python3
"""Capture and inspect the currently selected desktop Barracks category without clicks."""

import json
import os
import re
import sys
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
from army_training_live_e2e import capture_primary_monitor
from army_training_scanner import ArmyTrainingScannerError
from ui_variants import UIVariantError, resolve_variant

RUNS_DIR = ROOT_DIR / "device_runs"
EXPECTED_UNIT_TYPE = None


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


def run_live_inspection(capture_fn=None, run_dir_factory=None, output=print):
    """Capture one current desktop frame and produce a read-only inspection report."""
    capture_fn = capture_fn or capture_primary_monitor
    run_dir_factory = run_dir_factory or _create_run_dir
    run_dir = run_dir_factory()
    report = {
        "mode": "army_category_inspector_live",
        "status": "BLOCKED_CAPTURE",
        "actions_executed": False,
        "queue_modified": False,
        "expected_unit_type": EXPECTED_UNIT_TYPE,
        "git_sync": GIT_SYNC_RESULT,
    }
    try:
        frame, origin = capture_fn()
        report["frame_size"] = [int(frame.shape[1]), int(frame.shape[0])]
        report["monitor_origin"] = list(origin)
        if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
            report.update(status="BLOCKED_FRAME_SIZE", reason=f"expected_{EXPECTED_SIZE[0]}x{EXPECTED_SIZE[1]}")
        else:
            report.update(inspect_image(frame, expected_unit_type=EXPECTED_UNIT_TYPE, variant=resolve_variant()))
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