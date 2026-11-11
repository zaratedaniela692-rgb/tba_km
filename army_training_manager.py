#!/usr/bin/env python3
"""Manager runner for army stock goals: observe a Barracks frame, resolve slots, decide. No clicks."""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from army_campaign import (
    Campaign,
    CampaignError,
    campaign_path,
    expand_campaign,
    load_campaign,
    save_campaign,
)
from army_state import ArmyStateError, army_state_path, load_army_state, resolve_max_level, save_max_level
from army_training_observation import build_slot_observation
from army_training_process import (
    Slot,
    TrainingGoal,
    TrainingProcessError,
    enqueue_training_goal,
    migrate_legacy_training_goals,
    reconcile_training_goal,
)
from army_training_resolver import STATUS_OK, resolve_goal_slot
from army_training_category import select_army_type
from army_unit_types import DEFAULT_UNIT_TYPE, UNIT_TYPES
from army_training_executor import execute_training_goal, finish_active_training_for_test
from army_training_finish import CONFIRMATION_PHRASE, FALLBACK_GOAL_KIND, execute_finish_task, process_expirations
from task_controller import (
    ACTIVE_STATUSES,
    DEFAULT_PROFILE_ID,
    PROFILES_DIR,
    TaskQueueError,
    _parse_time,
    create_task_queue,
    effective_priority,
    load_task_queue,
    save_task_queue,
    task_queue_path,
    validate_task_queue,
    army_training_start_is_held,
    resume_army_training,
)

SOURCE = "army_training_manager"
CLEAR_QUEUE_CONFIRMATION = "CLEAR ARMY QUEUE"


@dataclass
class FrameObservation:
    """One captured Barracks frame; per-slot OCR runs lazily through `read_slot`."""

    observed_at: datetime
    source: str
    training_status: str
    layout_status: str
    levels: object  # LayoutLevelReading or None
    read_slot: object  # callable(frame_index) -> SlotReadings
    unit_type: str = DEFAULT_UNIT_TYPE


def observe_image(image, now=None, variant=None, unit_type=DEFAULT_UNIT_TYPE):
    from army_training_levels import read_layout_selector_levels
    from army_training_scanner import read_army_training_snapshot_from_image
    from army_training_slot_reader import read_slot_readings
    from army_training_slots import STATUS_OK as LAYOUT_OK, locate_slots
    from ui_variants import resolve_variant

    variant = variant or resolve_variant()
    regions = json.loads(variant["regions"].read_text(encoding="utf-8")).get("army_training", {})
    layout = locate_slots(image, regions, variant)
    levels = read_layout_selector_levels(image, layout.slots) if layout.status == LAYOUT_OK else None
    snapshot = read_army_training_snapshot_from_image(image, variant=variant)
    cache = {}

    def read_slot(index):
        if index not in cache:
            cache[index] = read_slot_readings(image, layout.slots[index])
        return cache[index]

    return FrameObservation(
        now or datetime.now(timezone.utc), SOURCE, snapshot["status"], layout.status, levels, read_slot,
        unit_type,
    )


def frame_max_level(frame):
    levels = frame.levels
    if levels is None or levels.status != "candidate":
        return None
    return levels.global_highest_visible_level


def _next_action(decision):
    if decision.state.value == "needs_preflight":
        return "train_after_preflight"
    if decision.reason == "selection_unverified":
        return "select_level_then_reobserve"
    return "none"


