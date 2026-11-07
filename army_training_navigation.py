"""Live navigation from the default world map to the Barracks screen."""

import json
import time
from pathlib import Path

import cv2

from army_training_slots import STATUS_OK, locate_slots
from game_screen import GameScreenError, clear_game_screen
from ui_variants import resolve_asset_path, resolve_variant

ROOT_DIR = Path(__file__).resolve().parent
EXPECTED_SIZE = (1920, 1080)
WORLD_MAP_FRAME_OFFSET_Y = 39
ARMY_BUTTON_SEARCH_MARGIN = 2
TRANSITION_WAIT_SECONDS = 1.0


def _read_regions(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot load screen regions: {error}") from error


def _army_search_region(frame, region):
    x = int(region["x"])
    y = int(region["y"]) + WORLD_MAP_FRAME_OFFSET_Y
    width = int(region["w"])
    height = int(region["h"])
    frame_height, frame_width = frame.shape[:2]
    if x < 0 or y < 0 or x + width > frame_width or y + height > frame_height:
        return None

    margin = ARMY_BUTTON_SEARCH_MARGIN
    search_x = max(0, x - margin)
    search_y = max(0, y - margin)
    search_right = min(frame_width, x + width + margin)
    search_bottom = min(frame_height, y + height + margin)
    return {
        "x": search_x,
        "y": search_y,
        "w": search_right - search_x,
        "h": search_bottom - search_y,
    }


def _match_army_button(frame, region, template, threshold):
    search_region = _army_search_region(frame, region)
    if search_region is None:
        return None

    x = search_region["x"]
    y = search_region["y"]
    search_area = frame[y:y + search_region["h"], x:x + search_region["w"]]
    template_height, template_width = template.shape[:2]
    if template_height > search_area.shape[0] or template_width > search_area.shape[1]:
        return None

    scores = cv2.matchTemplate(search_area, template, cv2.TM_SQDIFF_NORMED)
    error, _, location, _ = cv2.minMaxLoc(scores)
    confidence = max(0.0, min(100.0, (1.0 - float(error)) * 100.0))
    return (
        x + int(location[0]) + template_width // 2,
        y + int(location[1]) + template_height // 2,
        confidence,
        float(threshold),
        search_region,
    )


def _capture(capture_fn):
    frame, origin = capture_fn()
    if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
        raise ValueError(f"Expected primary-monitor frame {EXPECTED_SIZE}, got {(frame.shape[1], frame.shape[0])}.")
    return frame, origin


def open_army_training_screen(
    execute=False,
    capture_fn=None,
    press_key_fn=None,
    click_fn=None,
    sleep_fn=time.sleep,
    stop_file=None,
    variant=None,
):
    """Reset the game UI, open Armia, and confirm Barracks slots before task work."""
    plan = {
        "steps": ["press_escape_three_times", "click_army", "confirm_barracks_slots"],
        "actions_executed": False,
        "queue_modified": False,
    }
    if not execute:
        return {**plan, "status": "PREVIEW_ONLY"}

    from army_training_live_e2e import (
        _check_emergency_stop,
        _click_screen_point,
        _enable_live_failsafe,
        capture_primary_monitor,
    )
    from tools.verify import get_threshold

    capture_fn = capture_fn or capture_primary_monitor
    click_fn = click_fn or _click_screen_point
    variant = variant or resolve_variant()
    if variant["id"] != "legacy":  # the only ready UI variant is the current desktop client
        return {**plan, "status": "BLOCKED_UNSUPPORTED_VARIANT", "blockers": [variant["id"]]}

    try:
        reset = clear_game_screen(execute=True, press_key=press_key_fn, stop_file=stop_file or Path.home() / ".tba_stop")
    except GameScreenError as error:
        return {**plan, "status": "BLOCKED_SCREEN_RESET", "blockers": [str(error)]}

    result = {**plan, "actions_executed": reset["actions_executed"]}
    try:
        frame, origin = _capture(capture_fn)
        regions = _read_regions(variant["regions"])
        world_map = regions.get("world_map", {})
        army_region = world_map.get("armia")
        if not isinstance(army_region, dict):
            return {**result, "status": "BLOCKED_ARMY_BUTTON_REGION_MISSING", "blockers": ["world_map.armia"]}
        template_path = resolve_asset_path(variant, army_region["template"])
        template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
        if template is None:
            return {**result, "status": "BLOCKED_ARMY_BUTTON_TEMPLATE_MISSING", "blockers": [str(template_path)]}
        config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
        threshold = get_threshold(config, "world_map", "armia")
        search_region = _army_search_region(frame, army_region)
        match = _match_army_button(frame, army_region, template, threshold)
        if match is None:
            return {
                **result,
                "status": "BLOCKED_ARMY_BUTTON_OUTSIDE_FRAME",
                "armia_match_threshold": float(threshold),
                "search_region": search_region,
                "blockers": ["world_map.armia search region is outside the captured frame"],
            }
        match_x, match_y, match_confidence, match_threshold, search_region = match
        result.update(
            armia_match_confidence=match_confidence,
            armia_match_threshold=match_threshold,
            armia_match_candidate_point=(match_x, match_y),
            search_region=search_region,
        )
        if match_confidence < match_threshold:
            return {
                **result,
                "status": "BLOCKED_ARMY_BUTTON_UNCONFIRMED",
                "blockers": [
                    f"world_map.armia confidence {match_confidence:.2f}% is below {match_threshold:.2f}%"
                ],
            }
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return {**result, "status": "BLOCKED_BEFORE_ARMY_CLICK", "blockers": [str(error)]}

    try:
        _check_emergency_stop()
        _enable_live_failsafe(click_fn)
        click_fn((match_x, match_y), origin)
    except Exception as error:
        return {
            **result,
            "status": "UNKNOWN_AFTER_ARMY_CLICK_ATTEMPT",
            "actions_executed": True,
            "armia_match_confidence": match_confidence,
            "blockers": [f"armia_click_result_uncertain_no_retry:{error}"],
        }

    result.update(
        actions_executed=True,
        armia_match_confidence=match_confidence,
        armia_click_point=(match_x, match_y),
    )
    sleep_fn(TRANSITION_WAIT_SECONDS)
    try:
        frame, new_origin = _capture(capture_fn)
        if new_origin != origin:
            raise ValueError("Primary-monitor capture origin changed after opening Armia.")
        layout = locate_slots(frame, _read_regions(variant["regions"]).get("army_training", {}), variant)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return {**result, "status": "BLOCKED_AFTER_ARMY_CLICK", "blockers": [str(error)]}

    if layout.status != STATUS_OK or not layout.slots:
        return {
            **result,
            "status": "BLOCKED_BARRACKS_NOT_CONFIRMED",
            "layout_status": layout.status,
            "blockers": [layout.reason or "No training slots detected."],
        }

    result.update(status="BARRACKS_OPENED", layout_status=layout.status, visible_slots=len(layout.slots))
    return result