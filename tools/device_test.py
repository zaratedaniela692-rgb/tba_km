#!/usr/bin/env python3
"""Run supervised live game-window scenarios on a test PC and publish the evidence through git."""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
SCENARIOS_PATH = Path(__file__).with_name("device_test_scenarios.json")
PLAN_PATH = Path(__file__).with_name("device_test_plan.json")
SETTINGS_PATH = Path(__file__).with_name("device_test_settings.json")
RUNS_DIR_NAME = "device_runs"
KEEP_RUNS = 4  # the current run plus three earlier ones
MAX_SCENARIOS = 2  # every scenario adds many screenshots to the repository
STOP_FILE = Path.home() / ".tba_stop"
STEP_TIMEOUT_SECONDS = 600
GIT_TIMEOUT_SECONDS = 10
MAX_PREPARE_DELAY_SECONDS = 5
OUTPUT_LIMIT = 20000
PLACEHOLDERS = ("python", "run_dir", "profile")

OK, FAILED, BLOCKED, SKIPPED, UNCHANGED = "OK", "FAILED", "BLOCKED", "SKIPPED", "UNCHANGED"


class DeviceTestError(ValueError):
    """Invalid scenario registry or arguments."""


class Git:
    def __init__(self, root, runner=subprocess.run):
        self.root = Path(root)
        self.runner = runner

    def run(self, *args):
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"}
        try:
            done = self.runner(
                ["git", *args], cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=GIT_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL, env=env,
            )
        except subprocess.TimeoutExpired:
            return 124, f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s"
        except OSError as error:
            return 127, f"git {' '.join(args)} failed to start: {error}"
        return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()


@dataclass
class Context:
    root: Path
    device: str
    execute: bool = False
    profile: str = "device_test"
    delay: int | None = None
    git: Git | None = None
    push: bool = True
    force: bool = False
    sleep_fn: Callable = time.sleep
    now_fn: Callable = datetime.now
    run_fn: Callable = subprocess.run
    screenshot_fn: Callable = None
    stop_fn: Callable = None
    out: Callable = print
    commit_id: str = ""
    code_commit: str = ""

    def __post_init__(self):
        self.screenshot_fn = self.screenshot_fn or capture_screenshot
        self.stop_fn = self.stop_fn or check_stop_file


def check_stop_file():
    if STOP_FILE.exists():
        raise RuntimeError(f"Emergency stop file exists: {STOP_FILE}")


def capture_screenshot(path):
    """Save the primary monitor; returns None on success or the error text."""
    try:
        import cv2
        import mss
        import numpy as np

        with mss.mss() as grabber:
            frame = np.asarray(grabber.grab(grabber.monitors[1]))
        if not cv2.imwrite(str(path), cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)):
            return "imwrite_failed"
        return None
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def device_name(override=None):
    raw = override or os.environ.get("COMPUTERNAME") or socket.gethostname()
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_") or "device"


def load_scenarios(path=SCENARIOS_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeviceTestError(f"Cannot read scenarios: {error}") from error
    scenarios = {}
    for item in data.get("scenarios", ()):
        name = item.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_]+", name) or name in scenarios:
            raise DeviceTestError(f"Invalid or duplicate scenario name: {name!r}")
        for key in ("description", "prepare"):
            if not isinstance(item.get(key), str):
                raise DeviceTestError(f"{name}: missing '{key}'")
        steps = item.get("steps")
        if not isinstance(steps, list) or not steps:
            raise DeviceTestError(f"{name}: needs at least one step")
        for step in steps:
            if not isinstance(step.get("name"), str) or not ("argv" in step or "execute_argv" in step):
                raise DeviceTestError(f"{name}: every step needs a name and argv or execute_argv")
            for key in ("argv", "execute_argv"):
                if key in step:
                    _format_argv(step[key], dict.fromkeys(PLACEHOLDERS, "x"), f"{name}.{step['name']}")
        scenarios[name] = item
    return scenarios


def _format_argv(argv, values, label):
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) for part in argv):
        raise DeviceTestError(f"{label}: argv must be a non-empty list of strings")
    try:
        return [part.format_map(values) for part in argv]
    except (KeyError, IndexError, ValueError) as error:
        raise DeviceTestError(f"{label}: bad placeholder {error}") from error


def is_clicking(scenario):
    return any("execute_argv" in step for step in scenario["steps"])


def _runnable_argv(step, execute):
    if execute and "execute_argv" in step:
        return step["execute_argv"]
    return step.get("argv")


