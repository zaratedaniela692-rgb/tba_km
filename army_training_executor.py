"""One-goal, manager-owned army training executor with no automatic click retries."""

import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from army_state import open_training_marker
from army_training_lifecycle import advance_training_lifecycle, confirm_help_action
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
from army_training_slot_reader import read_slot_readings
from army_training_process import Slot, _transition, ProcessState
from army_training_resolver import STATUS_OK, resolve_goal_slot
from army_unit_types import DEFAULT_UNIT_TYPE
from army_training_slot_time import read_slot_training_time
from army_training_slots import STATUS_OK as LAYOUT_OK, locate_slots, slot_crop
from task_controller import ACTIVE_STATUSES, DEFAULT_SPEEDUP_RETRY_SECONDS, _parse_time, mark_task_started, task_parallelism_blocker, record_resource_retry_failure, army_training_start_is_held
from ui_variants import resolve_variant
from workflow_trace import record_live_checkpoint

MIN_CONFIDENCE = 70


def try_replenish_hidden_silver(profile_id, shortfall):
    """Reserved for an approved hidden-resource workflow; currently sends no input."""
    return {"status": "not_implemented", "reason": "hidden_silver_recovery_not_implemented"}


def _confirmed_silver_shortfall(plan):
    if set(plan.get("blockers", [])) != {"silver_insufficient_or_uncertain"}:
        return None
    resources = plan.get("resources", {})
    if not resources or any(not value.get("confidence_ok") or value.get("value") is None for value in resources.values()):
        return None
    silver = resources.get("silver", {}).get("value")
    readings = plan.get("readings", {})
    for key in ("queue_limit", "city_count", "silver_cost"):
        reading = readings.get(key, {})
        confidence = reading.get("confidence")
        if reading.get("value") is None or confidence is None or not MIN_CONFIDENCE <= confidence <= 100:
            return None
    cost = readings["silver_cost"]["value"]
    return cost - silver if silver is not None and 0 <= silver < cost else None


def _reading_is_reliable(reading):
    return (
        reading.value is not None
        and reading.confidence is not None
        and MIN_CONFIDENCE <= reading.confidence <= 100
    )


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


def _pause_uncertain_help(queue, task_id):
    queue["paused"] = True
    queue["pause_reason"] = f"uncertain_help_action:{task_id}"


def _quantity_keyboard(press_key_fn=None, write_text_fn=None):
    if press_key_fn is not None and write_text_fn is not None:
        return press_key_fn, write_text_fn
    try:
        import pyautogui
    except ImportError as error:
        raise LiveTrainingError("Live quantity entry requires the 'pyautogui' package.") from error
    return press_key_fn or pyautogui.press, write_text_fn or pyautogui.write


