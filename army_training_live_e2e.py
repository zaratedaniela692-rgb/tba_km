#!/usr/bin/env python3
"""One-shot, explicitly opted-in live army-training E2E for the second visible slot."""

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
import pytesseract

from army_training_levels import read_slot_selector_levels
from army_training_scanner import ArmyTrainingScannerError, _load_regions, read_army_training_snapshot_from_image
from army_training_slot_reader import read_slot_readings
from army_training_slots import STATUS_OK, locate_slots, slot_crop
from army_training_plan import TARGET_COMPLETION_PERCENT, TARGET_QUEUE_LIMIT_MULTIPLIER
from tools.resource_ocr import ResourceReadError, read_resource_region
from ui_variants import UIVariantError, resolve_variant

ROOT_DIR = Path(__file__).resolve().parent
SCREEN = "army_training"
WORLD_MAP_FRAME_OFFSET_Y = 39
MIN_CONFIDENCE = 70
EXPECTED_SIZE = (1920, 1080)
CONFIRMATION_PHRASE = "TRAIN SECOND SLOT MAX-1"
STOP_FILE = Path.home() / ".tba_stop"


class LiveTrainingError(ValueError):
    """Live E2E stopped at a failed safety gate."""

    def __init__(self, message, actions_executed=False, train_click_issued=False):
        super().__init__(message)
        self.actions_executed = actions_executed
        self.train_click_issued = train_click_issued


def _check_emergency_stop():
    if STOP_FILE.exists():
        raise LiveTrainingError(f"Emergency stop file exists: {STOP_FILE}")


def capture_primary_monitor():
    try:
        import mss
    except ImportError as error:
        raise LiveTrainingError("Live capture requires the 'mss' package.") from error
    with mss.mss() as capture:
        monitor = capture.monitors[1]
        frame = np.asarray(capture.grab(monitor))
    image = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    origin = (int(monitor["left"]), int(monitor["top"]))
    return image, origin


def _resource_readings(image, regions):
    result = {}
    for name in ("food", "silver"):
        region = dict(regions[f"{name}_count"])
        region["y"] = int(region["y"]) + WORLD_MAP_FRAME_OFFSET_Y
        result[name] = read_resource_region(image, region, min_confidence=MIN_CONFIDENCE)
    return result


def _slot_position_is_same(frame, variant, expected_slot):
    regions = _load_regions(variant["regions"]).get(SCREEN, {})
    layout = locate_slots(frame, regions, variant)
    if layout.status != STATUS_OK or len(layout.slots) < 2:
        return False, None
    slot = layout.slots[1]
    same = abs(slot.dx - expected_slot.dx) <= 2 and abs(slot.dy - expected_slot.dy) <= 3
    return same, slot if same else None


def _select_max_minus_one(frame, variant, slot):
    level = read_slot_selector_levels(frame, slot)
    if level.status != "candidate" or level.one_below_visible_level is None:
        raise LiveTrainingError("The slot's adjacent max-1 selector level is not confidently visible.")
    centers = level.badge_centers
    if len(centers) < 2:
        raise LiveTrainingError("The slot does not show both the maximum and max-1 selector badges.")
    lower_badge = centers[-2]
    selector = slot_crop(frame, slot, "unit_troop_level")
    selected_region = slot.regions["unit_troop_level"]
    return {
        "level": level.one_below_visible_level,
        "local_x": int(lower_badge[0]),
        "local_y": int(lower_badge[1]),
        "screen_x": int(selected_region["x"]) + int(lower_badge[0]),
        "screen_y": int(selected_region["y"]) + int(lower_badge[1]),
        "badge_count": len(centers),
        "selector_shape": selector.shape[:2],
    }


def _read_current_training_state(frame, variant):
    return read_army_training_snapshot_from_image(frame, variant=variant)


def _reading_is_reliable(reading):
    return (
        reading.value is not None
        and reading.confidence is not None
        and MIN_CONFIDENCE <= reading.confidence <= 100
    )


