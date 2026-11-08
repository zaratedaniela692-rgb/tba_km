"""Barracks category selection: read the highlighted list entry and click the target at most once."""

import time

import cv2

from army_unit_types import CATEGORY_PROFILES, SUPPORTED_TRAINING_UNIT_TYPES, validate_unit_type
from ui_variants import resolve_asset_path, resolve_variant
from workflow_trace import WorkflowTrace

LIST_REGION = "troops_types"
SELECTED_THRESHOLD = 0.95
POSITION_TOLERANCE = 3
SETTLE_SECONDS = 0.6
CONFIRMATION_PHRASE = "SELECT ARMY CATEGORY"
CONFIRMED_STATUSES = frozenset({"CATEGORY_CONFIRMED", "CATEGORY_SELECTED"})


def read_selected_category(frame, regions, variant):
    """Highlighted category among the supported ones; unit_type is None unless exactly one matches in place."""
    listing = regions.get(LIST_REGION)
    if listing is None:
        return {"unit_type": None, "reason": "list_region_missing", "scores": {}}
    left, top, width, height = (int(listing[key]) for key in ("x", "y", "w", "h"))
    crop = frame[top:top + height, left:left + width]
    scores, matched = {}, []
    for unit_type in SUPPORTED_TRAINING_UNIT_TYPES:
        region = regions.get(CATEGORY_PROFILES[unit_type].selected_region or "")
        if region is None or "template" not in region:
            continue
        template = cv2.imread(str(resolve_asset_path(variant, region["template"])), cv2.IMREAD_COLOR)
        if template is None or template.shape[0] > crop.shape[0] or template.shape[1] > crop.shape[1]:
            continue
        _, score, _, (found_x, found_y) = cv2.minMaxLoc(cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED))
        scores[unit_type] = round(float(score), 3)
        in_place = (
            abs(found_x - (int(region["x"]) - left)) <= POSITION_TOLERANCE
            and abs(found_y - (int(region["y"]) - top)) <= POSITION_TOLERANCE
        )
        if score >= SELECTED_THRESHOLD and in_place:
            matched.append(unit_type)
    if len(matched) == 1:
        return {"unit_type": matched[0], "reason": "highlight_matched", "scores": scores}
    return {"unit_type": None, "reason": "ambiguous" if matched else "no_known_category_highlighted", "scores": scores}


