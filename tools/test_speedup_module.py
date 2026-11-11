#!/usr/bin/env python3
"""Run the configured offline Speed Up planner check without game access."""

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from speedup_planner import HOUR, plan_speedups

MODULE = "speedup_planner"
SCENARIO = "synthetic_owned_inventory"
REMAINING_SECONDS = 12 * HOUR
INVENTORY = {HOUR: 20, 3 * HOUR: 20, 8 * HOUR: 20}


def run_check(planner=plan_speedups):
    inventory = dict(INVENTORY)
    try:
        plan = planner(REMAINING_SECONDS, inventory)
        covered = sum(duration * count for duration, count in plan.uses)
        passed = plan.status == "ok" and covered >= REMAINING_SECONDS and inventory == INVENTORY
        return {
            "status": "PASSED" if passed else "FAILED",
            "module": MODULE,
            "scenario": SCENARIO,
            "mode": "offline",
            "side_effects": [],
            "evidence_inputs": {"inventory": inventory, "remaining_seconds": REMAINING_SECONDS},
            "artifacts_dir": None,
            "result": {"plan_status": plan.status, "uses": plan.uses, "covered_seconds": covered},
        }
    except Exception as error:
        return {
            "status": "FAILED",
            "module": MODULE,
            "scenario": SCENARIO,
            "mode": "offline",
            "side_effects": [],
            "evidence_inputs": {"inventory": inventory, "remaining_seconds": REMAINING_SECONDS},
            "artifacts_dir": None,
            "error": f"{type(error).__name__}: {error}",
        }


def main(argv=None, output=print):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        output(json.dumps({"status": "BLOCKED_ARGUMENTS", "module": MODULE, "mode": "offline"}))
        return 2
    report = run_check()
    output(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())