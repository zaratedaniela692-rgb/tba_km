#!/usr/bin/env python3
"""Run the configured army E2E stages from the visible desktop world map."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from task_controller import DEFAULT_PROFILE_ID


ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)

# Edit these switches here; this wrapper intentionally has no command-line options.
EXECUTE_GAME_ACTIONS = False
RUN_NAVIGATION = True
RUN_ARMY_SLOTS = True
RUN_ARMY_SCROLL = False
RUN_SPECIALIST_TRAIN = False
RUN_QUEUED_TRAINING_TEST = False
TRAINING_QUANTITY = 100
TEST_PROFILE_ID = DEFAULT_PROFILE_ID

DEVICE_TEST = ROOT_DIR / "tools" / "device_test.py"
RUNS_DIR = ROOT_DIR / "device_runs"


class E2EError(RuntimeError):
    """The configured E2E sequence cannot safely continue."""


def _run(command, runner=subprocess.run):
    completed = runner(
        [str(part) for part in command],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="" if completed.stderr.endswith("\n") else "\n")
    if completed.returncode:
        raise E2EError(f"Command failed with exit code {completed.returncode}: {' '.join(map(str, command))}")
    return completed


def _device_name():
    raw = os.environ.get("COMPUTERNAME") or "device"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_") or "device"


def _run_device_scenario(name, profile_id=None, execute=False, runner=subprocess.run):
    command = [PYTHON, DEVICE_TEST, name, "--no-git", "--no-push", "--force", "--delay", "0"]
    if profile_id is not None:
        command.extend(("--profile", profile_id))
    if execute:
        command.append("--execute")
    print(f"\n=== {name}{' (execute)' if execute else ''} ===")
    return _run(command, runner)


def _queued_training_scenario(profile_id, quantity):
    return {
        "name": "army_training_quantity",
        "description": f"Execute one queued army goal with quantity {quantity}",
        "prepare": "World map visible; one pending army stock goal is configured for this profile.",
        "steps": [{
            "name": "execute_one_goal",
            "execute_argv": [
                str(PYTHON), str(ROOT_DIR / "army_training_manager.py"),
                "--profile", profile_id, "execute", "--execute",
                "--confirm", "EXECUTE ARMY TRAINING", "--quantity", str(quantity),
            ],
        }],
    }


def _assert_one_pending_army_goal(profile_id):
    from army_state import army_state_path, load_army_state, open_training
    from task_controller import ACTIVE_STATUSES, load_task_queue, task_queue_path

    state_path = army_state_path(profile_id)
    if open_training(load_army_state(state_path)) is not None:
        raise E2EError("An open-training marker exists; refusing to run a new queued training test.")
    queue_path = task_queue_path(profile_id)
    if not queue_path.is_file():
        raise E2EError(f"No task queue exists for profile {profile_id!r}; enqueue one goal first.")
    queue = load_task_queue(queue_path, expected_profile_id=profile_id)
    if queue["paused"] or any(task["status"] in ACTIVE_STATUSES for task in queue["tasks"]):
        raise E2EError("The profile queue is paused or has active tasks; refusing a new training test.")
    pending = [
        task for task in queue["tasks"]
        if task["task_type"] == "army_training"
        and task["payload"].get("goal_kind") == "slot_stock_v1"
        and task["status"] in {"queued", "waiting_resources"}
    ]
    if len(pending) != 1:
        raise E2EError(f"Expected exactly one pending army stock goal, found {len(pending)}.")
    slot = pending[0]["payload"].get("slot", {})
    if slot.get("unit_type") != "guardsmen":
        raise E2EError("The queued-training E2E currently supports only the verified guardsmen category.")


def _run_queued_training(profile_id, runner=subprocess.run):
    from tools import device_test

    _assert_one_pending_army_goal(profile_id)
    context = device_test.Context(
        root=ROOT_DIR,
        device=_device_name(),
        execute=True,
        profile=profile_id,
        delay=0,
        git=None,
        push=False,
        force=True,
        run_fn=runner,
    )
    report = device_test.run_scenario(_queued_training_scenario(profile_id, TRAINING_QUANTITY), context, execute=True)
    if report["status"] != device_test.OK:
        raise E2EError(f"Queued training device test failed: {report['status']} ({report['run_dir']}).")
    output = report["steps"][0].get("output_tail", "")
    try:
        manager_report = json.loads(output)
    except json.JSONDecodeError as error:
        raise E2EError(f"Manager did not return valid JSON ({report['run_dir']}).") from error
    if manager_report.get("status") != "START_CONFIRMED":
        raise E2EError(
            f"Expected a confirmed training start, got {manager_report.get('status')!r}; "
            f"inspect {report['run_dir']} before retrying."
        )
    print(f"Training start confirmed with quantity {TRAINING_QUANTITY}: {report['run_dir']}")
    return report


def _latest_training_state(device=None):
    device = device or _device_name()
    scenario_dir = RUNS_DIR / device / "army_slots"
    runs = [path for path in scenario_dir.iterdir() if path.is_dir()] if scenario_dir.is_dir() else []
    if not runs:
        raise E2EError("No army_slots device-test report exists; refusing the training-start stage.")
    latest_run = max(runs, key=lambda path: path.stat().st_mtime)
    report_path = latest_run / "army_slots.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise E2EError(f"Cannot read the latest army_slots report at {report_path}.") from error
    return report.get("training_state", {}).get("status"), report_path


def run_e2e(runner=subprocess.run, training_state_reader=_latest_training_state):
    print("Army E2E: keep the desktop game foregrounded on the world map with the player name visible.")
    print(f"Game input enabled: {EXECUTE_GAME_ACTIONS}")
    profile_id = TEST_PROFILE_ID
    print(f"Using profile: {profile_id}")

    _run_device_scenario("preflight", runner=runner)
    if RUN_QUEUED_TRAINING_TEST:
        if not EXECUTE_GAME_ACTIONS:
            raise E2EError("Enable EXECUTE_GAME_ACTIONS before RUN_QUEUED_TRAINING_TEST.")
        _run_queued_training(profile_id, runner=runner)
        print("\nConfigured army E2E stages completed. No Speed Up items were used.")
        return 0

    if RUN_NAVIGATION:
        _run_device_scenario("army_navigate", profile_id, execute=EXECUTE_GAME_ACTIONS, runner=runner)
        if not EXECUTE_GAME_ACTIONS:
            print("Navigation was previewed only. Enable EXECUTE_GAME_ACTIONS to open Barracks and continue.")
            return 0
    if RUN_ARMY_SLOTS:
        _run_device_scenario("army_slots", profile_id, runner=runner)

    if RUN_ARMY_SCROLL and EXECUTE_GAME_ACTIONS:
        _run_device_scenario("army_scroll", profile_id, runner=runner)

    if RUN_SPECIALIST_TRAIN and EXECUTE_GAME_ACTIONS:
        training_status, report_path = training_state_reader()
        print(f"Latest training-state evidence: {report_path} ({training_status})")
        if training_status == "active":
            print("Skipping Specialist training: an order is already active.")
        elif training_status != "idle":
            raise E2EError(
                f"Training state is {training_status!r}; refusing to start a test order. Inspect the saved report first."
            )
        else:
            _run_device_scenario("army_specialist_train", profile_id, execute=True, runner=runner)

    print("\nConfigured army E2E stages completed. No Speed Up items were used.")
    return 0


def main():
    try:
        return run_e2e()
    except (E2EError, OSError) as error:
        print(f"Army E2E stopped: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
