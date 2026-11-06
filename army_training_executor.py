"""One-goal, manager-owned army training executor with no automatic click retries."""

import time
from dataclasses import asdict

from army_state import open_training_marker
from army_training_finish import CONFIRMATION_PHRASE, VIEW_RESET_SECONDS, finish_open_training
from army_training_levels import read_slot_selector_levels
from army_training_live_e2e import (
    EXPECTED_SIZE,
    LiveTrainingError,
    _build_selected_slot_plan,
    _check_emergency_stop,
    _click_screen_point,
    _enable_live_failsafe,
    _load_regions,
    _read_current_training_state,
    capture_primary_monitor,
)
from army_training_process import Slot, _transition, ProcessState
from army_training_resolver import STATUS_OK, resolve_goal_slot
from army_unit_types import DEFAULT_UNIT_TYPE
from army_training_slot_time import read_slot_training_time
from army_training_slots import STATUS_OK as LAYOUT_OK, locate_slots, slot_crop
from task_controller import ACTIVE_STATUSES, DEFAULT_SPEEDUP_RETRY_SECONDS, _parse_time, mark_task_started
from ui_variants import resolve_variant

MIN_CONFIDENCE = 70


def _find_same_slot(frame, variant, expected_slot):
    regions = _load_regions(variant["regions"]).get("army_training", {})
    layout = locate_slots(frame, regions, variant)
    if layout.status != LAYOUT_OK:
        return None
    matches = [
        slot for slot in layout.slots
        if abs(slot.dx - expected_slot.dx) <= 2 and abs(slot.dy - expected_slot.dy) <= 3
    ]
    return matches[0] if len(matches) == 1 else None


def _level_click_point(frame, slot, target_level):
    reading = read_slot_selector_levels(frame, slot)
    if reading.status != "candidate" or reading.lowest_visible_level is None:
        return None, "selector_range_uncertain"
    if not reading.lowest_visible_level <= target_level <= reading.highest_visible_level:
        return None, "target_level_not_in_selector"
    badge_index = target_level - reading.lowest_visible_level
    if badge_index >= len(reading.badge_centers):
        return None, "target_badge_not_detected"
    badge = reading.badge_centers[badge_index]
    region = slot.regions["unit_troop_level"]
    return (region["x"] + int(badge[0]), region["y"] + int(badge[1])), None


def _record_uncertain(task, reason, now, pause=False, queue=None):
    process = task["payload"]["process"]
    _transition(task, ProcessState.BLOCKED, reason, now)
    process["decision"] = None
    process["decision_valid_until"] = None
    task["next_check_at"] = None
    if pause and queue is not None:
        queue["paused"] = True
        queue["pause_reason"] = f"uncertain_training_start:{task['task_id']}"


