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


def _create_numbered_run_dir(started_at):
    scenario_dir = ROOT_DIR / "device_runs" / _device_name() / "army_training_quantity"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    numbered = []
    legacy_count = 0
    for path in scenario_dir.iterdir():
        if not path.is_dir():
            continue
        match = re.fullmatch(r"(\d+)_\d{8}_\d{6}", path.name)
        if match:
            numbered.append(int(match.group(1)))
        elif re.fullmatch(r"\d{8}_\d{6}", path.name):
            legacy_count += 1

    run_number = max(max(numbered, default=0), legacy_count) + 1
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    while True:
        run_dir = scenario_dir / f"{run_number}_{timestamp}"
        try:
            run_dir.mkdir()
            return run_dir
        except FileExistsError:
            run_number += 1


def _capture_run_screen(run_dir, name):
    result = {"file": f"{name}.png", "captured_at": datetime.now(timezone.utc).isoformat()}
    try:
        import cv2

        from army_training_live_e2e import capture_primary_monitor

        frame, origin = capture_primary_monitor()
        path = run_dir / result["file"]
        if not cv2.imwrite(str(path), frame):
            raise OSError("image_write_failed")
        result.update(
            status="saved",
            frame_size=[int(frame.shape[1]), int(frame.shape[0])],
            monitor_origin=list(origin),
        )
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    return result


def prepare_test_profile(
    profile_id=TEST_PROFILE_ID, unit_type=UNIT_TYPE, global_level=GLOBAL_LEVEL, match_number=MATCH_NUMBER,
    finished_training=False,
):
    from army_training_process import Slot, TrainingGoal, enqueue_training_goal, rearm_training_goal
    from army_state import army_state_path, load_army_state, open_training
    from task_controller import ACTIVE_STATUSES
    from army_training_manager import _load_or_create_queue
    from task_controller import save_task_queue

    if profile_id != "test" or not finished_training:
        raise E2EError("Test goal preparation requires confirmed idle for the test profile.")
    state_path = army_state_path(profile_id, ROOT_DIR / "profiles")
    marker = open_training(load_army_state(state_path))
    if marker is not None:
        raise E2EError("Test preflight reported completion but the open-training marker remains.")
    queue, queue_path = _load_or_create_queue(profile_id, ROOT_DIR / "profiles")
    has_unrelated_active_task = any(
        task["status"] in ACTIVE_STATUSES
        and (marker is None or task["task_id"] != marker.get("task_id"))
        for task in queue["tasks"]
    )
    if queue["paused"] or has_unrelated_active_task:
        raise E2EError("Test profile has an active or paused task. Inspect it before cleanup; no tasks were deleted.")

    task = enqueue_training_goal(
        queue,
        TrainingGoal(profile_id, Slot(unit_type, global_level, match_number)),
        datetime.now(timezone.utc),
    )
    if task["status"] == "completed":
        task = rearm_training_goal(queue, task["task_id"], datetime.now(timezone.utc))
    save_task_queue(queue, queue_path)
    return task