def evaluate_goals(queue, frame, now, dry_run=True, max_age_seconds=30, unit_type=DEFAULT_UNIT_TYPE, respect_next_check=False):
    """Resolve and decide every open stock goal against one frame; dry_run leaves the queue unchanged."""
    if queue["paused"]:
        return {"status": "paused", "goals": []}
    goals = []
    for task in queue["tasks"]:
        payload = task["payload"]
        if (
            task["task_type"] != "army_training"
            or payload.get("goal_kind") != "slot_stock_v1"
            or task["status"] not in {"queued", "waiting_resources"}
        ):
            continue
        slot = Slot(**payload["slot"])
        if slot.unit_type != unit_type:
            continue
        entry = {
            "task_id": task["task_id"], "unit_type": slot.unit_type,
            "level": slot.global_level, "match_number": slot.match_number,
        }
        if respect_next_check and not _task_check_is_due(task, now):
            entry.update(
                resolution="deferred", reason="next_check_not_due", next_action="none",
                next_check_at=task["next_check_at"],
            )
            goals.append(entry)
            continue
        if frame.layout_status != "ok" or frame.levels is None:
            entry.update(resolution="blocked", reason=f"slot_layout_{frame.layout_status}", next_action="none")
            goals.append(entry)
            continue
        if frame.unit_type != unit_type:
            entry.update(resolution="blocked", reason="frame_unit_type_mismatch", next_action="none")
            goals.append(entry)
            continue
        resolution = resolve_goal_slot(frame.levels.slot_readings, slot.unit_type, slot.global_level, slot.match_number)
        entry.update(resolution=resolution.status, reason=resolution.reason, frame_index=resolution.frame_index)
        if resolution.status != STATUS_OK:
            entry["next_action"] = "none"
            goals.append(entry)
            continue
        observation = build_slot_observation(
            queue["profile_id"], slot, frame.levels.slot_readings[resolution.frame_index],
            frame.read_slot(resolution.frame_index), frame.training_status, frame.observed_at, frame.source,
        )
        decision = reconcile_training_goal(queue, task["task_id"], observation, now, max_age_seconds, dry_run=dry_run)
        entry.update(
            state=decision.state.value,
            reason=decision.reason,
            training_count=decision.training_count,
            next_action=_next_action(decision),
        )
        goals.append(entry)
    return {"status": "ok", "dry_run": dry_run, "goals": goals}


def _load_or_create_queue(profile_id, profiles_dir):
    path = task_queue_path(profile_id, profiles_dir)
    queue = load_task_queue(path, expected_profile_id=profile_id) if path.exists() else create_task_queue(profile_id)
    if migrate_legacy_training_goals(queue):
        save_task_queue(queue, path)
    return queue, path


def _read_image(path):
    from tools.resource_ocr import read_image

    return read_image(path)


def _command_enqueue(args, profiles_dir, now):
    queue, path = _load_or_create_queue(args.profile, profiles_dir)
    slot = Slot(args.unit_type, args.level, args.match)
    task = enqueue_training_goal(queue, TrainingGoal(args.profile, slot), now, args.priority)
    save_task_queue(queue, path)
    return {"status": "ok", "task_id": task["task_id"], "unit_type": args.unit_type, "queue": str(path)}


def _command_resume_army(args, profiles_dir, now):
    if args.confirm != "RESUME ARMY TRAINING":
        return {"status": "BLOCKED_CONFIRMATION", "queue_modified": False}
    path = task_queue_path(args.profile, profiles_dir)
    if not path.exists():
        return {"status": "NO_ARMY_TRAINING_HOLD", "queue_modified": False}
    queue = load_task_queue(path, expected_profile_id=args.profile)
    changed = resume_army_training(queue, now)
    if changed:
        save_task_queue(queue, path)
    return {
        "status": "ARMY_TRAINING_RESUMED" if changed else "NO_ARMY_TRAINING_HOLD",
        "queue_modified": changed, "profile_id": args.profile, "paused": queue["paused"],
    }


