#!/usr/bin/env python3
"""One-shot, explicitly opted-in live army-training E2E for the first visible slot."""

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
import pytesseract

from army_training_inspector import read_selected_category
from army_training_levels import detect_selector_badges, read_slot_selector_levels
from army_training_navigation import ensure_army_training_screen
from army_training_scanner import (
    ArmyTrainingScannerError,
    _load_regions,
    read_army_training_snapshot_from_image,
)
from army_training_slot_reader import read_slot_readings
from army_training_slots import STATUS_OK, locate_slots, slot_crop
from army_training_plan import TARGET_COMPLETION_PERCENT, TARGET_QUEUE_LIMIT_MULTIPLIER
from client_router import observe_foreground_profile
from tools.resource_ocr import ResourceReadError, read_resource_region
from ui_variants import UIVariantError, resolve_variant

ROOT_DIR = Path(__file__).resolve().parent
SCREEN = "army_training"
WORLD_MAP_FRAME_OFFSET_Y = 39
MIN_CONFIDENCE = 70
EXPECTED_SIZE = (1920, 1080)
DEFAULT_LEVEL = 6
CONFIRMATION_PHRASE = "NAVIGATE IF NEEDED AND TRAIN FIRST SLOT LEVEL {level}"
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
    if layout.status != STATUS_OK or not layout.slots:
        return False, None
    slot = layout.slots[0]
    same = abs(slot.dx - expected_slot.dx) <= 2 and abs(slot.dy - expected_slot.dy) <= 3
    return same, slot if same else None


def _select_requested_level(frame, slot, requested_level):
    level = read_slot_selector_levels(frame, slot)
    if isinstance(requested_level, bool) or not isinstance(requested_level, int) or not 1 <= requested_level <= 9:
        raise LiveTrainingError("Requested level must be an integer from 1 through 9.")
    if level.status != "candidate" or level.lowest_visible_level is None or level.highest_visible_level is None:
        raise LiveTrainingError("The slot's visible selector range is not confidently consecutive.")
    if not level.lowest_visible_level <= requested_level <= level.highest_visible_level:
        raise LiveTrainingError("The requested level is not in the slot's confidently read visible range.")
    badge_index = requested_level - level.lowest_visible_level
    badge = level.badge_centers[badge_index]
    selector = slot_crop(frame, slot, "unit_troop_level")
    selected_region = slot.regions["unit_troop_level"]
    return {
        "level": requested_level,
        "badge_index": badge_index,
        "local_x": int(badge[0]),
        "local_y": int(badge[1]),
        "screen_x": int(selected_region["x"]) + int(badge[0]),
        "screen_y": int(selected_region["y"]) + int(badge[1]),
        "badge_count": len(level.badge_centers),
        "lowest_visible_level": level.lowest_visible_level,
        "highest_visible_level": level.highest_visible_level,
        "selector_shape": selector.shape[:2],
    }


def _requested_level_is_selected(frame, slot, selection):
    selector = slot_crop(frame, slot, "unit_troop_level")
    badges = detect_selector_badges(selector)
    expected_index = selection["badge_index"]
    if len(badges) != selection["badge_count"] or expected_index >= len(badges):
        return False
    selected_index = max(range(len(badges)), key=lambda index: badges[index][2])
    other_radii = [badge[2] for index, badge in enumerate(badges) if index != selected_index]
    if other_radii and badges[selected_index][2] - max(other_radii) < 0.5:
        return False
    expected = (selection["local_x"], selection["local_y"])
    actual = badges[selected_index][:2]
    return selected_index == expected_index and max(abs(actual[axis] - expected[axis]) for axis in (0, 1)) <= 3


def _read_current_training_state(frame, variant, include_numeric=True):
    return read_army_training_snapshot_from_image(
        frame, variant=variant, include_numeric=include_numeric,
    )


def _reading_is_reliable(reading):
    return (
        reading.value is not None
        and reading.confidence is not None
        and MIN_CONFIDENCE <= reading.confidence <= 100
    )


