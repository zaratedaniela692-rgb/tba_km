#!/usr/bin/env python3
"""Run the configured read-only Army scanner check against a reviewed fixture."""

import json
import sys
from pathlib import Path

import cv2

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import army_training_scanner
from ui_variants import resolve_variant

MODULE = "army_training_scanner"
SCENARIO = "completed_training_control"
VARIANT = "legacy"
FIXTURE = ROOT_DIR / "tests" / "data" / "army_training" / "training_complete_finish_button.png"


def run_check(snapshot_reader=army_training_scanner.read_army_training_snapshot_from_image):
    try:
        fixture_reference = FIXTURE.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        fixture_reference = str(FIXTURE)
    try:
        image = cv2.imread(str(FIXTURE), cv2.IMREAD_COLOR)
        if image is None:
            raise OSError(f"fixture_unreadable:{fixture_reference}")
        snapshot = snapshot_reader(image, variant=resolve_variant(VARIANT), include_numeric=False)
        passed = snapshot.get("status") == "completed" and snapshot.get("finish_button_detected") is True
        return {
            "status": "PASSED" if passed else "FAILED",
            "module": MODULE,
            "scenario": SCENARIO,
            "mode": "offline_fixture_read_only",
            "variant": VARIANT,
            "side_effects": [],
            "evidence_inputs": [fixture_reference],
            "artifacts_dir": None,
            "result": {
                "training_status": snapshot.get("status"),
                "button_state": snapshot.get("button_state"),
                "finish_button_detected": snapshot.get("finish_button_detected"),
                "finish_button_point": snapshot.get("finish_button_point"),
            },
        }
    except Exception as error:
        return {
            "status": "FAILED",
            "module": MODULE,
            "scenario": SCENARIO,
            "mode": "offline_fixture_read_only",
            "variant": VARIANT,
            "side_effects": [],
            "evidence_inputs": [fixture_reference],
            "artifacts_dir": None,
            "error": f"{type(error).__name__}: {error}",
        }


def main(argv=None, output=print):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        output(json.dumps({"status": "BLOCKED_ARGUMENTS", "module": MODULE, "mode": "offline_fixture_read_only"}))
        return 2
    report = run_check()
    output(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())