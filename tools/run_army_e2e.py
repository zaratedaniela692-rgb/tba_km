#!/usr/bin/env python3
"""Run the configured army E2E stages from the visible desktop world map."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)

# Edit these switches here; this wrapper intentionally has no command-line options.
EXECUTE_GAME_ACTIONS = False
RUN_NAVIGATION = True
RUN_ARMY_SLOTS = True
RUN_ARMY_SCROLL = False
RUN_SPECIALIST_TRAIN = False

DEVICE_TEST = ROOT_DIR / "tools" / "device_test.py"
CLIENT_ROUTER = ROOT_DIR / "client_router.py"
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


def resolve_desktop_profile(route_output):
    try:
        route = json.loads(route_output)
    except json.JSONDecodeError as error:
        raise E2EError("Foreground profile router returned invalid JSON; no game action was started.") from error
    if route.get("status") != "routed" or route.get("client_id") != "desktop":
        raise E2EError(
            "A unique registered desktop profile is required; "
            f"router status={route.get('status')!r}, client={route.get('client_id')!r}, "
            f"reason={route.get('reason')!r}. No profile was created and no game action was started."
        )
    profile_id = route.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise E2EError("Foreground router did not return a usable profile ID.")
    return profile_id


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
    route_result = _run([PYTHON, CLIENT_ROUTER, "--once", "--register-missing"], runner)
    profile_id = resolve_desktop_profile(route_result.stdout)
    print(f"Using registered profile: {profile_id}")

    _run_device_scenario("preflight", runner=runner)
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