def load_plan(path, scenarios, default_execute=False):
    """Scenarios to run when none are named: [(name, execute)]."""
    try:
        entries = json.loads(Path(path).read_text(encoding="utf-8")).get("scenarios", [])
    except (OSError, json.JSONDecodeError) as error:
        raise DeviceTestError(f"Cannot read plan: {error}") from error
    items = []
    for entry in entries:
        name = entry if isinstance(entry, str) else entry.get("name")
        execute = default_execute or (isinstance(entry, dict) and entry.get("execute") is True)
        if name not in scenarios:
            raise DeviceTestError(f"Plan names unknown scenario: {name!r}")
        items.append((name, execute))
    if not items:
        raise DeviceTestError("The plan is empty.")
    return items


def load_settings(path=SETTINGS_PATH):
    """Load committed one-command defaults for supervised device tests."""
    try:
        settings = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeviceTestError(f"Cannot read device-test settings: {error}") from error
    if not isinstance(settings, dict):
        raise DeviceTestError("Device-test settings must be a JSON object.")
    scenarios = settings.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise DeviceTestError("Device-test settings need a non-empty scenarios list.")
    delay = settings.get("delay_seconds", MAX_PREPARE_DELAY_SECONDS)
    if type(delay) is not int or not 0 <= delay <= MAX_PREPARE_DELAY_SECONDS:
        raise DeviceTestError(f"delay_seconds must be between 0 and {MAX_PREPARE_DELAY_SECONDS}.")
    for key in ("publish", "push", "rerun_same_code"):
        if type(settings.get(key, True)) is not bool:
            raise DeviceTestError(f"{key} must be a boolean.")
    profile = settings.get("profile", "device_test")
    device = settings.get("device")
    if not isinstance(profile, str) or not profile.strip():
        raise DeviceTestError("profile must be a non-empty string.")
    if device is not None and (not isinstance(device, str) or not device.strip()):
        raise DeviceTestError("device must be null or a non-empty string.")
    settings["delay_seconds"] = delay
    settings["publish"] = settings.get("publish", True)
    settings["push"] = settings.get("push", True)
    settings["rerun_same_code"] = settings.get("rerun_same_code", True)
    settings["profile"] = profile
    return settings


def resolve_selection(names, scenarios, plan_path=PLAN_PATH, execute=False, allow_many=False):
    if names:
        items = []
        for name in names:
            if name == "all":
                items += [(key, execute) for key, item in scenarios.items() if item.get("in_all", True)]
            elif name in scenarios:
                items.append((name, execute))
            else:
                raise DeviceTestError(f"Unknown scenario '{name}'. Available: {', '.join(scenarios)}, all")
    else:
        items = load_plan(plan_path, scenarios, execute)
    if len(items) > MAX_SCENARIOS and not allow_many:
        raise DeviceTestError(
            f"{len(items)} scenarios requested; the limit is {MAX_SCENARIOS} (screenshots and diagnostics add up). "
            "Use --allow-many to override."
        )
    return items


def code_commit(git):
    """Latest commit that changed anything except device_runs."""
    code, output = git.run("log", "-1", "--format=%H", "--", ".", f":(exclude){RUNS_DIR_NAME}")
    return output if code == 0 else ""


def previous_code_commit(scenario_dir):
    scenario_dir = Path(scenario_dir)
    runs = sorted(path for path in scenario_dir.iterdir() if path.is_dir()) if scenario_dir.is_dir() else []
    for run in reversed(runs):
        try:
            return json.loads((run / "report.json").read_text(encoding="utf-8")).get("code_commit", "")
        except (OSError, json.JSONDecodeError):
            continue
    return ""


def sync_repository(git):
    """Try a fast-forward pull without risking local changes; failures are non-blocking."""
    _, dirty = git.run("status", "--porcelain", "--untracked-files=no")
    if dirty:
        return False, "tracked_changes_present; using_current_checkout"
    code, output = git.run("pull", "--ff-only")
    if code == 0:
        return True, output
    return False, f"pull_failed; using_current_checkout: {output}"


def prune_old_runs(scenario_dir, keep=KEEP_RUNS):
    runs = sorted(path for path in Path(scenario_dir).iterdir() if path.is_dir())
    removed = runs[:-keep] if len(runs) > keep else []
    for path in removed:
        shutil.rmtree(path)
    return [path.name for path in removed]


def _snapshot(root, directories):
    return {
        rel: {entry.name for entry in (root / rel).iterdir()} if (root / rel).is_dir() else set()
        for rel in directories
    }


