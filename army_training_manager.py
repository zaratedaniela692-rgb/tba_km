#!/usr/bin/env python3
"""Manager runner for army stock goals: observe a Barracks frame, resolve slots, decide. No clicks."""

import argparse
import json
import sys
from copy import deepcopy
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
from army_state import ArmyStateError, army_state_path, load_army_state, open_training, resolve_max_level, save_max_level
from army_training_observation import build_slot_observation
from army_training_process import (
    Slot,
    TrainingGoal,
    TrainingProcessError,
    enqueue_training_goal,
    migrate_legacy_training_goals,
    rearm_training_goal,
    reconcile_training_goal,
)
from army_training_resolver import STATUS_OK, resolve_goal_slot
from army_training_category import CONFIRMED_STATUSES, read_selected_category, select_army_type
from army_unit_types import DEFAULT_UNIT_TYPE, UNIT_TYPES
from army_training_executor import execute_training_goal
from army_training_finish import CONFIRMATION_PHRASE, FALLBACK_GOAL_KIND, execute_finish_task, process_expirations
from task_controller import (
    ACTIVE_STATUSES,
    PROFILES_DIR,
    TaskQueueError,
    _parse_time,
    create_task_queue,
    effective_priority,
    load_task_queue,
    save_task_queue,
    task_queue_path,
)
from profile_identity import ProfileIdentityError, resolve_profile_from_game

SOURCE = "army_training_manager"
CLEAR_QUEUE_CONFIRMATION = "CLEAR ARMY QUEUE"
SPECIALIST_TEST_CONFIRMATION = "TRAIN ONE SPECIALIST"


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
    # An unreadable highlight keeps the requested type; a different readable one is blocked by evaluate_goals.
    unit_type = read_selected_category(image, regions, variant)["unit_type"] or unit_type
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


def evaluate_goals(queue, frame, now, dry_run=True, max_age_seconds=30, unit_type=DEFAULT_UNIT_TYPE):
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