def _build_selected_slot_plan(
    frame, variant, slot, requested_quantity=None, goal_queue_limit=None, check_silver=True,
):
    readings = read_slot_readings(frame, slot)
    resources = _resource_readings(frame, _load_regions(variant["regions"])["world_map"])
    training = _read_current_training_state(frame, variant)
    queue_limit = goal_queue_limit if goal_queue_limit is not None else readings.queue_limit.value
    blockers = []
    if training["status"] != "idle":
        blockers.append("training_state_not_idle")
    if not all(_reading_is_reliable(reading) for reading in (readings.queue_limit, readings.city_count, readings.silver_cost)):
        blockers.append("slot_reading_uncertain")
    if any(not value["confidence_ok"] or value["value"] is None for value in resources.values()):
        blockers.append("resource_reading_uncertain")
    if resources["food"]["color"] != "white" or resources["food"]["value"] is None or resources["food"]["value"] <= 0:
        blockers.append("food_not_positive_white")
    if queue_limit is None or readings.city_count.value is None:
        target_count = completion_count = order_count = None
    else:
        target_count = queue_limit * TARGET_QUEUE_LIMIT_MULTIPLIER
        completion_count = (target_count * TARGET_COMPLETION_PERCENT + 99) // 100
        order_count = min(max(0, target_count - readings.city_count.value), queue_limit)
        if readings.city_count.value >= completion_count:
            blockers.append("stock_goal_already_satisfied")
        if order_count <= 0:
            blockers.append("no_training_quantity_needed")
    if requested_quantity is not None:
        if isinstance(requested_quantity, bool) or not isinstance(requested_quantity, int) or requested_quantity <= 0:
            blockers.append("requested_quantity_must_be_positive_integer")
        elif queue_limit is not None and requested_quantity > queue_limit:
            blockers.append("requested_quantity_exceeds_queue_limit")
        else:
            order_count = requested_quantity
    if check_silver and (
        readings.silver_cost.value is None
        or resources["silver"]["value"] is None
        or resources["silver"]["value"] < readings.silver_cost.value
    ):
        blockers.append("silver_insufficient_or_uncertain")
    if requested_quantity is None and readings.queue_limit.value is not None and order_count is not None and order_count != readings.queue_limit.value:
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


