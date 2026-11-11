#!/usr/bin/env python3
"""Run an offline stock-goal observation -> reconciliation -> queue selection flow."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from army_training_process import (
    NumericReading,
    Slot,
    SlotObservation,
    TrainingGoal,
    enqueue_training_goal,
    reconcile_training_goal,
)
from speedup import DialogReading, InventoryRow, finish_with_speedups
from speedup_readings import ParsedReading
from task_controller import create_task_queue, get_next_task

MODULE = "army_training_and_task_queue"
SCENARIO = "offline_stock_goal_reconciliation_and_dispatch"
PROFILE_ID = "offline-e2e-profile"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
SLOT = Slot("guardsmen", 5, 1)
SPEEDUP_DURATION = 3600
INITIAL_TIMER = 3600
OWNED_SPEEDUPS = 11


def run_check(speedup_finisher=finish_with_speedups, reconcile=reconcile_training_goal, select=get_next_task):
    try:
        dialog = {"remaining": INITIAL_TIMER, "quantity": OWNED_SPEEDUPS}
        clicks = []

        def capture():
            return dict(dialog)

        def read_dialog(frame):
            return DialogReading(
                ParsedReading(str(frame["remaining"]), frame["remaining"], 100.0, "ok"),
                (InventoryRow(SPEEDUP_DURATION, frame["quantity"], (SPEEDUP_DURATION, 0)),),
                True,
                0,
            )

        def click_owned_item(point):
            if point != (SPEEDUP_DURATION, 0) or dialog["quantity"] <= 0:
                raise RuntimeError("unexpected_or_unowned_speedup")
            clicks.append(point)
            dialog["quantity"] -= 1
            dialog["remaining"] = max(0, dialog["remaining"] - SPEEDUP_DURATION)

        speedup_result = speedup_finisher(
            capture, read_dialog, click_owned_item, lambda _direction: None,
            stop_fn=lambda: None, sleep_fn=lambda _: None, dry_run=False,
        )
        queue = create_task_queue(PROFILE_ID)
        goal = TrainingGoal(PROFILE_ID, SLOT)
        task = enqueue_training_goal(queue, goal, NOW)
        observation = SlotObservation(
            PROFILE_ID, SLOT, NOW, "synthetic_offline_observation", "idle",
            NumericReading(5, 99, "V"), NumericReading(0, 96, "0"),
            {4: NumericReading(1000, 96, "1000"), 5: NumericReading(700, 96, "700")},
            True,
        )
        decision = reconcile(queue, task["task_id"], observation, NOW, dry_run=False)
        selected = select(queue, {}, now=NOW)
        passed = (
            speedup_result.status == "FINISHED"
            and len(clicks) == 1
            and dialog["remaining"] == 0
            and decision.reason == "stock_below_threshold"
            and selected is not None and selected["task_id"] == task["task_id"]
        )
        return {
            "status": "PASSED" if passed else "FAILED",
            "module": MODULE,
            "scenario": SCENARIO,
            "mode": "offline_injected_callbacks",
            "profile_id": PROFILE_ID,
            "side_effects": ["in_memory_speedup_dialog_simulation", "in_memory_task_queue_only"],
            "evidence_inputs": {
                "source": observation.source, "slot": SLOT.__dict__,
                "owned_speedups": {SPEEDUP_DURATION: OWNED_SPEEDUPS}, "initial_timer_seconds": INITIAL_TIMER,
            },
            "artifacts_dir": None,
            "result": {
                "simulated_finish_status": speedup_result.status,
                "simulated_click_count": len(clicks),
                "decision": decision.reason,
                "process_state": queue["tasks"][0]["payload"]["process"]["state"],
                "selected_task_id": selected["task_id"] if selected else None,
            },
        }
    except Exception as error:
        return {
            "status": "FAILED",
            "module": MODULE,
            "scenario": SCENARIO,
            "mode": "offline_injected_callbacks",
            "profile_id": PROFILE_ID,
            "side_effects": ["in_memory_speedup_dialog_simulation", "in_memory_task_queue_only"],
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