def _command_test_specialist(args, profiles_dir, now):
    slot = Slot("specialists", args.level, args.match)
    expected_slot = {
        "unit_type": slot.unit_type,
        "global_level": slot.global_level,
        "match_number": slot.match_number,
    }
    if not args.execute:
        return {
            "status": "PREVIEW_ONLY",
            "goal": expected_slot,
            "actions_executed": False,
            "queue_modified": False,
            "live_confirmation_required": SPECIALIST_TEST_CONFIRMATION,
            "note": "Live test can consume silver/food and starts one in-game training order.",
        }
    if args.confirm != SPECIALIST_TEST_CONFIRMATION:
        return {
            "status": "BLOCKED_CONFIRMATION",
            "goal": expected_slot,
            "actions_executed": False,
            "queue_modified": False,
            "confirmation_required": SPECIALIST_TEST_CONFIRMATION,
        }

    queue, path = _load_or_create_queue(args.profile, profiles_dir)
    if queue["paused"]:
        return {
            "status": "BLOCKED_QUEUE_PAUSED", "pause_reason": queue["pause_reason"],
            "goal": expected_slot, "actions_executed": False, "queue_modified": False,
        }
    state_path = army_state_path(args.profile, profiles_dir)
    marker = open_training(load_army_state(state_path))
    if marker is not None:
        return {
            "status": "BLOCKED_OPEN_TRAINING_MARKER", "order_id": marker.get("order_id"),
            "goal": expected_slot, "actions_executed": False, "queue_modified": False,
        }
    active_tasks = [task for task in queue["tasks"] if task["status"] in ACTIVE_STATUSES]
    if active_tasks:
        return {
            "status": "BLOCKED_ACTIVE_TASKS", "active_task_ids": [task["task_id"] for task in active_tasks],
            "goal": expected_slot, "actions_executed": False, "queue_modified": False,
        }
    pending_finish = [
        task for task in queue["tasks"]
        if task["payload"].get("goal_kind") == FALLBACK_GOAL_KIND
        and task["status"] in {"queued", "waiting_resources"}
    ]
    if pending_finish:
        return {
            "status": "BLOCKED_PENDING_FINISH_TASKS",
            "task_ids": [task["task_id"] for task in pending_finish],
            "goal": expected_slot, "actions_executed": False, "queue_modified": False,
        }

    matching = next((
        task for task in queue["tasks"]
        if task["task_type"] == "army_training"
        and task["payload"].get("goal_kind") == "slot_stock_v1"
        and task["payload"].get("slot") == expected_slot
    ), None)
    other_pending = [
        task for task in queue["tasks"]
        if task["task_type"] == "army_training"
        and task["payload"].get("goal_kind") == "slot_stock_v1"
        and task["status"] in {"queued", "waiting_resources"}
        and task is not matching
    ]
    if other_pending:
        return {
            "status": "BLOCKED_OTHER_PENDING_ARMY_GOALS",
            "task_ids": [task["task_id"] for task in other_pending],
            "goal": expected_slot, "actions_executed": False, "queue_modified": False,
        }
    if matching is not None and matching["status"] not in {"queued", "waiting_resources", "completed"}:
        return {
            "status": "BLOCKED_GOAL_NOT_REUSABLE", "task_id": matching["task_id"],
            "task_status": matching["status"], "goal": expected_slot,
            "actions_executed": False, "queue_modified": False,
        }

    created_for_test = matching is None
    original_matching = deepcopy(matching) if matching is not None and matching["status"] == "completed" else None
    if created_for_test:
        matching = enqueue_training_goal(queue, TrainingGoal(args.profile, slot), now)
        queue_modified = True
        setup_action = "created"
    elif matching["status"] == "completed":
        matching = rearm_training_goal(queue, matching["task_id"], now)
        queue_modified = True
        setup_action = "rearmed"
    else:
        queue_modified = False
        setup_action = "reused"
    task_id = matching["task_id"]
    if queue_modified:
        save_task_queue(queue, path)

    execution_args = argparse.Namespace(
        profile=args.profile,
        execute=True,
        confirm=CONFIRMATION_PHRASE,
        navigate_only=False,
        stop_after_train_confirmed=True,
    )
    try:
        result = _command_execute(execution_args, profiles_dir, now)
    except Exception as error:
        return {
            "status": "TEST_RESULT_UNKNOWN_QUEUE_PRESERVED",
            "reason": str(error),
            "test_goal": expected_slot,
            "test_task_id": task_id,
            "test_goal_action": setup_action,
            "actions_executed": "unknown",
            "queue_modified": queue_modified,
            "operator_action": "Inspect the game before retrying; no automatic cleanup or retry was done.",
        }
    result["test_goal"] = expected_slot
    result["test_task_id"] = task_id
    result["test_goal_action"] = setup_action
    if result.get("train_click_attempted") or result.get("status") == "TEST_TRAINING_STARTED_CONFIRMED":
        return result

    if created_for_test:
        current_queue = load_task_queue(path, expected_profile_id=args.profile)
        test_task = next((task for task in current_queue["tasks"] if task["task_id"] == task_id), None)
        if test_task is not None and test_task["status"] in {"queued", "waiting_resources"}:
            current_queue["tasks"].remove(test_task)
            save_task_queue(current_queue, path)
            result["test_goal_removed_after_block"] = True
            result["queue_modified"] = True
    elif original_matching is not None:
        current_queue = load_task_queue(path, expected_profile_id=args.profile)
        for index, task in enumerate(current_queue["tasks"]):
            if task["task_id"] == task_id:
                current_queue["tasks"][index] = original_matching
                save_task_queue(current_queue, path)
                result["completed_test_goal_restored"] = True
                result["queue_modified"] = True
                break
    result["status"] = "TEST_BLOCKED_BEFORE_TRAIN"
    result["queue_modified"] = result.get("queue_modified", False) or queue_modified
    return result


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