def _enter_training_quantity(slot, quantity, origin, click_fn, press_key_fn, write_text_fn):
    region = slot.regions.get("unit_troop_count_to_train")
    if not region:
        raise LiveTrainingError("Training quantity field region is missing.")
    point = (region["x"] + region["w"] // 2, region["y"] + region["h"] // 2)
    _check_emergency_stop()
    _enable_live_failsafe(click_fn)
    click_fn(point, origin)
    _check_emergency_stop()
    press_key_fn("backspace", presses=6)
    _check_emergency_stop()
    write_text_fn(str(quantity))
    return point


def finish_active_training_for_test(
    frame,
    origin,
    profile_id,
    capture_fn,
    click_fn=None,
    speedup_fn=None,
    sleep_fn=time.sleep,
):
    """Finish existing training for the isolated E2E test, without input retries."""
    if profile_id != "test":
        raise LiveTrainingError("Finishing unmarked training is allowed only for the test profile.")
    click_fn = click_fn or _click_screen_point
    variant = resolve_variant()
    if variant["id"] not in {"legacy", "desktop"}:
        raise LiveTrainingError("Test training finish requires the verified desktop variant.")
    expected_origin = tuple(origin)
    actions_executed = False
    step = "test_finish_initial_state"

    def read_state():
        _check_emergency_stop()
        if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE or tuple(origin) != expected_origin:
            raise LiveTrainingError("Capture geometry changed during test training finish.")
        return _read_current_training_state(frame, variant, include_numeric=False)

    def observe():
        nonlocal frame, origin
        _check_emergency_stop()
        frame, origin = capture_fn()
        return read_state()

    def click_point(point, action):
        nonlocal actions_executed
        if not (0 <= point[0] < EXPECTED_SIZE[0] and 0 <= point[1] < EXPECTED_SIZE[1]):
            raise LiveTrainingError("Training button is outside the verified frame.")
        _check_emergency_stop()
        _enable_live_failsafe(click_fn)
        record_live_checkpoint(step, profile_id=profile_id, decision="click", action=action, monitor_origin=origin)
        actions_executed = True
        click_fn(point, origin)

    def click_region(button_region, action):
        if not isinstance(button_region, dict):
            raise LiveTrainingError("Training button location is not recognized.")
        point = (
            int(button_region["x"]) + int(button_region["w"]) // 2,
            int(button_region["y"]) + int(button_region["h"]) // 2,
        )
        click_point(point, action)

    def click_finish():
        finish_point = state.get("finish_button_point")
        if finish_point is None:
            raise LiveTrainingError("Completed training has no confidently detected Finish button.")
        click_point(finish_point, "click_finish")
        sleep_fn(0.5)

    try:
        state = read_state()
        if state["status"] == "idle":
            return {"status": "IDLE", "actions_executed": False}
        if state["status"] == "completed":
            step = "test_finish_button"
            click_finish()
            state = observe()
        elif state["status"] == "active":
            if state.get("button_state") == "help":
                step = "test_finish_help"
                click_region(state.get("training_button_region"), "click_help")
                sleep_fn(0.2)
                state = observe()
                if state["status"] != "active" or state.get("button_state") != "speedup":
                    raise LiveTrainingError("Help click did not produce a confirmed Speed Up button.")
            if state.get("button_state") != "speedup":
                raise LiveTrainingError("Active training has no confirmed Speed Up button.")
            step = "test_finish_speedup"
            click_region(state.get("training_button_region"), "open_speedup")
            sleep_fn(0.35)
            _check_emergency_stop()
            if speedup_fn is None:
                from speedup_live import run_desktop_speedups

                speedup_result = run_desktop_speedups(execute=True)[0]
            else:
                speedup_result = speedup_fn()
            if speedup_result.status != "FINISHED":
                raise LiveTrainingError(
                    f"Speed Up did not finish training: {speedup_result.status} ({speedup_result.reason})."
                )
            sleep_fn(VIEW_RESET_SECONDS)
            step = "test_finish_postcondition"
            state = observe()
            if state["status"] == "completed":
                step = "test_finish_button"
                click_finish()
                state = observe()
        else:
            raise LiveTrainingError(f"Training state is not confirmed: {state['status']}.")
        if state["status"] != "idle":
            raise LiveTrainingError(f"Training did not return to idle: {state['status']}.")
        record_live_checkpoint(
            "test_finish_idle", profile_id=profile_id, decision="continue",
            verification="idle_confirmed", monitor_origin=origin,
        )
        return {"status": "FINISHED", "actions_executed": actions_executed}
    except Exception as error:
        record_live_checkpoint(
            step, profile_id=profile_id, decision="uncertain" if actions_executed else "blocked",
            reason=str(error), frame=frame, monitor_origin=origin,
        )
        raise LiveTrainingError(f"Test training finish stopped without retry: {error}") from error


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
    quantity=None,
    press_key_fn=None,
    write_text_fn=None,
):
    """Execute at most one stock goal. Callers must persist the mutated queue afterward."""
    if not execute:
        return {"status": "PREVIEW_ONLY", "actions_executed": False, "queue_modified": False, "task_id": task_id}
    if confirmation != CONFIRMATION_PHRASE:
        raise LiveTrainingError(f"Live execution requires confirmation phrase: {CONFIRMATION_PHRASE}")
    if quantity is not None and (isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0):
        raise LiveTrainingError("Training quantity must be a positive integer.")

    from army_training_process import _goal_task

    task = _goal_task(queue, task_id)
    if queue["paused"]:
        raise LiveTrainingError("Profile queue is paused.")
    if task["status"] not in {"queued", "waiting_resources"}:
        raise LiveTrainingError("Only a pending stock goal can be executed.")
    if army_training_start_is_held(queue, task):
        raise LiveTrainingError("New army training is held; explicit resume is required.")
    next_check = _parse_time(task.get("next_check_at"))
    if next_check is not None and now < next_check:
        raise LiveTrainingError("Training goal retry is not due yet.")
    active_tasks = [item for item in queue["tasks"] if item["task_id"] != task_id and item["status"] in ACTIVE_STATUSES]
    threshold = queue["settings"]["parallel_wait_threshold_seconds"]
    if task_parallelism_blocker(task, active_tasks, threshold) is not None:
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
            record_live_checkpoint(
                "training_frame_geometry", profile_id=queue.get("profile_id"), decision="blocked",
                observation={"expected": EXPECTED_SIZE, "actual": (frame.shape[1], frame.shape[0])},
                reason="unsupported_frame_size", frame=frame, monitor_origin=origin,
            )
            raise LiveTrainingError(f"Expected primary-monitor frame {EXPECTED_SIZE}, got {(frame.shape[1], frame.shape[0])}.")
        layout = locate_slots(frame, regions.get("army_training", {}), variant)
        if layout.status != LAYOUT_OK:
            record_live_checkpoint(
                "training_slot_layout", profile_id=queue.get("profile_id"), decision="blocked",
                observation={"status": layout.status, "reason": layout.reason},
                reason="slot_layout_unconfirmed", frame=frame, monitor_origin=origin,
            )
            raise LiveTrainingError("Visible slot geometry is not confirmed.")
        level_readings = tuple(read_slot_selector_levels(frame, slot) for slot in layout.slots)
        resolution = resolve_goal_slot(
            level_readings, goal_slot.unit_type, goal_slot.global_level, goal_slot.match_number,
        )
        if resolution.status != STATUS_OK:
            record_live_checkpoint(
                "training_slot_resolution", profile_id=queue.get("profile_id"), decision="blocked",
                observation={"status": resolution.status, "reason": resolution.reason,
                "candidates": resolution.candidates}, reason="goal_slot_unresolved",
                frame=frame, monitor_origin=origin,
            )
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
        "requested_quantity": quantity,
    }
    if before_state["status"] != "idle":
        if state_path is None:
            record_live_checkpoint(
                "preexisting_training", profile_id=queue.get("profile_id"), decision="blocked",
                observation={"training_status": before_state["status"]},
                reason="no_state_path_for_owned_training", frame=frame, monitor_origin=origin,
            )
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
            record_live_checkpoint(
                "previous_training_finish", profile_id=queue.get("profile_id"), decision="blocked",
                observation=finish, reason=finish.get("reason", "previous_training_not_finished"),
                frame=frame, monitor_origin=origin,
            )
            if finish.get("next_attempt_at"):
                task["next_check_at"] = finish["next_attempt_at"]
                result["queue_modified"] = True
            return result
        result["actions_executed"] = bool(finish.get("actions_attempted"))
        sleep_fn(VIEW_RESET_SECONDS)
        frame, origin, selected_slot, before_state = observe()
        if before_state["status"] != "idle":
            record_live_checkpoint(
                "idle_after_finish", profile_id=queue.get("profile_id"), decision="blocked",
                observation={"training_status": before_state["status"]},
                reason="training_not_idle_after_finish", frame=frame, monitor_origin=origin,
            )
            raise LiveTrainingError(f"Training is not idle after finishing the previous one ({before_state['status']}).")
        result["frame_index"] = selected_slot.index
    click_point, selection_error = _level_click_point(frame, selected_slot, goal_slot.global_level)
    if selection_error:
        record_live_checkpoint(
            "level_selector_resolution", profile_id=queue.get("profile_id"), decision="blocked",
            observation={"target_level": goal_slot.global_level}, reason=selection_error,
            frame=frame, monitor_origin=origin,
        )
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
            evidence_frame, evidence_origin = frame, origin
            try:
                evidence_frame, evidence_origin = capture_fn()
            except Exception:
                pass
            record_live_checkpoint(
                "selector_click_result", profile_id=queue.get("profile_id"), decision="uncertain",
                action="select_level", reason=str(error), frame=evidence_frame, monitor_origin=evidence_origin,
            )
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
            record_live_checkpoint(
                "selector_verified", profile_id=queue.get("profile_id"), decision="continue",
                action="select_level", observation={"target_level": goal_slot.global_level,
                "frame_index": selected_slot.index}, verification="same_slot_detected", frame=frame,
                monitor_origin=new_origin,
            )
        except Exception as error:
            result.update(status="UNKNOWN_AFTER_LEVEL_CLICK", blockers=[f"post_selection_check_failed_stop_without_retry:{error}"])
            record_live_checkpoint(
                "selector_verification", profile_id=queue.get("profile_id"), decision="uncertain",
                action="select_level", reason=str(error), frame=frame, monitor_origin=origin,
            )
            _record_uncertain(task, result["status"], now)
            return result

    try:
        _check_emergency_stop()
        current_state = _read_current_training_state(frame, variant)
        if current_state["status"] != "idle":
            raise LiveTrainingError(f"Training changed before Train ({current_state['status']}).")
        goal_queue_limit = None
        if quantity is not None:
            current_readings = read_slot_readings(frame, selected_slot)
            if not _reading_is_reliable(current_readings.queue_limit):
                record_live_checkpoint(
                    "quantity_limit_read", profile_id=queue.get("profile_id"), decision="blocked",
                    observation={"raw": current_readings.queue_limit.raw,
                    "value": current_readings.queue_limit.value,
                    "confidence": current_readings.queue_limit.confidence},
                    reason="queue_limit_unreliable", frame=frame, monitor_origin=origin,
                )
                raise LiveTrainingError("Maximum training queue is uncertain; refusing quantity entry.")
            goal_queue_limit = current_readings.queue_limit.value
            if quantity > goal_queue_limit:
                record_live_checkpoint(
                    "quantity_limit_check", profile_id=queue.get("profile_id"), decision="blocked",
                    observation={"requested": quantity, "maximum": goal_queue_limit},
                    reason="requested_quantity_exceeds_queue_limit", frame=frame, monitor_origin=origin,
                )
                raise LiveTrainingError(
                    f"Requested quantity {quantity} exceeds the visible queue maximum {goal_queue_limit}."
                )
            initial_plan = _build_selected_slot_plan(
                frame, variant, selected_slot,
                requested_quantity=quantity,
                goal_queue_limit=goal_queue_limit,
                check_silver=False,
            )
            result["preflight_before_quantity"] = initial_plan
            if initial_plan["blockers"]:
                result.update(status="BLOCKED_BEFORE_QUANTITY", blockers=initial_plan["blockers"])
                record_live_checkpoint(
                    "quantity_preflight", profile_id=queue.get("profile_id"), decision="blocked",
                    observation=initial_plan, reason="preflight_blockers", frame=frame,
                )
                return result
            press_key_fn, write_text_fn = _quantity_keyboard(press_key_fn, write_text_fn)
            result["actions_executed"] = True
            result["quantity_input_attempted"] = True
            quantity_frame = None
            try:
                record_live_checkpoint(
                    "quantity_input_started", profile_id=queue.get("profile_id"), decision="set_quantity",
                    action={"quantity": quantity, "point": (
                        selected_slot.regions["unit_troop_count_to_train"]["x"]
                        + selected_slot.regions["unit_troop_count_to_train"]["w"] // 2,
                        selected_slot.regions["unit_troop_count_to_train"]["y"]
                        + selected_slot.regions["unit_troop_count_to_train"]["h"] // 2,
                    )}, monitor_origin=origin,
                )
                result["quantity_input_point"] = _enter_training_quantity(
                    selected_slot, quantity, origin, click_fn, press_key_fn, write_text_fn,
                )
                result["quantity_input_issued"] = True
                sleep_fn(0.2)
                quantity_frame, quantity_origin = capture_fn()
                if quantity_origin != origin or (quantity_frame.shape[1], quantity_frame.shape[0]) != EXPECTED_SIZE:
                    raise LiveTrainingError("Capture geometry changed after quantity entry.")
                selected_slot = _find_same_slot(quantity_frame, variant, selected_slot)
                if selected_slot is None:
                    raise LiveTrainingError("Same training slot was not confirmed after quantity entry.")
                quantity_state = _read_current_training_state(quantity_frame, variant)
                if quantity_state["status"] != "idle":
                    raise LiveTrainingError(
                        f"Training changed after quantity entry ({quantity_state['status']})."
                    )
                quantity_reading = read_slot_readings(quantity_frame, selected_slot).queue_limit
                if not _reading_is_reliable(quantity_reading) or quantity_reading.value != quantity:
                    raise LiveTrainingError(
                        f"Requested quantity was not confirmed by OCR ({quantity_reading.raw!r})."
                    )
                result["quantity_confirmed"] = quantity_reading.value
                frame = quantity_frame
                record_live_checkpoint(
                    "quantity_verified", profile_id=queue.get("profile_id"), decision="continue",
                    action={"quantity": quantity},
                    observation={"raw": quantity_reading.raw, "confidence": quantity_reading.confidence,
                    "value": quantity_reading.value}, verification="ocr_matches_request", frame=quantity_frame,
                    monitor_origin=quantity_origin,
                )
            except Exception as error:
                result.update(
                    status="BLOCKED_QUANTITY_UNCONFIRMED",
                    blockers=[f"quantity_input_or_verification_failed_do_not_train:{error}"],
                )
                record_live_checkpoint(
                    "quantity_verification", profile_id=queue.get("profile_id"), decision="blocked",
                    action={"quantity": quantity}, reason=str(error),
                    frame=quantity_frame if quantity_frame is not None else frame,
                    monitor_origin=quantity_origin if "quantity_origin" in locals() else origin,
                )
                return result
        plan = _build_selected_slot_plan(
            frame, variant, selected_slot,
            requested_quantity=quantity,
            goal_queue_limit=goal_queue_limit,
        )
        result["preflight"] = plan
        if plan["blockers"]:
            result.update(status="BLOCKED_BEFORE_TRAIN", blockers=plan["blockers"])
            shortfall = _confirmed_silver_shortfall(plan)
            if shortfall is not None:
                recovery = try_replenish_hidden_silver(queue["profile_id"], shortfall)
                if recovery["status"] != "not_implemented":
                    raise LiveTrainingError("Hidden silver recovery requires a fresh-preflight integration before use.")
                updated = record_resource_retry_failure(
                    queue, task_id, "silver_insufficient", recovery["status"], now=now,
                )
                _transition(task, ProcessState.BLOCKED, "silver_insufficient", now)
                task["payload"]["process"].update(decision=None, decision_valid_until=None)
                result.update(
                    status="ARMY_TRAINING_HELD" if queue.get("army_training_hold") else "WAITING_RESOURCES",
                    queue_modified=True, resource_retry=updated["resource_retry"],
                    next_check_at=updated["next_check_at"], recovery=recovery,
                    army_training_hold=queue.get("army_training_hold"), silver_shortfall=shortfall,
                )
            record_live_checkpoint(
                "train_preflight", profile_id=queue.get("profile_id"), decision="blocked",
                observation=plan, reason="preflight_blockers", frame=frame, monitor_origin=origin,
            )
            return result
        time_reading = read_slot_training_time(frame, selected_slot)
        if time_reading.value is None or time_reading.confidence is None or time_reading.confidence < MIN_CONFIDENCE:
            raise LiveTrainingError(f"Training time is uncertain ({time_reading.raw}); refusing Train click.")
    except Exception as error:
        result.update(status="BLOCKED_BEFORE_TRAIN", blockers=[str(error)])
        record_live_checkpoint(
            "train_preflight_exception", profile_id=queue.get("profile_id"), decision="blocked",
            reason=str(error), frame=frame, monitor_origin=origin,
        )
        return result

    train_region = selected_slot.regions["unit_troop_train_button"]
    train_point = (train_region["x"] + train_region["w"] // 2, train_region["y"] + train_region["h"] // 2)
    _check_emergency_stop()
    record_live_checkpoint(
        "train_click_started", profile_id=queue.get("profile_id"), decision="click",
        action={"point": train_point, "quantity": quantity},
        observation={"preflight": result.get("preflight"), "training_seconds": time_reading.value},
        monitor_origin=origin,
    )
    result["train_click_attempted"] = True
    result["actions_executed"] = True
    result["queue_modified"] = "unknown"
    try:
        click_fn(train_point, origin)
        result["train_click_issued"] = True
    except Exception as error:
        result.update(status="UNKNOWN_AFTER_TRAIN_CLICK_ATTEMPT", blockers=[f"train_click_result_uncertain_do_not_retry:{error}"])
        evidence_frame, evidence_origin = frame, origin
        try:
            evidence_frame, evidence_origin = capture_fn()
        except Exception:
            pass
        record_live_checkpoint(
            "train_click_result", profile_id=queue.get("profile_id"), decision="uncertain",
            action={"point": train_point}, reason=str(error), frame=evidence_frame,
            monitor_origin=evidence_origin,
        )
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
        evidence_frame, evidence_origin = frame, origin
        try:
            evidence_frame, evidence_origin = capture_fn()
        except Exception:
            pass
        record_live_checkpoint(
            "train_postcondition", profile_id=queue.get("profile_id"), decision="uncertain",
            action="click_train", reason=str(error), frame=evidence_frame, monitor_origin=evidence_origin,
        )
        _record_uncertain(task, result["status"], now, pause=True, queue=queue)
        return result
    result["post_click_training_state"] = after_state["status"]
    record_live_checkpoint(
        "train_postcondition", profile_id=queue.get("profile_id"),
        decision="continue" if after_state["status"] == "active" else "stop",
        action="click_train", observation={"training_status": after_state["status"], "quantity": quantity},
        verification="active_training_detected" if after_state["status"] == "active" else "not_confirmed",
        frame=after_frame, monitor_origin=after_origin,
    )
    if after_state["status"] != "active":
        result.update(status="UNKNOWN_AFTER_CLICK", blockers=["train_click_not_visually_confirmed_do_not_retry"])
        _record_uncertain(task, result["status"], now, pause=True, queue=queue)
        return result

    started_at = datetime.now(timezone.utc)
    mark_task_started(queue, task_id, time_reading.value, now=started_at)
    if state_path is not None:
        open_training_marker(
            state_path, f"{task_id}@{started_at.isoformat()}", task_id, asdict(goal_slot), started_at,
            _parse_time(task["expires_at"]),
        )
    record_live_checkpoint(
        "task_started", profile_id=queue.get("profile_id"), decision="persisted",
        observation={"task_id": task_id, "status": task.get("status"), "quantity": quantity,
        "initial_remaining_seconds": time_reading.value}, verification="training_marker_written",
        monitor_origin=after_origin,
    )
    return _request_help_after_confirmed_start(
        queue, task, result, started_at, time_reading, frame, origin, variant,
        capture_fn, click_fn, sleep_fn,
    )


def _request_help_after_confirmed_start(
    queue, task, result, started_at, time_reading, frame, origin, variant,
    capture_fn, click_fn, sleep_fn,
):
    task_id = task["task_id"]
    post_order_delay = queue["settings"]["post_order_delay_seconds"]
    sleep_fn(post_order_delay)
    help_requested_at = started_at + timedelta(seconds=post_order_delay)
    try:
        help_frame, help_origin = capture_fn()
        if help_origin != origin or (help_frame.shape[1], help_frame.shape[0]) != EXPECTED_SIZE:
            raise LiveTrainingError("Capture geometry changed before Help click.")
        help_state = _read_current_training_state(help_frame, variant, include_numeric=False)
    except Exception as error:
        _pause_uncertain_help(queue, task_id)
        result.update(
            status="START_CONFIRMED_HELP_UNCERTAIN",
            blockers=[f"help_state_read_failed_do_not_click:{error}"],
            queue_modified=True,
        )
        record_live_checkpoint(
            "help_state_read", profile_id=queue.get("profile_id"), decision="blocked",
            action="inspect_help_button", reason=str(error),
            frame=help_frame if "help_frame" in locals() else frame,
            monitor_origin=help_origin if "help_origin" in locals() else origin,
        )
        return result
    result["help_button_state_before_click"] = help_state.get("button_state", "unknown")
    button_region = help_state.get("training_button_region")
    if help_state["status"] != "active" or help_state.get("button_state") != "help" or not button_region:
        _pause_uncertain_help(queue, task_id)
        result.update(
            status="START_CONFIRMED_HELP_UNCERTAIN",
            blockers=["active_training_and_panel_help_button_not_confirmed_do_not_click"],
            queue_modified=True,
        )
        record_live_checkpoint(
            "help_precondition", profile_id=queue.get("profile_id"), decision="blocked",
            action="click_help", observation={"training_status": help_state["status"],
            "button_state": help_state.get("button_state")}, reason="help_not_confirmed", frame=help_frame,
            monitor_origin=help_origin,
        )
        return result

    help_point = (
        button_region["x"] + button_region["w"] // 2,
        button_region["y"] + button_region["h"] // 2,
    )
    try:
        _check_emergency_stop()
    except Exception as error:
        result.update(
            status="START_CONFIRMED_HELP_BLOCKED",
            blockers=[f"emergency_stop_before_help_click:{error}"],
            queue_modified=True,
        )
        return result
    result["help_click_attempted"] = True
    record_live_checkpoint(
        "help_click_started", profile_id=queue.get("profile_id"), decision="click",
        action={"point": help_point}, observation={"button_state": help_state.get("button_state")},
        monitor_origin=help_origin,
    )
    try:
        click_fn(help_point, origin)
        result["help_click_issued"] = True
    except Exception as error:
        _pause_uncertain_help(queue, task_id)
        result.update(
            status="UNKNOWN_AFTER_HELP_CLICK_ATTEMPT",
            blockers=[f"help_click_result_uncertain_do_not_retry:{error}"],
            queue_modified=True,
        )
        evidence_frame, evidence_origin = help_frame, help_origin
        try:
            evidence_frame, evidence_origin = capture_fn()
        except Exception:
            pass
        record_live_checkpoint(
            "help_click_result", profile_id=queue.get("profile_id"), decision="uncertain",
            action={"point": help_point}, reason=str(error), frame=evidence_frame,
            monitor_origin=evidence_origin,
        )
        return result

    settle_delay = queue["settings"]["help_to_speedup_delay_seconds"]
    sleep_fn(settle_delay)
    try:
        confirmed_frame, confirmed_origin = capture_fn()
        if confirmed_origin != origin or (confirmed_frame.shape[1], confirmed_frame.shape[0]) != EXPECTED_SIZE:
            raise LiveTrainingError("Capture geometry changed after Help click.")
        confirmed_state = _read_current_training_state(
            confirmed_frame, variant, include_numeric=False,
        )
    except Exception as error:
        _pause_uncertain_help(queue, task_id)
        result.update(
            status="UNKNOWN_AFTER_HELP_CLICK",
            blockers=[f"help_confirmation_failed_do_not_retry:{error}"],
            queue_modified=True,
        )
        record_live_checkpoint(
            "help_postcondition", profile_id=queue.get("profile_id"), decision="uncertain",
            action="click_help", reason=str(error),
            frame=confirmed_frame if "confirmed_frame" in locals() else help_frame,
            monitor_origin=confirmed_origin if "confirmed_origin" in locals() else help_origin,
        )
        return result
    result["help_button_state_after_click"] = confirmed_state.get("button_state", "unknown")
    if confirmed_state["status"] != "active" or confirmed_state.get("button_state") != "speedup":
        _pause_uncertain_help(queue, task_id)
        result.update(
            status="UNKNOWN_AFTER_HELP_CLICK",
            blockers=["speedup_button_not_confirmed_after_help_do_not_retry"],
            queue_modified=True,
        )
        record_live_checkpoint(
            "help_postcondition", profile_id=queue.get("profile_id"), decision="blocked",
            action="click_help", observation={"training_status": confirmed_state["status"],
            "button_state": confirmed_state.get("button_state")}, reason="speedup_not_confirmed",
            frame=confirmed_frame, monitor_origin=confirmed_origin,
        )
        return result
    confirm_help_action(
        queue, task_id,
        help_requested_at,
        training_status="active", button_state="speedup",
    )
    advance_training_lifecycle(
        queue, task_id, help_requested_at + timedelta(seconds=settle_delay),
        training_status="active", button_state="speedup", dry_run=False,
    )
    result.update(
        status="START_CONFIRMED",
        help_action="confirmed",
        queue_modified=True,
        actions_executed=True,
        initial_remaining_seconds=time_reading.value,
        initial_time_reading=asdict(time_reading),
        blockers=[],
    )
    record_live_checkpoint(
        "help_postcondition", profile_id=queue.get("profile_id"), decision="confirmed",
        action="click_help", observation={"training_status": confirmed_state["status"],
        "button_state": confirmed_state.get("button_state"), "task_status": task.get("status")},
        verification="speedup_button_confirmed", frame=confirmed_frame, monitor_origin=confirmed_origin,
    )
    return result
