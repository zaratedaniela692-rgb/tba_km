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
RUNS_DIR_NAME = "device_runs"
KEEP_RUNS = 4  # the current run plus three earlier ones
STOP_FILE = Path.home() / ".tba_stop"
STEP_TIMEOUT_SECONDS = 600
OUTPUT_LIMIT = 20000
PLACEHOLDERS = ("python", "run_dir", "profile")

OK, FAILED, BLOCKED, SKIPPED = "OK", "FAILED", "BLOCKED", "SKIPPED"


class DeviceTestError(ValueError):
    """Invalid scenario registry or arguments."""


class Git:
    def __init__(self, root, runner=subprocess.run):
        self.root = Path(root)
        self.runner = runner

    def run(self, *args):
        done = self.runner(
            ["git", *args], cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
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
    sleep_fn: Callable = time.sleep
    now_fn: Callable = datetime.now
    run_fn: Callable = subprocess.run
    screenshot_fn: Callable = None
    stop_fn: Callable = None
    out: Callable = print
    commit_id: str = ""

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


def sync_repository(git):
    """Fast-forward pull; a local-only device_runs commit may be rebased. Returns (ok, detail)."""
    _, dirty = git.run("status", "--porcelain", "--untracked-files=no")
    if dirty:
        return False, "tracked_changes_present"
    code, output = git.run("pull", "--ff-only")
    if code == 0:
        return True, output
    code, output = git.run("pull", "--rebase")
    if code == 0:
        return True, output
    git.run("rebase", "--abort")
    return False, f"pull_failed: {output}"


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


def run_scenario(scenario, ctx):
    """Run one scenario; returns its report, or None when no step may run without --execute."""
    steps = [(step, _runnable_argv(step, ctx.execute)) for step in scenario["steps"]]
    if all(argv is None for _, argv in steps):
        ctx.out(f"[{scenario['name']}] SKIPPED: requires --execute")
        return None

    started = ctx.now_fn()
    scenario_dir = ctx.root / RUNS_DIR_NAME / ctx.device / scenario["name"]
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
        "execute": ctx.execute,
        "commit": ctx.commit_id,
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
    code, output = git.run("pull", "--rebase")
    if code != 0:
        git.run("rebase", "--abort")
        return False, f"push_failed_pull_rebase_failed: {output}"
    code, output = git.run("push")
    return code == 0, output


def run_scenarios(names, ctx, scenarios):
    """Run scenarios in order; returns (exit_code, results)."""
    if ctx.git is not None:
        ok, detail = sync_repository(ctx.git)
        if not ok:
            ctx.out(f"BLOCKED: git sync failed: {detail}")
            return 2, [{"scenario": "git", "status": BLOCKED, "detail": detail}]
        ctx.commit_id = ctx.git.run("rev-parse", "--short", "HEAD")[1]

    results = []
    for name in names:
        report = run_scenario(scenarios[name], ctx)
        if report is None:
            results.append({"scenario": name, "status": SKIPPED})
            continue
        if ctx.git is not None:
            report["publish"] = publish_run(ctx.git, ctx.root, report.pop("scenario_dir"), report)
            ctx.out(f"[{name}] {report['status']}: {report['publish']['detail']}")
        results.append(report)

    if ctx.git is not None and ctx.push and any(r.get("publish", {}).get("committed") for r in results):
        pushed, detail = push_changes(ctx.git)
        ctx.out("pushed" if pushed else f"PUSH FAILED: {detail}")
        results.append({"scenario": "git_push", "status": OK if pushed else FAILED, "detail": detail})

    failed = any(r["status"] in {FAILED, BLOCKED} for r in results)
    return (1 if failed else 0), results


def _scenario_names(selection, scenarios):
    if selection == "all":
        return [name for name, item in scenarios.items() if item.get("in_all", True)]
    if selection not in scenarios:
        raise DeviceTestError(f"Unknown scenario '{selection}'. Available: {', '.join(scenarios)}, all")
    return [selection]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Supervised live game-window tests for a test PC.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="show scenarios")
    run = commands.add_parser("run", help="run a scenario or 'all'")
    run.add_argument("scenario")
    run.add_argument("--execute", action="store_true", help="also run steps that click in the game")
    run.add_argument("--profile", default="device_test")
    run.add_argument("--device", help="device label; default is the computer name")
    run.add_argument("--delay", type=int, help="seconds to switch to the game before each scenario")
    run.add_argument("--no-git", action="store_true", help="skip pull, commit and push")
    run.add_argument("--no-push", action="store_true", help="commit but do not push")
    args = parser.parse_args(argv)

    try:
        scenarios = load_scenarios()
        if args.command == "list":
            for name, item in scenarios.items():
                kind = "clicks with --execute" if is_clicking(item) else "no clicks"
                print(f"{name:16} {kind:22} {item['description']}")
            return 0
        names = _scenario_names(args.scenario, scenarios)
    except DeviceTestError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    ctx = Context(
        root=ROOT_DIR, device=device_name(args.device), execute=args.execute, profile=args.profile,
        delay=args.delay, git=None if args.no_git else Git(ROOT_DIR), push=not args.no_push,
    )
    code, _ = run_scenarios(names, ctx, scenarios)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