def run_one_shot(
    capture_fn=None, click_fn=None, execute=False, confirmation="", level=DEFAULT_LEVEL,
    sleep_fn=time.sleep, ensure_screen_fn=None, route_fn=None,
):
    """Prepare or execute one training attempt for an explicit level in the first visible slot."""
    capture_fn = capture_fn or capture_primary_monitor
    click_fn = click_fn or _click_screen_point
    if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 9:
        raise LiveTrainingError("Requested level must be an integer from 1 through 9.")
    required_confirmation = CONFIRMATION_PHRASE.format(level=level)
    if execute and confirmation != required_confirmation:
        raise LiveTrainingError(f"Live execution requires confirmation phrase: {required_confirmation}")
    route = None
    if execute:
        route_fn = route_fn or observe_foreground_profile
        try:
            observation = route_fn(capture_fn=capture_fn, register_missing=False)
            route = observation if isinstance(observation, dict) else asdict(observation)
        except Exception as error:
            return {
                "mode": "live_one_shot",
                "status": "BLOCKED_ROUTE",
                "actions_executed": False,
                "queue_modified": False,
                "blockers": [f"foreground_route_failed:{type(error).__name__}:{error}"],
            }
        profile_id = route.get("profile_id")
        if (
            route.get("status") != "routed"
            or route.get("client_id") != "desktop"
            or not isinstance(profile_id, str)
            or not profile_id.strip()
        ):
            return {
                "mode": "live_one_shot",
                "status": "BLOCKED_ROUTE",
                "actions_executed": False,
                "queue_modified": False,
                "route": route,
                "blockers": ["foreground_route_must_resolve_one_desktop_profile"],
            }
    variant = resolve_variant()
    ensure_screen_fn = ensure_screen_fn or ensure_army_training_screen
    screen = ensure_screen_fn(
        execute=execute,
        capture_fn=capture_fn,
        click_fn=click_fn,
        sleep_fn=sleep_fn,
        variant=variant,
    )
    if screen.get("status") != "BARRACKS_READY":
        return {
            "mode": "live_one_shot",
            "status": screen.get("status", "BLOCKED_BARRACKS"),
            "actions_executed": bool(screen.get("actions_executed", False)),
            "queue_modified": False,
            "route": route,
            "navigation": screen.get("navigation"),
            "blockers": [screen.get("layout_reason") or screen.get("reason") or screen.get("status", "barracks_not_ready")],
        }
    frame, origin, layout = screen["frame"], screen["origin"], screen["layout"]
    category = read_selected_category(frame, variant)
    if category.get("status") != "confirmed" or category.get("unit_type") != "guardsmen":
        return {
            "mode": "live_one_shot",
            "status": "BLOCKED_CATEGORY_RECOGNITION",
            "actions_executed": bool(screen.get("actions_executed", False)),
            "queue_modified": False,
            "route": route,
            "navigation": screen.get("navigation"),
            "blockers": ["The highlighted Barracks category is not confidently confirmed as Guardsmen."],
        }
    first_slot = layout.slots[0]
    before_state = _read_current_training_state(frame, variant)
    if before_state["status"] != "idle":
        return {
            "mode": "live_one_shot",
            "status": "BLOCKED_TRAINING_NOT_IDLE",
            "actions_executed": bool(screen.get("actions_executed", False)),
            "queue_modified": False,
            "route": route,
            "navigation": screen.get("navigation"),
            "blockers": [f"Training is not confirmed idle ({before_state['status']})."],
        }

    try:
        selection = _select_requested_level(frame, first_slot, level)
    except LiveTrainingError as error:
        return {
            "mode": "live_one_shot",
            "status": "BLOCKED_LEVEL_NOT_RESOLVED",
            "actions_executed": bool(screen.get("actions_executed", False)),
            "queue_modified": False,
            "route": route,
            "navigation": screen.get("navigation"),
            "blockers": [str(error)],
        }
    result = {
        "mode": "live_one_shot",
        "actions_executed": bool(screen.get("actions_executed", False)),
        "queue_modified": False,
        "route": route,
        "navigation": screen.get("navigation"),
        "slot_frame_index": first_slot.index,
        "slot_row": first_slot.row,
        "slot_column": first_slot.column,
        "unit_type": category["unit_type"],
        "presumed_highest_level": selection["highest_visible_level"],
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
        same_slot, current_slot = _slot_position_is_same(selected_frame, variant, first_slot)
        if not same_slot:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["same_slot_not_confirmed_after_level_click"]
            return result
        current_category = read_selected_category(selected_frame, variant)
        if current_category.get("status") != "confirmed" or current_category.get("unit_type") != "guardsmen":
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["guardsmen_category_not_confirmed_after_level_click"]
            return result
        if not _requested_level_is_selected(selected_frame, current_slot, selection):
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["requested_level_not_visually_confirmed"]
            return result
        result["selection_confirmed"] = True

        read_frame, read_origin = capture_fn()
        if read_origin != origin or (read_frame.shape[1], read_frame.shape[0]) != EXPECTED_SIZE:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["capture_geometry_changed_before_slot_read"]
            return result
        same_slot, read_slot = _slot_position_is_same(read_frame, variant, first_slot)
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
        same_slot, final_slot = _slot_position_is_same(fresh_frame, variant, first_slot)
        if not same_slot:
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["same_slot_not_confirmed_before_train"]
            return result
        if not _requested_level_is_selected(fresh_frame, final_slot, selection):
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["requested_level_not_visually_confirmed_before_train"]
            return result
        final_state = _read_current_training_state(fresh_frame, variant)
        if final_state["status"] != "idle":
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = [f"training_changed_before_train_{final_state['status']}"]
            return result
        final_category = read_selected_category(fresh_frame, variant)
        if final_category.get("status") != "confirmed" or final_category.get("unit_type") != "guardsmen":
            result["status"] = "BLOCKED_AFTER_LEVEL_CLICK"
            result["blockers"] = ["guardsmen_category_not_confirmed_before_train"]
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
    parser = argparse.ArgumentParser(description="One-shot E2E for an explicit level in the first visible slot.")
    parser.add_argument("--level", type=int, required=True, help="visible Guardsmen level to select (1-9)")
    parser.add_argument("--execute", action="store_true", help="allow live selector and at most one Train click")
    parser.add_argument("--confirm", default="", help="type the exact phrase authorizing navigation if needed and one training attempt")
    args = parser.parse_args(argv)
    try:
        result = run_one_shot(execute=args.execute, confirmation=args.confirm, level=args.level)
    except (LiveTrainingError, ArmyTrainingScannerError, ResourceReadError, UIVariantError, OSError, ValueError, pytesseract.TesseractNotFoundError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error), "actions_executed": False, "queue_modified": False}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