def _collect_module_debug(root, before, run_dir):
    moved = []
    for rel, known in before.items():
        base = root / rel
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.name in known:
                continue
            target = run_dir / "module_debug" / Path(rel).name
            target.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(target / entry.name))
            moved.append(f"{rel}/{entry.name}")
    return moved


def _tail(text):
    return text if len(text) <= OUTPUT_LIMIT else text[-OUTPUT_LIMIT:]


def run_scenario(scenario, ctx, execute=None):
    """Run one scenario; None when no step may run without --execute, UNCHANGED when the code was already tested."""
    execute = ctx.execute if execute is None else execute
    steps = [(step, _runnable_argv(step, execute)) for step in scenario["steps"]]
    if all(argv is None for _, argv in steps):
        ctx.out(f"[{scenario['name']}] SKIPPED: requires --execute")
        return None

    scenario_dir = ctx.root / RUNS_DIR_NAME / ctx.device / scenario["name"]
    if ctx.git is not None and not ctx.force and ctx.code_commit and previous_code_commit(scenario_dir) == ctx.code_commit:
        ctx.out(f"[{scenario['name']}] UNCHANGED: already tested on code {ctx.code_commit[:8]}; use --force to run again")
        return {"scenario": scenario["name"], "status": UNCHANGED, "detail": ctx.code_commit}

    started = ctx.now_fn()
    run_dir = scenario_dir / started.strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    log_lines = []

    def log(message):
        line = f"{ctx.now_fn().isoformat(timespec='seconds')} {message}"
        log_lines.append(line)
        ctx.out(line)

    values = {"python": sys.executable, "run_dir": str(run_dir), "profile": ctx.profile}
    before = _snapshot(ctx.root, scenario.get("debug_dirs", ()))
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    records, status = [], OK

    log(f"[{scenario['name']}] prepare: {scenario['prepare']}")
    delay = ctx.delay if ctx.delay is not None else scenario.get("prepare_seconds", 10)
    if delay:
        log(f"[{scenario['name']}] starting in {delay} s")
        ctx.sleep_fn(delay)

    for index, (step, argv) in enumerate(steps, 1):
        record = {"index": index, "name": step["name"]}
        records.append(record)
        if argv is None:
            record.update(status=SKIPPED, reason="requires_--execute")
            log(f"step {index} {step['name']}: SKIPPED (requires --execute)")
            continue
        try:
            ctx.stop_fn()
        except RuntimeError as error:
            record.update(status=BLOCKED, reason=str(error))
            status = BLOCKED
            log(f"step {index} {step['name']}: BLOCKED {error}")
            break

        command = _format_argv(argv, values, f"{scenario['name']}.{step['name']}")
        prefix = f"{index:02d}_{step['name']}"
        record["command"] = command
        record["screenshot_before_error"] = ctx.screenshot_fn(run_dir / f"{prefix}_before.png")
        log(f"step {index} {step['name']}: {' '.join(command)}")
        began = time.monotonic()
        try:
            done = ctx.run_fn(
                command, cwd=ctx.root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=step.get("timeout", STEP_TIMEOUT_SECONDS), env=env,
            )
            returncode = done.returncode
            output = (done.stdout or "") + (done.stderr or "")
        except subprocess.TimeoutExpired:
            returncode, output = None, "timeout"
        except OSError as error:
            returncode, output = None, f"cannot start: {error}"
        record["duration_seconds"] = round(time.monotonic() - began, 2)
        record["returncode"] = returncode
        record["output_tail"] = _tail(output)
        record["screenshot_after_error"] = ctx.screenshot_fn(run_dir / f"{prefix}_after.png")
        record["status"] = OK if returncode == 0 else FAILED
        log(f"step {index} {step['name']}: {record['status']} (rc={returncode}, {record['duration_seconds']} s)")
        if returncode != 0:
            status = FAILED
            break  # never continue a live sequence after a failure

    moved = _collect_module_debug(ctx.root, before, run_dir)
    report = {
        "scenario": scenario["name"],
        "device": ctx.device,
        "status": status,
        "run_dir": str(run_dir.resolve()),
        "execute": execute,
        "commit": ctx.commit_id,
        "code_commit": ctx.code_commit,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": ctx.now_fn().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "steps": records,
        "module_debug": moved,
    }
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    report["scenario_dir"] = str(scenario_dir)
    return report


def publish_run(git, root, scenario_dir, report):
    """Prune old runs, then commit only this scenario's directory."""
    removed = prune_old_runs(scenario_dir)
    relative = Path(scenario_dir).relative_to(root).as_posix()
    message = f"{RUNS_DIR_NAME}: {report['scenario']} on {report['device']} - {report['status']}"
    git.run("add", "-A", "--", relative)
    code, output = git.run("commit", "-m", message, "--", relative)
    return {"removed_runs": removed, "committed": code == 0, "detail": output if code else message}