def _command_list(args, profiles_dir, now):
    path = task_queue_path(args.profile, profiles_dir)
    queue_exists = path.exists()
    queue = load_task_queue(path, expected_profile_id=args.profile) if queue_exists else None
    tasks = []
    for task in queue["tasks"] if queue is not None else []:
        payload = task.get("payload", {})
        item = {
            "task_id": task["task_id"],
            "task_type": task["task_type"],
            "status": task["status"],
            "priority": task.get("priority"),
            "created_at": task.get("created_at"),
            "next_check_at": task.get("next_check_at"),
            "completed_reason": task.get("completed_reason"),
            "resource_retry": task.get("resource_retry"),
            "resource_retry_history": task.get("resource_retry_history", []),
            "training_start_held": army_training_start_is_held(queue, task),
        }
        slot = payload.get("slot")
        if payload.get("goal_kind") == "slot_stock_v1" and isinstance(slot, dict):
            item.update(
                unit_type=slot.get("unit_type", DEFAULT_UNIT_TYPE),
                level=slot.get("global_level"),
                match_number=slot.get("match_number"),
                process_state=payload.get("process", {}).get("state"),
            )
        elif payload.get("goal_kind") == FALLBACK_GOAL_KIND:
            item["order_id"] = payload.get("order_id")
        tasks.append(item)
    return {
        "status": "QUEUE_LISTED" if tasks else "QUEUE_EMPTY",
        "profile_id": args.profile,
        "queue_exists": queue_exists,
        "paused": queue["paused"] if queue is not None else False,
        "pause_reason": queue["pause_reason"] if queue is not None else None,
        "army_training_hold": queue.get("army_training_hold") if queue is not None else None,
        "task_count": len(tasks),
        "tasks": tasks,
        "queue_modified": False,
        "queue_path": str(path),
    }


def _command_remove(args, profiles_dir, now):
    queue, path = _load_or_create_queue(args.profile, profiles_dir)
    target_slot = Slot(args.unit_type, args.level, args.match)
    task = next((
        item for item in queue["tasks"]
        if item["task_type"] == "army_training"
        and item["payload"].get("goal_kind") == "slot_stock_v1"
        and item["payload"].get("slot") == {
            "unit_type": target_slot.unit_type,
            "global_level": target_slot.global_level,
            "match_number": target_slot.match_number,
        }
    ), None)
    if task is None:
        return {
            "status": "TASK_NOT_FOUND", "unit_type": args.unit_type,
            "level": args.level, "match_number": args.match,
            "queue_modified": False, "queue_path": str(path),
        }
    if task["status"] in ACTIVE_STATUSES:
        return {
            "status": "BLOCKED_ACTIVE_TASK", "task_id": task["task_id"],
            "task_status": task["status"], "queue_modified": False,
            "queue_path": str(path),
        }

    queue["tasks"].remove(task)
    save_task_queue(queue, path)
    return {
        "status": "TASK_REMOVED", "task_id": task["task_id"],
        "unit_type": args.unit_type, "remaining_tasks": len(queue["tasks"]),
        "queue_modified": True, "queue_path": str(path),
    }


def _command_clear(args, profiles_dir, now):
    queue, path = _load_or_create_queue(args.profile, profiles_dir)
    if args.confirm != CLEAR_QUEUE_CONFIRMATION:
        return {
            "status": "BLOCKED_CONFIRMATION",
            "confirmation_required": CLEAR_QUEUE_CONFIRMATION,
            "task_count": len(queue["tasks"]),
            "queue_modified": False,
            "queue_path": str(path),
        }
    if queue["paused"]:
        return {
            "status": "BLOCKED_QUEUE_PAUSED",
            "pause_reason": queue["pause_reason"],
            "queue_modified": False,
            "queue_path": str(path),
        }
    active_tasks = [task for task in queue["tasks"] if task["status"] in ACTIVE_STATUSES]
    if active_tasks:
        return {
            "status": "BLOCKED_ACTIVE_TASKS",
            "active_task_ids": [task["task_id"] for task in active_tasks],
            "queue_modified": False,
            "queue_path": str(path),
        }

    removed_count = len(queue["tasks"])
    queue["tasks"] = []
    save_task_queue(queue, path)
    return {
        "status": "QUEUE_CLEARED",
        "removed_tasks": removed_count,
        "queue_modified": True,
        "queue_path": str(path),
    }


