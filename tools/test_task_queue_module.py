#!/usr/bin/env python3
"""Run the configured in-memory task-queue readiness check."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from task_controller import create_task_queue, enqueue_task, get_next_task

MODULE = "task_queue"
SCENARIO = "army_hold_allows_other_task_type"
PROFILE_ID = "offline-wrapper-profile"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
ARMY_TASK_ID = "offline-army-stock-goal"
OTHER_TASK_ID = "offline-building-task"


def run_check(selector=get_next_task):
    try:
        queue = create_task_queue(PROFILE_ID)
        enqueue_task(
            queue, "army_training", task_id=ARMY_TASK_ID, now=NOW,
            payload={"goal_kind": "slot_stock_v1", "slot": {"unit_type": "guardsmen", "global_level": 5, "match_number": 1}},
        )
        enqueue_task(queue, "building_upgrade", task_id=OTHER_TASK_ID, now=NOW)
        queue["army_training_hold"] = {
            "at": NOW.isoformat(), "task_id": ARMY_TASK_ID,
            "reason": "offline_fixture_hold_no_game_input",
        }
        selected = selector(queue, {}, now=NOW)
        passed = selected is not None and selected["task_id"] == OTHER_TASK_ID
        return {
            "status": "PASSED" if passed else "FAILED",
            "module": MODULE,
            "scenario": SCENARIO,
            "mode": "offline_in_memory",
            "profile_id": PROFILE_ID,
            "side_effects": ["in_memory_queue_selection_only"],
            "evidence_inputs": {"army_training_hold": queue["army_training_hold"]},
            "artifacts_dir": None,
            "result": {"selected_task_id": selected["task_id"] if selected else None},
        }
    except Exception as error:
        return {
            "status": "FAILED",
            "module": MODULE,
            "scenario": SCENARIO,
            "mode": "offline_in_memory",
            "profile_id": PROFILE_ID,
            "side_effects": ["in_memory_queue_selection_only"],
            "evidence_inputs": {},
            "artifacts_dir": None,
            "error": f"{type(error).__name__}: {error}",
        }


def main(argv=None, output=print):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        output(json.dumps({"status": "BLOCKED_ARGUMENTS", "module": MODULE, "mode": "offline_in_memory"}))
        return 2
    report = run_check()
    output(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())