def _next_pending_goal_unit_type(queue):
    candidates = [
        task for task in queue["tasks"]
        if task["task_type"] == "army_training"
        and task["payload"].get("goal_kind") == "slot_stock_v1"
        and task["status"] in {"queued", "waiting_resources"}
    ]
    candidates.sort(key=lambda task: (effective_priority(queue, task), _parse_time(task["created_at"])))
    return Slot(**candidates[0]["payload"]["slot"]).unit_type if candidates else None


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

    queue, path = _load_or_create_queue(args.profile, profiles_dir)
    state_path = army_state_path(args.profile, profiles_dir)
    if args.navigate_only:
        navigation = open_army_training_screen(execute=args.execute)
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
    due_finish = next((
        task for task in queue["tasks"]
        if task["payload"].get("goal_kind") == FALLBACK_GOAL_KIND
        and task["status"] in {"queued", "waiting_resources"}
        and (_parse_next_check(task) is None or _parse_next_check(task) <= now)
    ), None)
    if due_finish is not None:
        from army_training_speedup import finish_active_training_with_speedups

        result = execute_finish_task(
            queue, due_finish["task_id"], state_path, now,
            execute=args.execute, confirmation=args.confirm,
            speedup_fn=finish_active_training_with_speedups,
        )
        if args.execute:
            save_task_queue(queue, path)
        result.update(
            task_id=due_finish["task_id"], housekeeping=housekeeping,
            navigation=navigation, queue_path=str(path),
        )
        return result
    unit_type = _next_pending_goal_unit_type(queue)
    if unit_type is not None:
        category = select_army_type(unit_type, execute=args.execute)
        if category["status"] not in CONFIRMED_STATUSES:
            return {
                "status": category["status"], "category_selection": category,
                "actions_executed": category.get("actions_executed", False), "queue_modified": False,
                "navigation": navigation, "housekeeping": housekeeping,
                "queue_path": str(path),
            }
    else:
        unit_type = DEFAULT_UNIT_TYPE
        category = None
    image, _ = capture_primary_monitor()
    frame = observe_image(image, now, unit_type=unit_type)
    report = evaluate_goals(queue, frame, now, dry_run=not args.execute, unit_type=unit_type)
    eligible = [
        item for item in report.get("goals", [])
        if item.get("state") == "needs_preflight"
        or item.get("reason") == "selection_unverified"
    ]
    eligible.sort(key=lambda item: (
        effective_priority(queue, next(task for task in queue["tasks"] if task["task_id"] == item["task_id"])),
        next(task["created_at"] for task in queue["tasks"] if task["task_id"] == item["task_id"]),
    ))
    if not eligible:
        if args.execute:
            save_task_queue(queue, path)
        return {
            "status": "NO_EXECUTABLE_GOAL", "actions_executed": False, "queue_modified": False,
            "evaluation": report, "housekeeping": housekeeping, "navigation": navigation,
            **({"category_selection": category} if category is not None else {}),
        }
    task_id = eligible[0]["task_id"]
    from army_training_speedup import finish_active_training_with_speedups

    result = execute_training_goal(
        queue,
        task_id,
        now,
        execute=args.execute,
        confirmation=args.confirm,
        state_path=state_path,
        speedup_fn=finish_active_training_with_speedups,
        stop_after_train_confirmed=getattr(args, "stop_after_train_confirmed", False),
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


def build_parser():
    parser = argparse.ArgumentParser(description="Army stock-goal manager; execution is opt-in and limited to one order.")
    parser.add_argument("--profile", required=True, help="profile ID or 'auto' to read the visible in-game player name")
    parser.add_argument("--new-profile", action="store_true", help="with --profile auto, create a new ID even when this player name already exists")
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

    specialist_test = commands.add_parser(
        "test-specialist", help="run one supervised Specialists order and stop after active training is confirmed",
    )
    specialist_test.add_argument("--level", type=int, default=5)
    specialist_test.add_argument("--match", type=int, default=1)
    specialist_test.add_argument("--execute", action="store_true", help="allow one verified Train click")
    specialist_test.add_argument("--confirm", default="", help=f"type exactly: {SPECIALIST_TEST_CONFIRMATION}")
    specialist_test.set_defaults(handler=_command_test_specialist)

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

    run = commands.add_parser("run", help="decide open goals from a screenshot; dry-run unless --save")
    run.add_argument("--unit-type", choices=UNIT_TYPES, required=True)
    run.add_argument("--image", required=True)
    run.add_argument("--save", action="store_true", help="persist decisions in the task queue (still no clicks)")
    run.set_defaults(handler=_command_run)

    execute = commands.add_parser("execute", help="execute at most one ready goal; preview unless --execute is provided")
    execute.add_argument("--execute", action="store_true", help="allow selector and at most one Train click")
    execute.add_argument("--confirm", default="", help=f"type exactly: {CONFIRMATION_PHRASE}")
    execute.add_argument(
        "--navigate-only", action="store_true",
        help="run or preview the army-training startup navigation without evaluating or training a goal",
    )
    execute.set_defaults(handler=_command_execute)
    return parser


def main(argv=None, now=None):
    args = build_parser().parse_args(argv)
    if args.tesseract:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = args.tesseract
    try:
        profile_resolution = None
        if args.profile == "auto":
            profile_resolution, reading = resolve_profile_from_game(
                profiles_dir=Path(args.profiles_dir),
                new_profile=args.new_profile,
                tesseract_cmd=args.tesseract,
            )
            args.profile = profile_resolution.profile_id
        elif args.new_profile:
            raise ProfileIdentityError("--new-profile requires --profile auto.")
        report = args.handler(args, Path(args.profiles_dir), now or datetime.now(timezone.utc))
        if profile_resolution is not None:
            report["profile_identity"] = {
                "player_name": profile_resolution.player_name,
                "profile_id": profile_resolution.profile_id,
                "action": profile_resolution.action,
                "ocr_passes": list(reading.candidates),
            }
    except (CampaignError, ArmyStateError, TaskQueueError, TrainingProcessError, ProfileIdentityError, OSError, ValueError) as error:
        print(f"Manager error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.command == "test-specialist" and report.get("status") not in {
        "PREVIEW_ONLY", "TEST_TRAINING_STARTED_CONFIRMED",
    }:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