def _command_set_campaign(args, profiles_dir, now):
    campaign = Campaign(args.unit_type, args.policy, args.level, True, args.priority)
    path = save_campaign(campaign, campaign_path(args.profile, profiles_dir))
    return {"status": "ok", "campaign": str(path)}


def _command_expand(args, profiles_dir, now):
    campaign = load_campaign(campaign_path(args.profile, profiles_dir))
    if campaign is None:
        raise CampaignError("No campaign is configured for this profile.")
    state_path = army_state_path(args.profile, profiles_dir)
    fresh = None
    if args.image:
        fresh = frame_max_level(observe_image(_read_image(args.image), now, unit_type=campaign.unit_type))
        if fresh is not None:
            save_max_level(state_path, campaign.unit_type, fresh, now, SOURCE)
    max_level = resolve_max_level(campaign.unit_type, fresh, load_army_state(state_path), now)
    if max_level.status != "ok":
        return {"status": "blocked", "reason": max_level.reason, "goals": []}
    queue, path = _load_or_create_queue(args.profile, profiles_dir)
    goals = expand_campaign(queue, campaign, max_level.level, now)
    save_task_queue(queue, path)
    return {"status": "ok", "max_level": max_level.level, "max_level_source": max_level.source, "goals": goals}


def _command_run(args, profiles_dir, now):
    queue, path = _load_or_create_queue(args.profile, profiles_dir)
    frame = observe_image(_read_image(args.image), now, unit_type=args.unit_type)
    report = evaluate_goals(queue, frame, now, dry_run=not args.save, unit_type=args.unit_type)
    if args.save:
        save_task_queue(queue, path)
    return report


def _parse_next_check(task):
    return _parse_time(task.get("next_check_at"))


def _task_check_is_due(task, now):
    next_check = _parse_next_check(task)
    return next_check is None or next_check <= now


def _next_pending_goal_unit_type(queue, now=None):
    candidates = [
        task for task in queue["tasks"]
        if task["task_type"] == "army_training"
        and task["payload"].get("goal_kind") == "slot_stock_v1"
        and task["status"] in {"queued", "waiting_resources"}
        and (now is None or _task_check_is_due(task, now))
    ]
    candidates.sort(key=lambda task: (effective_priority(queue, task), _parse_time(task["created_at"])))
    return Slot(**candidates[0]["payload"]["slot"]).unit_type if candidates else None


def _next_due_finish_task(queue, now):
    return next((
        task for task in queue["tasks"]
        if task["payload"].get("goal_kind") == FALLBACK_GOAL_KIND
        and task["status"] in {"queued", "waiting_resources"}
        and (_parse_next_check(task) is None or _parse_next_check(task) <= now)
    ), None)


def _select_executable_goal(queue, report, test_task_id=None):
    if queue.get("army_training_hold") is not None:
        return None
    eligible = [
        item for item in report.get("goals", [])
        if item.get("state") == "needs_preflight"
        or item.get("reason") == "selection_unverified"
    ]
    if test_task_id:
        eligible = [item for item in eligible if item["task_id"] == test_task_id]
    eligible.sort(key=lambda item: (
        effective_priority(queue, next(task for task in queue["tasks"] if task["task_id"] == item["task_id"])),
        next(task["created_at"] for task in queue["tasks"] if task["task_id"] == item["task_id"]),
    ))
    return eligible[0]["task_id"] if eligible else None