def execute_training_goal(
    queue,
    task_id,
    now,
    execute=False,
    confirmation="",
    capture_fn=None,
    click_fn=None,
    sleep_fn=time.sleep,
    state_path=None,
    speedup_fn=None,
):
    """Execute at most one stock goal. Callers must persist the mutated queue afterward."""
    if not execute:
        return {"status": "PREVIEW_ONLY", "actions_executed": False, "queue_modified": False, "task_id": task_id}
    if confirmation != CONFIRMATION_PHRASE:
        raise LiveTrainingError(f"Live execution requires confirmation phrase: {CONFIRMATION_PHRASE}")

    from army_training_process import _goal_task

    task = _goal_task(queue, task_id)
    if queue["paused"]:
        raise LiveTrainingError("Profile queue is paused.")
    if task["status"] not in {"queued", "waiting_resources"}:
        raise LiveTrainingError("Only a pending stock goal can be executed.")
    active_tasks = [item for item in queue["tasks"] if item["task_id"] != task_id and item["status"] in ACTIVE_STATUSES]
    threshold = queue["settings"]["parallel_wait_threshold_seconds"]
    if any(item["task_type"] == task["task_type"] for item in active_tasks) or any(
        item["status"] != "waiting_completion"
        or item["last_remaining_seconds"] is None
        or item["last_remaining_seconds"] <= threshold
        for item in active_tasks
    ):
        raise LiveTrainingError("Task queue lifecycle gates do not allow this goal to start.")
    capture_fn = capture_fn or capture_primary_monitor
    click_fn = click_fn or _click_screen_point
    variant = resolve_variant()
    regions = _load_regions(variant["regions"])
    goal_slot = Slot(**task["payload"]["slot"])
    if goal_slot.unit_type != DEFAULT_UNIT_TYPE:
        raise LiveTrainingError("Training execution is not verified for this unit type.")

    def observe():
        frame, origin = capture_fn()
        if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
            raise LiveTrainingError(f"Expected primary-monitor frame {EXPECTED_SIZE}, got {(frame.shape[1], frame.shape[0])}.")
        layout = locate_slots(frame, regions.get("army_training", {}), variant)
        if layout.status != LAYOUT_OK:
            raise LiveTrainingError("Visible slot geometry is not confirmed.")
        level_readings = tuple(read_slot_selector_levels(frame, slot) for slot in layout.slots)
        resolution = resolve_goal_slot(
            level_readings, goal_slot.unit_type, goal_slot.global_level, goal_slot.match_number,
        )
        if resolution.status != STATUS_OK:
            raise LiveTrainingError(f"Goal slot resolution failed: {resolution.reason}")
        return frame, origin, layout.slots[resolution.frame_index], _read_current_training_state(frame, variant)

    frame, origin, selected_slot, before_state = observe()
    result = {
        "mode": "manager_execute_one_goal",
        "task_id": task_id,
        "goal": asdict(goal_slot),
        "frame_index": selected_slot.index,
        "selection_confirmed": False,
        "actions_executed": False,
        "queue_modified": False,
        "status": "PREPARED",
        "blockers": [],
    }
    if before_state["status"] != "idle":
        if state_path is None:
            raise LiveTrainingError(f"Training is not confirmed idle ({before_state['status']}).")
        finish = finish_open_training(
            state_path, before_state["status"], speedup_fn, now,
            queue["settings"].get("speedup_retry_seconds") or DEFAULT_SPEEDUP_RETRY_SECONDS,
        )
        result["finish"] = finish
        if finish["status"] not in {"idle", "finished"}:
            result.update(
                status="BLOCKED_PENDING_FINISH",
                blockers=[finish.get("reason", "previous_training_not_finished")],
                actions_executed=bool(finish.get("actions_attempted")),
            )
            if finish.get("next_attempt_at"):
                task["next_check_at"] = finish["next_attempt_at"]
                result["queue_modified"] = True
            return result
        result["actions_executed"] = bool(finish.get("actions_attempted"))
        sleep_fn(VIEW_RESET_SECONDS)
        frame, origin, selected_slot, before_state = observe()
        if before_state["status"] != "idle":
            raise LiveTrainingError(f"Training is not idle after finishing the previous one ({before_state['status']}).")
        result["frame_index"] = selected_slot.index
    click_point, selection_error = _level_click_point(frame, selected_slot, goal_slot.global_level)
    if selection_error:
        raise LiveTrainingError(selection_error)
    level_reading = read_slot_selector_levels(frame, selected_slot)
    if goal_slot.global_level != level_reading.highest_visible_level:
        _check_emergency_stop()
        _enable_live_failsafe(click_fn)
        result["actions_executed"] = True
        result["level_click_attempted"] = True
        try:
            click_fn(click_point, origin)
            result["level_click_issued"] = True
        except Exception as error:
            result.update(status="UNKNOWN_AFTER_LEVEL_CLICK_ATTEMPT", blockers=[f"level_click_result_uncertain:{error}"])
            _record_uncertain(task, result["status"], now)
            return result
        sleep_fn(0.25)
        try:
            frame, new_origin = capture_fn()
            if new_origin != origin or (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
                raise LiveTrainingError("Capture geometry changed after level selection.")
            selected_slot = _find_same_slot(frame, variant, selected_slot)
            if selected_slot is None:
                raise LiveTrainingError("Same slot not confirmed after level selection.")
        except Exception as error:
            result.update(status="UNKNOWN_AFTER_LEVEL_CLICK", blockers=[f"post_selection_check_failed_stop_without_retry:{error}"])
            _record_uncertain(task, result["status"], now)
            return result

    try:
        _check_emergency_stop()
        current_state = _read_current_training_state(frame, variant)
        if current_state["status"] != "idle":
            raise LiveTrainingError(f"Training changed before Train ({current_state['status']}).")
        plan = _build_selected_slot_plan(frame, variant, selected_slot)
        result["preflight"] = plan
        if plan["blockers"]:
            result.update(status="BLOCKED_BEFORE_TRAIN", blockers=plan["blockers"])
            return result
        time_reading = read_slot_training_time(frame, selected_slot)
        if time_reading.value is None or time_reading.confidence is None or time_reading.confidence < MIN_CONFIDENCE:
            raise LiveTrainingError(f"Training time is uncertain ({time_reading.raw}); refusing Train click.")
    except Exception as error:
        result.update(status="BLOCKED_BEFORE_TRAIN", blockers=[str(error)])
        return result

    train_region = selected_slot.regions["unit_troop_train_button"]
    train_point = (train_region["x"] + train_region["w"] // 2, train_region["y"] + train_region["h"] // 2)
    _check_emergency_stop()
    result["train_click_attempted"] = True
    result["actions_executed"] = True
    result["queue_modified"] = "unknown"
    try:
        click_fn(train_point, origin)
        result["train_click_issued"] = True
    except Exception as error:
        result.update(status="UNKNOWN_AFTER_TRAIN_CLICK_ATTEMPT", blockers=[f"train_click_result_uncertain_do_not_retry:{error}"])
        _record_uncertain(task, result["status"], now, pause=True, queue=queue)
        return result
    result["actions_executed"] = True
    sleep_fn(0.5)
    try:
        after_frame, after_origin = capture_fn()
        if after_origin != origin or (after_frame.shape[1], after_frame.shape[0]) != EXPECTED_SIZE:
            raise LiveTrainingError("Post-click capture geometry changed.")
        after_state = _read_current_training_state(after_frame, variant)
    except Exception as error:
        result.update(status="UNKNOWN_AFTER_CLICK", blockers=[f"post_click_confirmation_failed_do_not_retry:{error}"])
        _record_uncertain(task, result["status"], now, pause=True, queue=queue)
        return result
    result["post_click_training_state"] = after_state["status"]
    if after_state["status"] != "active":
        result.update(status="UNKNOWN_AFTER_CLICK", blockers=["train_click_not_visually_confirmed_do_not_retry"])
        _record_uncertain(task, result["status"], now, pause=True, queue=queue)
        return result

    mark_task_started(queue, task_id, time_reading.value, now=now)
    if state_path is not None:
        open_training_marker(
            state_path, f"{task_id}@{now.isoformat()}", task_id, asdict(goal_slot), now,
            _parse_time(task["expires_at"]),
        )
    result.update(
        status="START_CONFIRMED",
        queue_modified=True,
        actions_executed=True,
        initial_remaining_seconds=time_reading.value,
        initial_time_reading=asdict(time_reading),
        blockers=[],
    )
    return result