def _build_selected_slot_plan(frame, variant, slot):
    readings = read_slot_readings(frame, slot)
    resources = _resource_readings(frame, _load_regions(variant["regions"])["world_map"])
    training = _read_current_training_state(frame, variant)
    blockers = []
    if training["status"] != "idle":
        blockers.append("training_state_not_idle")
    if not all(_reading_is_reliable(reading) for reading in (readings.queue_limit, readings.city_count, readings.silver_cost)):
        blockers.append("slot_reading_uncertain")
    if any(not value["confidence_ok"] or value["value"] is None for value in resources.values()):
        blockers.append("resource_reading_uncertain")
    if resources["food"]["color"] != "white" or resources["food"]["value"] is None or resources["food"]["value"] <= 0:
        blockers.append("food_not_positive_white")
    if readings.queue_limit.value is None or readings.city_count.value is None:
        target_count = completion_count = order_count = None
    else:
        target_count = readings.queue_limit.value * TARGET_QUEUE_LIMIT_MULTIPLIER
        completion_count = (target_count * TARGET_COMPLETION_PERCENT + 99) // 100
        order_count = min(max(0, target_count - readings.city_count.value), readings.queue_limit.value)
        if readings.city_count.value >= completion_count:
            blockers.append("stock_goal_already_satisfied")
        if order_count <= 0:
            blockers.append("no_training_quantity_needed")
    if (
        readings.silver_cost.value is None
        or resources["silver"]["value"] is None
        or resources["silver"]["value"] < readings.silver_cost.value
    ):
        blockers.append("silver_insufficient_or_uncertain")
    if readings.queue_limit.value is not None and order_count is not None and order_count != readings.queue_limit.value:
        blockers.append("planned_quantity_is_not_full_queue")
    return {
        "training": training,
        "readings": asdict(readings),
        "resources": resources,
        "target_count": target_count,
        "completion_count": completion_count,
        "planned_quantity": order_count,
        "blockers": blockers,
    }


def _click_screen_point(point, origin):
    try:
        import pyautogui
    except ImportError as error:
        raise LiveTrainingError("Live execution requires the 'pyautogui' package.") from error
    pyautogui.click(origin[0] + point[0], origin[1] + point[1])


def _enable_live_failsafe(click_fn):
    if click_fn is not _click_screen_point:
        return
    try:
        import pyautogui
    except ImportError as error:
        raise LiveTrainingError("Live execution requires the 'pyautogui' package.") from error
    pyautogui.FAILSAFE = True