def _finish_test_training(queue, path, state_path, profile_id, now, navigation, capture_fn):
    from army_state import clear_open_training, open_training

    if navigation.get("status") != "BARRACKS_OPENED":
        return {
            "status": "BLOCKED_TASK_STARTUP",
            "actions_executed": navigation.get("actions_executed", False),
            "queue_modified": False,
            "navigation": navigation,
            "queue_path": str(path),
        }
    try:
        image, origin = capture_fn()
        finish_result = finish_active_training_for_test(
            image, origin, profile_id, capture_fn,
        )
        if finish_result["status"] not in {"IDLE", "FINISHED"}:
            raise ValueError("Test finisher did not confirm idle.")
    except Exception as error:
        return {
            "status": "BLOCKED_ACTIVE_TRAINING_FINISH",
            "actions_executed": "unknown",
            "queue_modified": False,
            "reason": f"{type(error).__name__}: {error}",
            "navigation": navigation,
            "queue_path": str(path),
        }
    marker = open_training(load_army_state(state_path))
    if marker is not None:
        for item in queue["tasks"]:
            owned = item["task_id"] == marker.get("task_id")
            fallback = (
                item["payload"].get("goal_kind") == FALLBACK_GOAL_KIND
                and item["payload"].get("order_id") == marker.get("order_id")
            )
            if item["task_type"] == "army_training" and (owned or fallback) and item["status"] != "completed":
                item.update(status="completed", completed_at=now.isoformat(), completed_reason="e2e_idle_confirmed")
        validate_task_queue(queue, expected_profile_id=profile_id)
    save_task_queue(queue, path)
    if marker is not None:
        clear_open_training(state_path)
    return {
        "status": "TRAINING_FINISHED_FOR_TEST" if finish_result["status"] == "FINISHED" else "TRAINING_IDLE_FOR_TEST",
        "actions_executed": navigation.get("actions_executed", False) or finish_result["actions_executed"],
        "queue_modified": marker is not None,
        "finish": finish_result,
        "navigation": navigation,
        "queue_path": str(path),
    }