def push_changes(git):
    code, output = git.run("push")
    if code == 0:
        return True, output
    return False, f"push_failed; diagnostic commit retained locally: {output}"


def run_scenarios(selection, ctx, scenarios):
    """Run scenarios in order; items are names or (name, execute). Returns (exit_code, results)."""
    if ctx.git is not None:
        ok, detail = sync_repository(ctx.git)
        if not ok:
            ctx.out(f"WARNING: git sync skipped: {detail}")
        ctx.commit_id = ctx.git.run("rev-parse", "--short", "HEAD")[1]
        ctx.code_commit = code_commit(ctx.git)

    results = []
    for item in selection:
        name, execute = item if isinstance(item, tuple) else (item, ctx.execute)
        report = run_scenario(scenarios[name], ctx, execute)
        if report is None:
            results.append({"scenario": name, "status": SKIPPED})
            continue
        if report["status"] == UNCHANGED:
            results.append(report)
            continue
        ctx.out(f"[{name}] diagnostics saved: {report['run_dir']}")
        if ctx.git is not None:
            report["publish"] = publish_run(ctx.git, ctx.root, report.pop("scenario_dir"), report)
            ctx.out(f"[{name}] {report['status']}: {report['publish']['detail']}")
        results.append(report)

    if ctx.git is not None and ctx.push and any(r.get("publish", {}).get("committed") for r in results):
        pushed, detail = push_changes(ctx.git)
        ctx.out("pushed" if pushed else f"PUSH FAILED: {detail}")
        results.append({"scenario": "git_push", "status": OK if pushed else FAILED, "detail": detail})

    if any(r["status"] in {FAILED, BLOCKED} for r in results):
        return 1, results
    ran = [r for r in results if r["status"] not in {SKIPPED, UNCHANGED}]
    return (3 if not ran and any(r["status"] == UNCHANGED for r in results) else 0), results


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Supervised live game-window tests. Without scenario names it runs tools/device_test_plan.json.",
    )
    parser.add_argument("scenarios", nargs="*", help="scenario names or 'all'; default is the plan file")
    parser.add_argument("--list", action="store_true", help="show scenarios and the current plan")
    parser.add_argument("--execute", action="store_true", help="also run steps that click in the game")
    parser.add_argument("--force", action="store_true", help="run and publish even if this code was already tested")
    parser.add_argument("--allow-many", action="store_true", help=f"allow more than {MAX_SCENARIOS} scenarios")
    parser.add_argument("--profile")
    parser.add_argument("--device", help="device label; default is the computer name")
    parser.add_argument("--delay", type=int, help="seconds to switch to the game before each scenario")
    parser.add_argument("--no-git", action="store_true", help="skip pull, commit and push")
    parser.add_argument("--no-push", action="store_true", help="commit but do not push")
    args = parser.parse_args(argv)
    if args.delay is not None and not 0 <= args.delay <= MAX_PREPARE_DELAY_SECONDS:
        parser.error(f"--delay must be between 0 and {MAX_PREPARE_DELAY_SECONDS} seconds")

    try:
        scenarios = load_scenarios()
        settings = load_settings()
        if args.list:
            for name, item in scenarios.items():
                kind = "clicks with --execute" if is_clicking(item) else "no clicks"
                print(f"{name:16} {kind:22} {item['description']}")
            plan = load_plan(SETTINGS_PATH, scenarios)
            print("plan: " + ", ".join(f"{name}{' (execute)' if execute else ''}" for name, execute in plan))
            print(
                "settings: "
                f"delay={settings['delay_seconds']}s, publish={settings['publish']}, "
                f"push={settings['push']}, rerun_same_code={settings['rerun_same_code']}"
            )
            return 0
        selection = resolve_selection(args.scenarios, scenarios, SETTINGS_PATH, args.execute, args.allow_many)
    except DeviceTestError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    ctx = Context(
        root=ROOT_DIR,
        device=device_name(args.device or settings.get("device")),
        execute=args.execute,
        profile=args.profile or settings["profile"],
        delay=args.delay if args.delay is not None else settings["delay_seconds"],
        git=None if args.no_git or not settings["publish"] else Git(ROOT_DIR),
        push=not args.no_push and settings["push"],
        force=args.force or settings["rerun_same_code"],
    )
    code, _ = run_scenarios(selection, ctx, scenarios)
    return code


if __name__ == "__main__":
    raise SystemExit(main())