def run_e2e():
    if TEST_PROFILE_ID != "test":
        raise E2EError("Unmarked training completion is restricted to the test profile.")
    print(
        f"Preparing live Barracks test for profile {TEST_PROFILE_ID!r}: "
        f"{UNIT_TYPE}, level {GLOBAL_LEVEL}, match {MATCH_NUMBER}, quantity {TRAINING_QUANTITY}."
    )
    print("Live scope: desktop test account, Guardsmen selected; finish existing training using owned speedups, then train one goal. No purchases or gold.")
    run_dir = _create_numbered_run_dir(datetime.now())
    environment = {**os.environ, "TBA_RUN_DIR": str(run_dir), "TBA_PROFILE_ID": TEST_PROFILE_ID}
    finish_command = [
        PYTHON, ROOT_DIR / "army_training_manager.py", "--profile", TEST_PROFILE_ID,
        "execute", "--execute", "--confirm", "EXECUTE ARMY TRAINING",
        "--finish-active-for-test", "--navigate-only",
    ]
    finish_result = None
    try:
        finish_result = subprocess.run(
            [str(part) for part in finish_command], cwd=ROOT_DIR, capture_output=True,
            text=True, encoding="utf-8", errors="replace", check=False, env=environment,
        )
        finish_report = json.loads(finish_result.stdout)
        if not isinstance(finish_report, dict):
            raise ValueError("Pre-test check did not return a JSON object.")
    except (OSError, ValueError) as error:
        finish_report = {"status": "PREFLIGHT_OUTPUT_INVALID", "reason": f"{type(error).__name__}: {error}"}
    preflight_output = (finish_result.stdout or "") + (finish_result.stderr or "") if finish_result else finish_report["reason"]
    (run_dir / "preflight_log.txt").write_text(preflight_output, encoding="utf-8")
    (run_dir / "preflight.json").write_text(json.dumps(finish_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if finish_result is None or finish_result.returncode or finish_report.get("status") not in {
        "TRAINING_IDLE_FOR_TEST", "TRAINING_FINISHED_FOR_TEST",
    }:
        (run_dir / "report.json").write_text(json.dumps({
            "status": "FINISH_PREFLIGHT_FAILED", "live_test_status": "FAILED_OR_UNCERTAIN",
            "finish": finish_report, "test_profile": TEST_PROFILE_ID, "run_dir": str(run_dir.resolve()),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise E2EError(
            f"Pre-test Barracks check did not confirm idle ({finish_report.get('status')}): "
            f"{finish_report.get('reason', finish_report.get('blockers', 'no details'))}. "
            f"The test goal was not added. Evidence: {run_dir}"
        )
    task = prepare_test_profile(finished_training=True)
    command = [
        PYTHON, ROOT_DIR / "army_training_manager.py",
        "--profile", TEST_PROFILE_ID,
        "execute", "--execute", "--confirm", "EXECUTE ARMY TRAINING",
        "--quantity", TRAINING_QUANTITY,
        "--test-task-id", task["task_id"],
    ]
    print(f"Queued {task['task_id']} ({UNIT_TYPE}, level {GLOBAL_LEVEL}, match {MATCH_NUMBER}, quantity {TRAINING_QUANTITY}).")
    print("Starting live sequence: the manager will navigate from the world map, then submit one training order.")

    completed = None
    launch_error = None
    try:
        completed = subprocess.run(
            [str(part) for part in command],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
    except OSError as error:
        launch_error = f"{type(error).__name__}: {error}"
    output = ""
    if completed is not None:
        output = (completed.stdout or "") + (completed.stderr or "")
    elif launch_error:
        output = launch_error
    trace_path = run_dir / "workflow_trace.jsonl"
    checkpoint_events = []
    if trace_path.is_file():
        for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                output += f"\nInvalid workflow trace JSON: {raw_line}"
                continue
            checkpoint_events.append(event)
            output += f"\n{event.get('timestamp', 'unknown_time')} [checkpoint] {json.dumps(event, ensure_ascii=False, sort_keys=True)}"
    (run_dir / "log.txt").write_text(output, encoding="utf-8")
    try:
        report = json.loads(completed.stdout) if completed is not None else None
        if not isinstance(report, dict):
            raise json.JSONDecodeError("manager did not return a JSON object", output, 0)
    except json.JSONDecodeError:
        report = {
            "status": "MANAGER_OUTPUT_INVALID",
            "returncode": completed.returncode if completed is not None else None,
            "output": output,
        }
    report.update(
        finish=finish_report,
        test_profile=TEST_PROFILE_ID,
        expected_quantity=TRAINING_QUANTITY,
        test_task_id=task["task_id"],
        run_dir=str(run_dir.resolve()),
        checkpoint_event_count=len(checkpoint_events),
        checkpoint_events=checkpoint_events,
        workflow_trace_file=trace_path.name if trace_path.is_file() else None,
    )
    if completed is not None and completed.returncode == 0 and report.get("status") == "START_CONFIRMED" and report.get("quantity_confirmed") == TRAINING_QUANTITY:
        report["live_test_status"] = "PASSED"
    else:
        report["live_test_status"] = "FAILED_OR_UNCERTAIN"
        evidence_files = any(run_dir.glob("checkpoint_*.png"))
        if not evidence_files:
            failure_capture = _capture_run_screen(run_dir, "failure")
            report["failure_screen"] = failure_capture
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
