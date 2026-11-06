"""Finish step, expiry processing and fallback task for a training the bot has started."""

import time
from datetime import timedelta

from army_state import (
    clear_open_training,
    load_army_state,
    open_training,
    parse_marker_time,
    record_speedup_attempt,
)
from army_training_live_e2e import (
    EXPECTED_SIZE,
    LiveTrainingError,
    _check_emergency_stop,
    _read_current_training_state,
    capture_primary_monitor,
)
from task_controller import (
    DEFAULT_FINISH_GRACE_SECONDS,
    DEFAULT_SPEEDUP_RETRY_SECONDS,
    TaskQueueError,
    complete_task,
    enqueue_task,
    expire_tasks,
)
from ui_variants import resolve_variant

CONFIRMATION_PHRASE = "EXECUTE ARMY TRAINING"
FALLBACK_GOAL_KIND = "finish_training_v1"
VIEW_RESET_SECONDS = 5
NEEDS_ATTENTION_AFTER_ATTEMPTS = 3


def fallback_task_id(order_id):
    return f"army_finish:{order_id}"


def _setting(queue, key, default):
    return queue["settings"].get(key) or default


def finish_open_training(
    state_path, training_status, speedup_fn, now, retry_seconds=DEFAULT_SPEEDUP_RETRY_SECONDS,
    attention_after=NEEDS_ATTENTION_AFTER_ATTEMPTS,
):
    """Decide the finish step from the observed state; `speedup_fn()` must return the observed state afterwards.

    Never pauses the queue: a failed attempt keeps the marker and schedules the next attempt.
    """
    marker = open_training(load_army_state(state_path))
    if training_status == "idle":
        return {"status": "idle", "marker_cleared": clear_open_training(state_path) if marker else False}
    if training_status != "active":
        return {"status": "unknown", "reason": "training_state_unknown"}
    if marker is None:
        return {"status": "blocked", "reason": "foreign_training_active"}
    next_attempt_at = parse_marker_time(marker, "next_attempt_at")
    if next_attempt_at is not None and now < next_attempt_at:
        return {"status": "waiting", "reason": "speedup_retry_not_due", "next_attempt_at": next_attempt_at.isoformat()}

    attempted = speedup_fn is not None
    reason = "speedup_module_unavailable"
    if attempted:
        try:
            outcome = speedup_fn()
        except Exception as error:
            outcome, reason = "unknown", f"speedup_error:{error}"
        else:
            reason = "speedup_not_confirmed"
        if outcome == "idle":
            clear_open_training(state_path)
            return {"status": "finished", "reason": "speedup_confirmed_idle", "actions_attempted": True}
    updated = record_speedup_attempt(state_path, now, retry_seconds)
    return {
        "status": "failed",
        "reason": reason,
        "actions_attempted": attempted,
        "attempts": updated["speedup_attempts"],
        "next_attempt_at": updated["next_attempt_at"],
        "needs_attention": updated["speedup_attempts"] >= attention_after,
    }


def process_expirations(queue, state_path, now):
    """Close expired tasks and create the single fallback task for an open marker past its grace."""
    expired = expire_tasks(queue, now)
    marker = open_training(load_army_state(state_path))
    created = None
    if marker is not None:
        grace = _setting(queue, "finish_grace_seconds", DEFAULT_FINISH_GRACE_SECONDS)
        expires_at = parse_marker_time(marker, "expires_at")
        task_id = fallback_task_id(marker["order_id"])
        exists = any(task["task_id"] == task_id for task in queue["tasks"])
        if expires_at is not None and now >= expires_at + timedelta(seconds=grace) and not exists:
            enqueue_task(
                queue, "army_training", task_id=task_id, now=now,
                payload={"goal_kind": FALLBACK_GOAL_KIND, "order_id": marker["order_id"]},
            )
            created = task_id
    return {"expired": [task["task_id"] for task in expired], "fallback_created": created}


def execute_finish_task(
    queue,
    task_id,
    state_path,
    now,
    execute=False,
    confirmation="",
    capture_fn=None,
    speedup_fn=None,
    sleep_fn=time.sleep,
):
    """Run the fallback task: a no-op when the marker is gone, otherwise one finish step."""
    task = next((item for item in queue["tasks"] if item["task_id"] == task_id), None)
    if task is None or task["payload"].get("goal_kind") != FALLBACK_GOAL_KIND:
        raise TaskQueueError("Fallback finish task not found.")
    if task["status"] not in {"queued", "waiting_resources"}:
        raise TaskQueueError("Only a pending fallback task can run.")
    marker = open_training(load_army_state(state_path))
    if marker is None or marker.get("order_id") != task["payload"].get("order_id"):
        if execute:
            complete_task(queue, task_id, "marker_already_cleared", now)
        return {"status": "NOOP_MARKER_CLEARED", "actions_executed": False, "queue_modified": execute}
    if not execute:
        return {"status": "PREVIEW_ONLY", "actions_executed": False, "queue_modified": False}
    if confirmation != CONFIRMATION_PHRASE:
        raise LiveTrainingError(f"Live execution requires confirmation phrase: {CONFIRMATION_PHRASE}")

    capture_fn = capture_fn or capture_primary_monitor
    frame, _ = capture_fn()
    if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
        raise LiveTrainingError(f"Expected primary-monitor frame {EXPECTED_SIZE}, got {(frame.shape[1], frame.shape[0])}.")
    state = _read_current_training_state(frame, resolve_variant())["status"]

    def guarded_speedup():
        _check_emergency_stop()
        outcome = speedup_fn()
        sleep_fn(VIEW_RESET_SECONDS)
        return outcome

    retry = _setting(queue, "speedup_retry_seconds", DEFAULT_SPEEDUP_RETRY_SECONDS)
    outcome = finish_open_training(
        state_path, state, guarded_speedup if speedup_fn else None, now, retry,
    )
    result = {"status": outcome["status"].upper(), "finish": outcome, "actions_executed": bool(outcome.get("actions_attempted")), "queue_modified": False}
    if outcome["status"] in {"idle", "finished"}:
        complete_task(queue, task_id, "training_finished", now)
        result["queue_modified"] = True
    elif outcome.get("next_attempt_at"):
        task["next_check_at"] = outcome["next_attempt_at"]
        result["queue_modified"] = True
    return result