def run_one_shot(capture_fn=None, click_fn=None, execute=False, confirmation="", sleep_fn=time.sleep):
    """Prepare or execute one second-visible-slot max-1 training attempt."""
    capture_fn = capture_fn or capture_primary_monitor
    click_fn = click_fn or _click_screen_point
    if execute and confirmation != CONFIRMATION_PHRASE:
        raise LiveTrainingError(f"Live execution requires confirmation phrase: {CONFIRMATION_PHRASE}")
    variant = resolve_variant()
    regions = _load_regions(variant["regions"])
    frame, origin = capture_fn()
    if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
        raise LiveTrainingError(f"Expected primary-monitor frame {EXPECTED_SIZE}, got {(frame.shape[1], frame.shape[0])}.")
    layout = locate_slots(frame, regions.get(SCREEN, {}), variant)
    if layout.status != STATUS_OK or len(layout.slots) < 2:
        raise LiveTrainingError("Could not confidently detect at least two visible training slots.")
    second_slot = layout.slots[1]
    before_state = _read_current_training_state(frame, variant)
    if before_state["status"] != "idle":
        raise LiveTrainingError(f"Training is not confirmed idle ({before_state['status']}); no selector or Train click performed.")

    selection = _select_max_minus_one(frame, variant, second_slot)
    result = {
        "mode": "live_one_shot",
        "actions_executed": False,
        "queue_modified": False,
        "slot_frame_index": second_slot.index,
        "slot_row": second_slot.row,
        "slot_column": second_slot.column,
        "presumed_highest_level": read_slot_selector_levels(frame, second_slot).highest_visible_level,
        "requested_level": selection["level"],
        "selection_confirmed": False,
        "selection": selection,
        "status": "PREVIEW_ONLY",
        "blockers": ["dry_run_no_game_actions"],
    }
    if not execute:
        return result

    _check_emergency_stop()
    _enable_live_failsafe(click_fn)
    result["actions_executed"] = True
    result["level_click_attempted"] = True
    try:
        click_fn((selection["screen_x"], selection["screen_y"]), origin)
        result["level_click_issued"] = True
    except Exception as error:
        result["status"] = "UNKNOWN_AFTER_LEVEL_CLICK_ATTEMPT"
        result["blockers"] = [f"level_click_result_uncertain:{error}"]
        return result

    try:
        sleep_fn(0.25)
        selected_frame, selected_origin = capture_fn()
        if selected_origin != origin or (selected_frame.shape[1], selected_frame.shape[0]) != EXPECTED_SIZE:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["capture_geometry_changed_after_level_selection"]
            return result
        same_slot, current_slot = _slot_position_is_same(selected_frame, variant, second_slot)
        if not same_slot:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["same_slot_not_confirmed_after_level_click"]
            return result

        read_frame, read_origin = capture_fn()
        if read_origin != origin or (read_frame.shape[1], read_frame.shape[0]) != EXPECTED_SIZE:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["capture_geometry_changed_before_slot_read"]
            return result
        same_slot, read_slot = _slot_position_is_same(read_frame, variant, second_slot)
        if not same_slot:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["same_slot_not_confirmed_before_slot_read"]
            return result
        plan = _build_selected_slot_plan(read_frame, variant, read_slot)
        result["preflight"] = plan
        if plan["blockers"]:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = plan["blockers"]
            return result

        fresh_frame, fresh_origin = capture_fn()
        if fresh_origin != origin or (fresh_frame.shape[1], fresh_frame.shape[0]) != EXPECTED_SIZE:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["capture_geometry_changed_before_train"]
            return result
        same_slot, final_slot = _slot_position_is_same(fresh_frame, variant, second_slot)
        if not same_slot:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["same_slot_not_confirmed_before_train"]
            return result
        final_state = _read_current_training_state(fresh_frame, variant)
        if final_state["status"] != "idle":
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = [f"training_changed_before_train_{final_state['status']}"]
            return result
        final_plan = _build_selected_slot_plan(fresh_frame, variant, final_slot)
        result["preflight"] = final_plan
        if final_plan["blockers"]:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = final_plan["blockers"]
            return result

        _check_emergency_stop()
    except Exception as error:
        result["status"] = "UNKNOWN_AFTER_LEVEL_CLICK"
        result["blockers"] = [f"post_selection_check_failed_stop_without_retry:{error}"]
        return result
    train_region = final_slot.regions["unit_troop_train_button"]
    train_point = (train_region["x"] + train_region["w"] // 2, train_region["y"] + train_region["h"] // 2)
    result["train_click_attempted"] = True
    result["queue_modified"] = "unknown"
    result["status"] = "SUBMITTED_UNCONFIRMED"
    try:
        click_fn(train_point, fresh_origin)
        result["train_click_issued"] = True
    except Exception as error:
        result["actions_executed"] = True
        result["status"] = "UNKNOWN_AFTER_TRAIN_CLICK_ATTEMPT"
        result["blockers"] = [f"train_click_result_uncertain_do_not_retry:{error}"]
        return result
    result["actions_executed"] = True
    sleep_fn(0.5)
    try:
        after_frame, after_origin = capture_fn()
    except Exception as error:
        result["status"] = "UNKNOWN_AFTER_CLICK"
        result["blockers"] = [f"post_click_capture_failed_do_not_retry:{error}"]
        return result
    if after_origin != origin or (after_frame.shape[1], after_frame.shape[0]) != EXPECTED_SIZE:
        result["status"] = "UNKNOWN_AFTER_CLICK"
        result["blockers"] = ["post_click_capture_geometry_changed"]
        return result
    after_state = _read_current_training_state(after_frame, variant)
    result["post_click_training_state"] = after_state["status"]
    if after_state["status"] == "active":
        result["status"] = "START_CONFIRMED"
        result["queue_modified"] = True
        result["blockers"] = []
    else:
        result["status"] = "UNKNOWN_AFTER_CLICK"
        result["blockers"] = ["train_click_not_visually_confirmed_do_not_retry"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-shot E2E for the second visible slot, max-1 level.")
    parser.add_argument("--execute", action="store_true", help="allow live selector and at most one Train click")
    parser.add_argument("--confirm", default="", help=f"type exactly: {CONFIRMATION_PHRASE}")
    args = parser.parse_args(argv)
    try:
        result = run_one_shot(execute=args.execute, confirmation=args.confirm)
    except (LiveTrainingError, ArmyTrainingScannerError, ResourceReadError, UIVariantError, OSError, ValueError, pytesseract.TesseractNotFoundError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error), "actions_executed": False, "queue_modified": False}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
