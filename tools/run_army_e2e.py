#!/usr/bin/env python3
"""Run the configured army E2E stages from the visible desktop world map."""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from task_controller import DEFAULT_PROFILE_ID

PYTHON = Path(sys.executable)

# Edit the intended target here. Running this script performs the configured live test.
UNIT_TYPE = "guardsmen"
GLOBAL_LEVEL = 7
MATCH_NUMBER = 1
TRAINING_QUANTITY = 100
TEST_PROFILE_ID = DEFAULT_PROFILE_ID


class E2EError(RuntimeError):
    """The configured E2E sequence cannot safely continue."""


def _device_name():
    raw = os.environ.get("COMPUTERNAME") or "device"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_") or "device"


def prepare_test_profile(profile_id=TEST_PROFILE_ID, unit_type=UNIT_TYPE, global_level=GLOBAL_LEVEL, match_number=MATCH_NUMBER):
    from army_training_process import Slot, TrainingGoal, enqueue_training_goal
    from army_state import army_state_path, load_army_state, open_training
    from task_controller import ACTIVE_STATUSES, load_task_queue, task_queue_path
    from army_training_manager import _load_or_create_queue
    from task_controller import save_task_queue

    state_path = army_state_path(profile_id)
    if open_training(load_army_state(state_path)) is not None:
        raise E2EError("Test profile has an open-training marker. Inspect the game; no tasks were deleted.")
    queue, queue_path = _load_or_create_queue(profile_id, ROOT_DIR / "profiles")
    if queue["paused"] or any(task["status"] in ACTIVE_STATUSES for task in queue["tasks"]):
        raise E2EError("Test profile has an active or paused task. Inspect it before cleanup; no tasks were deleted.")

    queue["tasks"] = []
    task = enqueue_training_goal(
        queue,
        TrainingGoal(profile_id, Slot(unit_type, global_level, match_number)),
        datetime.now(timezone.utc),
    )
    save_task_queue(queue, queue_path)
    return task


def run_e2e():
    print(
        f"Preparing live Barracks test for profile {TEST_PROFILE_ID!r}: "
        f"{UNIT_TYPE}, level {GLOBAL_LEVEL}, match {MATCH_NUMBER}, quantity {TRAINING_QUANTITY}."
    )
    print("Requirement: desktop game, intended account, Guardsmen category selected, no active training.")
    task = prepare_test_profile()
    command = [
        PYTHON, ROOT_DIR / "army_training_manager.py",
        "execute", "--execute", "--confirm", "EXECUTE ARMY TRAINING",
        "--quantity", TRAINING_QUANTITY,
    ]
    print(f"Queued {task['task_id']} ({UNIT_TYPE}, level {GLOBAL_LEVEL}, match {MATCH_NUMBER}, quantity {TRAINING_QUANTITY}).")
    print("Starting live sequence: the manager will navigate from the world map, then submit one training order.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = ROOT_DIR / "device_runs" / _device_name() / "army_training_quantity" / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)
    completed = subprocess.run(
        [str(part) for part in command],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    (run_dir / "log.txt").write_text(output, encoding="utf-8")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        report = {
            "status": "MANAGER_OUTPUT_INVALID",
            "returncode": completed.returncode,
            "output": output,
        }
    report.update(
        test_profile=TEST_PROFILE_ID,
        expected_quantity=TRAINING_QUANTITY,
        test_task_id=task["task_id"],
        run_dir=str(run_dir.resolve()),
    )
    if report.get("status") == "START_CONFIRMED" and report.get("quantity_confirmed") == TRAINING_QUANTITY:
        report["live_test_status"] = "PASSED"
    else:
        report["live_test_status"] = "FAILED_OR_UNCERTAIN"
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output, end="" if output.endswith("\n") else "\n")
    print(f"Live test {report['live_test_status']}; evidence: {run_dir}")
    return 0 if report["live_test_status"] == "PASSED" else 2


def main():
    try:
        return run_e2e()
    except (E2EError, OSError) as error:
        print(f"Army E2E stopped: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    try:
        raise SystemExit(run_e2e())
    except (E2EError, OSError, ValueError) as error:
        print(f"Army E2E stopped: {error}", file=sys.stderr)
        raise SystemExit(2)
