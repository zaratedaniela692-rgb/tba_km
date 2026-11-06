"""Coordinate confirmed visual lifecycle states with the persistent task queue."""

from datetime import datetime

from army_training_process import reconcile_training_goal
from task_controller import (
    TaskQueueError,
    _find_task,
    _parse_time,
    confirm_task_completed,
    mark_help_requested,
    mark_speedup_available,
    update_task_remaining_time,
    validate_task_queue,
)

VALID_TRAINING_STATES = {"active", "idle", "unknown"}
VALID_BUTTON_STATES = {"help", "speedup", "absent", "unknown"}


class TrainingLifecycleError(ValueError):
    """Invalid lifecycle evidence or an unsafe queue transition."""


def _pause_uncertain(queue, task_id):
    queue["paused"] = True
    queue["pause_reason"] = f"uncertain_help_action:{task_id}"


def confirm_help_action(queue, task_id, now: datetime, training_status, button_state):
    """Commit a Help click only after active training and the Speed Up button are observed."""
    validate_task_queue(queue)
    task = _find_task(queue, task_id)
    if task["status"] != "waiting_help_delay":
        raise TrainingLifecycleError("Help can only be confirmed from waiting_help_delay.")
    if training_status != "active" or button_state != "speedup":
        _pause_uncertain(queue, task_id)
        validate_task_queue(queue)
        return {"status": "paused", "reason": "help_click_result_uncertain"}
    mark_help_requested(queue, task_id, now)
    current_time = now
    if current_time.tzinfo is None:
        raise TrainingLifecycleError("A timezone-aware timestamp is required.")
    speedup_check_at = _parse_time(task["speedup_check_at"])
    if speedup_check_at is not None and current_time >= speedup_check_at:
        mark_speedup_available(queue, task_id, now)
    return {"status": task["status"], "reason": "help_click_confirmed"}


def advance_training_lifecycle(
    queue,
    task_id,
    now: datetime,
    training_status,
    button_state="unknown",
    remaining_seconds=None,
    observation=None,
    dry_run=True,
):
    """Plan or apply one lifecycle transition from explicit visual evidence.

    This function never clicks. The visual adapter must identify Help, Speed Up,
    active training, or idle state before the corresponding transition is applied.
    """
    validate_task_queue(queue)
    if training_status not in VALID_TRAINING_STATES:
        raise TrainingLifecycleError("Unknown training_status value.")
    if button_state not in VALID_BUTTON_STATES:
        raise TrainingLifecycleError("Unknown button_state value.")
    task = _find_task(queue, task_id)
    if queue["paused"]:
        return {"status": "paused", "action": "none", "reason": queue["pause_reason"]}

    if task["status"] == "waiting_help_delay":
        due_at = _parse_time(task["help_due_at"])
        if due_at is None or now < due_at:
            return {"status": task["status"], "action": "wait", "reason": "help_delay_not_elapsed"}
        if training_status == "active" and button_state == "help":
            return {"status": task["status"], "action": "click_help", "reason": "help_button_confirmed"}
        return {"status": task["status"], "action": "none", "reason": "help_button_or_active_state_uncertain"}

    if task["status"] == "waiting_speedup":
        check_at = _parse_time(task["speedup_check_at"])
        if check_at is None or now < check_at:
            return {"status": task["status"], "action": "wait", "reason": "speedup_settle_delay_not_elapsed"}
        if training_status != "active" or button_state != "speedup":
            return {"status": task["status"], "action": "wait", "reason": "speedup_button_not_confirmed"}
        if dry_run:
            return {"status": "ready_to_accelerate" if task["quick_finish"] else "waiting_completion", "action": "confirm_speedup", "reason": "speedup_button_confirmed"}
        updated = mark_speedup_available(queue, task_id, now)
        return {"status": updated["status"], "action": "manual_acceleration_required" if updated["quick_finish"] else "wait_for_completion", "reason": "speedup_button_confirmed"}

    if task["status"] == "ready_to_accelerate":
        return {"status": task["status"], "action": "manual_acceleration_required", "reason": "acceleration_dialog_not_implemented"}

    if task["status"] == "waiting_completion":
        if training_status == "active":
            if remaining_seconds is not None and not dry_run:
                update_task_remaining_time(queue, task_id, remaining_seconds)
            return {"status": task["status"], "action": "wait", "reason": "training_active"}
        if training_status != "idle":
            return {"status": task["status"], "action": "wait", "reason": "training_state_uncertain"}
        stock_goal = task["payload"].get("goal_kind") == "slot_stock_v1"
        if stock_goal and observation is None:
            return {"status": task["status"], "action": "reobserve_stock", "reason": "fresh_stock_observation_required"}
        if dry_run:
            return {"status": task["status"], "action": "complete_and_reconcile", "reason": "training_idle_confirmed"}
        confirm_task_completed(queue, task_id, now)
        decision = None
        if stock_goal:
            decision = reconcile_training_goal(queue, task_id, observation, now, dry_run=False)
        validate_task_queue(queue)
        return {
            "status": task["status"],
            "action": "goal_satisfied" if task["status"] == "completed" else "requeue_goal",
            "reason": decision.reason if decision is not None else "training_completed",
        }

    return {"status": task["status"], "action": "none", "reason": "no_lifecycle_transition"}