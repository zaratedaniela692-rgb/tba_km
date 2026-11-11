#!/usr/bin/env python3
"""Read-only Barracks category and visible-slot inspector."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import cv2

from army_training_levels import read_slot_selector_levels
from army_training_scanner import ArmyTrainingScannerError, _load_regions, _read_image
from army_training_slot_reader import read_slot_readings
from army_training_slots import STATUS_OK, locate_slots
from ui_variants import UIVariantError, resolve_asset_path, resolve_variant

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_FIXTURE = ROOT_DIR / "screenshots" / "army_training" / "specialist_view.png"
SCREEN = "army_training"
CATEGORY_REGION = "troops_types"
CATEGORY_TEMPLATES = {
    "guardsmen": "templates/army_training/troops_type_guardsmen_selected.png",
    "specialists": "templates/army_training/troops_type_specialists_selected.png",
}
CATEGORY_MATCH_THRESHOLD = 0.95
EXPECTED_SIZE = (1920, 1080)


def read_selected_category(image, variant=None):
    """Recognize one selected category from its annotated list region."""
    variant = variant or resolve_variant()
    if variant["id"] not in {"desktop", "legacy"}:
        return {"status": "unsupported", "reason": "category_inspection_requires_desktop_assets"}
    regions = _load_regions(variant["regions"]).get(SCREEN, {})
    region = regions.get(CATEGORY_REGION)
    if not isinstance(region, dict):
        raise ArmyTrainingScannerError("Missing annotated Barracks category-list region.")
    x, y, width, height = (int(region[key]) for key in ("x", "y", "w", "h"))
    if x < 0 or y < 0 or x + width > image.shape[1] or y + height > image.shape[0]:
        raise ArmyTrainingScannerError("Barracks category-list region is outside the frame.")
    category_list = image[y:y + height, x:x + width]
    matches = []
    scores = {}
    for unit_type, template_name in CATEGORY_TEMPLATES.items():
        template_path = resolve_asset_path(variant, template_name)
        template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
        if template is None:
            raise ArmyTrainingScannerError(f"Cannot read category template: {template_path}")
        if template.shape[0] > category_list.shape[0] or template.shape[1] > category_list.shape[1]:
            raise ArmyTrainingScannerError(f"Category template is larger than its region: {unit_type}")
        result = cv2.matchTemplate(category_list, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        scores[unit_type] = float(score)
        if score >= CATEGORY_MATCH_THRESHOLD:
            matches.append({
                "unit_type": unit_type,
                "score": float(score),
                "location": [x + int(location[0]), y + int(location[1])],
            })
    if len(matches) != 1:
        return {
            "status": "unknown" if not matches else "ambiguous",
            "reason": "selected_category_not_uniquely_matched",
            "scores": scores,
            "matches": matches,
        }
    return {"status": "confirmed", **matches[0], "scores": scores}


def _read_slot_report(image, slot):
    try:
        levels = asdict(read_slot_selector_levels(image, slot))
    except ArmyTrainingScannerError as error:
        levels = {"status": "unknown", "reason": f"level_read_failed:{error}"}
    try:
        readings = asdict(read_slot_readings(image, slot))
    except ArmyTrainingScannerError as error:
        readings = {"status": "unknown", "reason": f"numeric_read_failed:{error}"}
    return {
        "frame_index": slot.index,
        "row": slot.row,
        "column": slot.column,
        "anchor_score": slot.anchor_score,
        "check_score": slot.check_score,
        "selector_levels": levels,
        "readings": readings,
    }


def inspect_image(image, expected_unit_type=None, variant=None):
    """Inspect the highlighted category and visible slots without sending input."""
    variant = variant or resolve_variant()
    if (image.shape[1], image.shape[0]) != EXPECTED_SIZE:
        return {
            "status": "BLOCKED_FRAME_SIZE",
            "reason": f"expected_{EXPECTED_SIZE[0]}x{EXPECTED_SIZE[1]}",
            "frame_size": [int(image.shape[1]), int(image.shape[0])],
            "actions_executed": False,
        }
    category = read_selected_category(image, variant)
    base = {
        "mode": "read_only_army_category_inspection",
        "actions_executed": False,
        "queue_modified": False,
        "category": category,
    }
    if category["status"] != "confirmed":
        return {**base, "status": "BLOCKED_CATEGORY_RECOGNITION"}
    if expected_unit_type is not None and category["unit_type"] != expected_unit_type:
        return {
            **base,
            "status": "BLOCKED_UNIT_TYPE_MISMATCH",
            "expected_unit_type": expected_unit_type,
        }
    regions = _load_regions(variant["regions"]).get(SCREEN, {})
    layout = locate_slots(image, regions, variant)
    if layout.status != STATUS_OK:
        return {
            **base,
            "status": "BLOCKED_SLOT_LAYOUT",
            "layout_status": layout.status,
            "layout_reason": layout.reason,
        }
    return {
        **base,
        "status": "INSPECTED_READ_ONLY",
        "slot_count": len(layout.slots),
        "slots": [_read_slot_report(image, slot) for slot in layout.slots],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect a Barracks category and visible slots without clicking.")
    parser.add_argument("--image", type=Path, default=DEFAULT_FIXTURE, help="screenshot path; defaults to the Specialists fixture")
    parser.add_argument("--unit-type", choices=sorted(CATEGORY_TEMPLATES), help="require this highlighted category")
    args = parser.parse_args(argv)
    try:
        image = _read_image(args.image)
        report = inspect_image(image, expected_unit_type=args.unit_type)
    except (ArmyTrainingScannerError, UIVariantError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error), "actions_executed": False}, indent=2), file=sys.stderr)
        return 2
    report["source"] = str(args.image)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "INSPECTED_READ_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())