def select_army_type(
    unit_type, execute=False, capture_fn=None, click_fn=None, sleep_fn=time.sleep, stop_fn=None, variant=None,
):
    """Make `unit_type` the highlighted Barracks category; without `execute` nothing is sent to the game."""
    trace = WorkflowTrace("army_training_category")

    def finish(result):
        result["event_trace"] = trace.events
        return result

    result = {"unit_type": unit_type, "actions_executed": False, "selection_confirmed": False}
    try:
        validate_unit_type(unit_type)
    except ValueError:
        trace.record("validate_target", target=unit_type, decision="block", reason="unknown_unit_type")
        return finish({**result, "status": "BLOCKED_UNKNOWN_UNIT_TYPE"})
    if unit_type not in SUPPORTED_TRAINING_UNIT_TYPES:
        trace.record("validate_target", target=unit_type, decision="block", reason="selection_not_implemented")
        return finish({**result, "status": "BLOCKED_CATEGORY_SELECTION_UNIMPLEMENTED"})

    from army_training_live_e2e import (
        EXPECTED_SIZE,
        _check_emergency_stop,
        _click_screen_point,
        _enable_live_failsafe,
        capture_primary_monitor,
    )
    from army_training_scanner import _load_regions
    from army_training_slots import STATUS_OK, locate_slots

    capture_fn = capture_fn or capture_primary_monitor
    click_fn = click_fn or _click_screen_point
    stop_fn = stop_fn or _check_emergency_stop
    variant = variant or resolve_variant()
    regions = _load_regions(variant["regions"]).get("army_training", {})
    target = regions.get(CATEGORY_PROFILES[unit_type].selected_region or "")
    if target is None or LIST_REGION not in regions:
        trace.record(
            "load_regions", target=unit_type, observation={"target_region_found": target is not None,
            "list_region_found": LIST_REGION in regions}, decision="block", reason="category_region_missing",
        )
        return finish({**result, "status": "BLOCKED_CATEGORY_REGION_MISSING"})

    frame, origin = capture_fn()
    if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
        trace.record("capture_barracks", observation={"frame_size": (frame.shape[1], frame.shape[0]),
                     "expected_size": EXPECTED_SIZE}, decision="block", reason="unsupported_frame_size")
        return finish({**result, "status": "BLOCKED_UNSUPPORTED_FRAME_SIZE"})
    layout = locate_slots(frame, regions, variant)
    if layout.status != STATUS_OK:
        trace.record("confirm_barracks", observation={"layout_status": layout.status,
                     "layout_reason": layout.reason}, decision="block", reason="barracks_not_confirmed")
        return finish({**result, "status": "BLOCKED_BARRACKS_NOT_CONFIRMED"})
    current = read_selected_category(frame, regions, variant)
    result.update(current_category=current["unit_type"], scores=current["scores"])
    trace.record("read_selected_category", target=unit_type, observation=current)
    if current["unit_type"] == unit_type:
        trace.record("category_decision", target=unit_type, decision="already_selected", verification="confirmed")
        return finish({**result, "status": "CATEGORY_CONFIRMED", "selection_confirmed": True})
    if not execute:
        trace.record("category_decision", target=unit_type, decision="would_select", reason="preview_only")
        return finish({**result, "status": "CATEGORY_WOULD_SELECT"})

    try:
        stop_fn()
    except Exception as error:
        trace.record("emergency_stop_check", decision="block", reason=str(error))
        return finish({**result, "status": "BLOCKED_EMERGENCY_STOP", "reason": str(error)})
    _enable_live_failsafe(click_fn)
    point = (int(target["x"]) + int(target["w"]) // 2, int(target["y"]) + int(target["h"]) // 2)
    result["actions_executed"] = True
    trace.record("category_click", target=unit_type, action={"point": point, "origin": origin}, decision="click")
    try:
        click_fn(point, origin)
    except Exception as error:
        trace.record("category_click_result", action="click", verification="unknown", reason=str(error))
        return finish({**result, "status": "BLOCKED_CATEGORY_CLICK_FAILED", "reason": str(error)})
    sleep_fn(SETTLE_SECONDS)
    try:
        after, after_origin = capture_fn()
        if (after.shape[1], after.shape[0]) != EXPECTED_SIZE or tuple(after_origin) != tuple(origin):
            trace.record("verify_category", observation={"frame_size": (after.shape[1], after.shape[0]),
                         "origin": after_origin}, decision="block", verification="failed",
                         reason="capture_geometry_changed")
            return finish({**result, "status": "BLOCKED_CATEGORY_NOT_CONFIRMED", "reason": "capture_geometry_changed"})
        confirmed = read_selected_category(after, regions, variant)
    except Exception as error:
        trace.record("verify_category", decision="block", verification="unknown", reason=str(error))
        return finish({**result, "status": "BLOCKED_CATEGORY_NOT_CONFIRMED", "reason": str(error)})
    result["scores_after_click"] = confirmed["scores"]
    if confirmed["unit_type"] != unit_type:
        trace.record("verify_category", target=unit_type, observation=confirmed, decision="block",
                     verification="failed", reason="highlight_not_on_target")
        return finish({**result, "status": "BLOCKED_CATEGORY_NOT_CONFIRMED", "reason": "highlight_not_on_target"})
    trace.record("verify_category", target=unit_type, observation=confirmed, decision="continue",
                 verification="confirmed")
    return finish({**result, "status": "CATEGORY_SELECTED", "selection_confirmed": True})


def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Select a Barracks category; preview by default.")
    parser.add_argument("--unit-type", required=True, choices=sorted(SUPPORTED_TRAINING_UNIT_TYPES))
    parser.add_argument("--execute", action="store_true", help="click the category entry")
    parser.add_argument("--confirm", default="", help=f"type exactly: {CONFIRMATION_PHRASE}")
    args = parser.parse_args(argv)
    if args.execute and args.confirm != CONFIRMATION_PHRASE:
        parser.error(f"live selection requires --confirm \"{CONFIRMATION_PHRASE}\"")
    result = select_army_type(args.unit_type, execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = result["status"] in CONFIRMED_STATUSES or (not args.execute and result["status"] == "CATEGORY_WOULD_SELECT")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