def _command_execute(args, profiles_dir, now):
    from army_training_live_e2e import capture_primary_monitor
    from army_training_navigation import open_army_training_screen

    if args.execute and args.confirm != CONFIRMATION_PHRASE:
        return {
            "status": "BLOCKED_CONFIRMATION",
            "actions_executed": False,
            "queue_modified": False,
            "blockers": [f"Live execution requires confirmation phrase: {CONFIRMATION_PHRASE}"],
        }

    test_finish = args.execute and getattr(args, "finish_active_for_test", False)
    test_task_id = getattr(args, "test_task_id", None)
    if test_task_id and (args.profile != "test" or args.navigate_only):
        return {"status": "BLOCKED_TEST_TASK_MODE", "actions_executed": False, "queue_modified": False}
    if test_finish and (args.profile != "test" or not args.navigate_only):
        return {
            "status": "BLOCKED_TEST_PROFILE_REQUIRED" if args.profile != "test" else "BLOCKED_TEST_FINISH_MODE",
            "actions_executed": False, "queue_modified": False,
        }
    if test_finish:
        path = task_queue_path(args.profile, profiles_dir)
        queue = load_task_queue(path, expected_profile_id=args.profile) if path.exists() else create_task_queue(args.profile)
    else:
        queue, path = _load_or_create_queue(args.profile, profiles_dir)
    state_path = army_state_path(args.profile, profiles_dir)
    test_task = None
    if test_task_id:
        test_task = next((task for task in queue["tasks"] if task["task_id"] == test_task_id), None)
        if (
            test_task is None or test_task["task_type"] != "army_training"
            or test_task["payload"].get("goal_kind") != "slot_stock_v1"
            or test_task["status"] not in {"queued", "waiting_resources"}
        ):
            return {"status": "BLOCKED_TEST_TASK", "actions_executed": False, "queue_modified": False}
    if args.execute and queue["paused"]:
        return {
            "status": "BLOCKED_PAUSED_QUEUE", "actions_executed": False, "queue_modified": False,
            "reason": queue["pause_reason"], "queue_path": str(path),
        }
    if args.navigate_only:
        navigation = open_army_training_screen(execute=args.execute)
        if test_finish:
            return _finish_test_training(
                queue, path, state_path, args.profile, now, navigation, capture_primary_monitor,
            )
        return {
            **navigation,
            "navigation": navigation,
            "queue_modified": False,
            "queue_path": str(path),
        }
    if not args.execute:
        navigation = open_army_training_screen(execute=False)
        return {
            "status": "PREVIEW_ONLY",
            "actions_executed": False,
            "queue_modified": False,
            "navigation": navigation,
            "queue_path": str(path),
        }

    housekeeping = process_expirations(queue, state_path, now)
    if args.execute:
        save_task_queue(queue, path)
    navigation = open_army_training_screen(execute=args.execute)
    if args.execute and navigation.get("status") != "BARRACKS_OPENED":
        return {
            "status": "BLOCKED_TASK_STARTUP",
            "actions_executed": navigation.get("actions_executed", False),
            "queue_modified": False,
            "navigation": navigation,
            "housekeeping": housekeeping,
            "queue_path": str(path),
        }
    due_finish = _next_due_finish_task(queue, now)
    if due_finish is not None:
        result = execute_finish_task(
            queue, due_finish["task_id"], state_path, now,
            execute=args.execute, confirmation=args.confirm,
        )
        if args.execute:
            save_task_queue(queue, path)
        result.update(
            task_id=due_finish["task_id"], housekeeping=housekeeping,
            navigation=navigation, queue_path=str(path),
        )
        return result
    if queue.get("army_training_hold") is not None:
        return {
            "status": "ARMY_TRAINING_HELD", "army_training_hold": queue["army_training_hold"],
            "actions_executed": navigation.get("actions_executed", False), "queue_modified": False,
            "navigation": navigation, "housekeeping": housekeeping, "queue_path": str(path),
        }
    if test_task is not None:
        unit_type = Slot(**test_task["payload"]["slot"]).unit_type if _task_check_is_due(test_task, now) else None
    else:
        unit_type = _next_pending_goal_unit_type(queue, now)
    if unit_type is not None:
        category = select_army_type(unit_type)
        if category["status"] != "DEFAULT_CATEGORY_ASSUMED":
            return {
                "status": category["status"], "category_selection": category,
                "actions_executed": False, "queue_modified": False,
                "navigation": navigation, "housekeeping": housekeeping,
                "queue_path": str(path),
            }
    else:
        unit_type = DEFAULT_UNIT_TYPE
        category = None
    image, _origin = capture_primary_monitor()
    frame = observe_image(image, now, unit_type=unit_type)
    report = evaluate_goals(
        queue, frame, now, dry_run=not args.execute, unit_type=unit_type, respect_next_check=True,
    )
    task_id = _select_executable_goal(queue, report, test_task_id)
    if task_id is None:
        if args.execute:
            save_task_queue(queue, path)
        return {
            "status": "NO_EXECUTABLE_GOAL", "actions_executed": False, "queue_modified": False,
            "evaluation": report, "housekeeping": housekeeping, "navigation": navigation,
            **({"category_selection": category} if category is not None else {}),
        }
    result = execute_training_goal(
        queue,
        task_id,
        now,
        execute=args.execute,
        confirmation=args.confirm,
        state_path=state_path,
        quantity=getattr(args, "quantity", None),
    )
    if args.execute:
        save_task_queue(queue, path)
    result["evaluation"] = report
    result["housekeeping"] = housekeeping
    result["navigation"] = navigation
    if category is not None:
        result["category_selection"] = category
    result["queue_path"] = str(path)
    return result


def _positive_quantity(value):
    try:
        quantity = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("quantity must be a positive integer") from error
    if quantity <= 0:
        raise argparse.ArgumentTypeError("quantity must be a positive integer")
    return quantity


def build_parser():
    parser = argparse.ArgumentParser(description="Army stock-goal manager; execution is opt-in and limited to one order.")
    parser.add_argument(
        "--profile", default=DEFAULT_PROFILE_ID,
        help=f"profile ID (default: {DEFAULT_PROFILE_ID!r})",
    )
    parser.add_argument("--profiles-dir", default=str(PROFILES_DIR))
    parser.add_argument("--tesseract", help="path to tesseract.exe")
    commands = parser.add_subparsers(dest="command", required=True)

    list_command = commands.add_parser("list", help="list tasks in a profile queue without modifying it")
    list_command.set_defaults(handler=_command_list)

    enqueue = commands.add_parser("enqueue", help="add one stock goal (level, match number)")
    enqueue.add_argument("--unit-type", choices=UNIT_TYPES, required=True)
    enqueue.add_argument("--level", type=int, required=True)
    enqueue.add_argument("--match", type=int, required=True)
    enqueue.add_argument("--priority", type=int)
    enqueue.set_defaults(handler=_command_enqueue)

    remove = commands.add_parser("remove", help="remove one inactive goal by unit type, level, and match")
    remove.add_argument("--unit-type", choices=UNIT_TYPES, required=True)
    remove.add_argument("--level", type=int, required=True)
    remove.add_argument("--match", type=int, required=True)
    remove.set_defaults(handler=_command_remove)

    clear = commands.add_parser("clear", help="clear all tasks in a profile queue")
    clear.add_argument("--confirm", default="", help=f"type exactly: {CLEAR_QUEUE_CONFIRMATION}")
    clear.set_defaults(handler=_command_clear)

    campaign = commands.add_parser("set-campaign", help="store the replenishment policy")
    campaign.add_argument("--unit-type", choices=UNIT_TYPES, required=True)
    campaign.add_argument("--policy", choices=("max", "max_minus_1", "fixed"), required=True)
    campaign.add_argument("--level", type=int)
    campaign.add_argument("--priority", type=int)
    campaign.set_defaults(handler=_command_set_campaign)

    expand = commands.add_parser("expand", help="expand the campaign into stock goals")
    expand.add_argument("--image", help="Barracks screenshot to read the max level from; else the cache is used")
    expand.set_defaults(handler=_command_expand)

    resume = commands.add_parser("resume-army", help="clear the army resource hold and require fresh observation; no game input")
    resume.add_argument("--confirm", default="", help="type exactly: RESUME ARMY TRAINING")
    resume.set_defaults(handler=_command_resume_army)

    run = commands.add_parser("run", help="decide open goals from a screenshot; dry-run unless --save")
    run.add_argument("--unit-type", choices=UNIT_TYPES, required=True)
    run.add_argument("--image", required=True)
    run.add_argument("--save", action="store_true", help="persist decisions in the task queue (still no clicks)")
    run.set_defaults(handler=_command_run)

    execute = commands.add_parser("execute", help="execute at most one ready goal; preview unless --execute is provided")
    execute.add_argument("--execute", action="store_true", help="allow selector and at most one Train click")
    execute.add_argument("--confirm", default="", help=f"type exactly: {CONFIRMATION_PHRASE}")
    execute.add_argument(
        "--quantity", type=_positive_quantity,
        help="optional number of soldiers to train; omitted uses the full queue",
    )
    execute.add_argument(
        "--navigate-only", action="store_true",
        help="run or preview the army-training startup navigation without evaluating or training a goal",
    )
    execute.add_argument(
        "--finish-active-for-test", action="store_true",
        help="finish current Barracks training before the queued goal; test profile only",
    )
    execute.add_argument("--test-task-id", help="execute only this stock goal in the test profile; no alternate goal")
    execute.set_defaults(handler=_command_execute)
    return parser


def main(argv=None, now=None):
    args = build_parser().parse_args(argv)
    if args.tesseract:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = args.tesseract
    try:
        report = args.handler(args, Path(args.profiles_dir), now or datetime.now(timezone.utc))
    except (CampaignError, ArmyStateError, TaskQueueError, TrainingProcessError, OSError, ValueError) as error:
        print(f"Manager error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
