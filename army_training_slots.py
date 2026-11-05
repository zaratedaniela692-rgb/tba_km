#!/usr/bin/env python3
"""Read-only detector of the visible unit slots in the army training window.

A slot is one unit training panel. Slots are located by the "Train" button and
cross-checked with the quantity slider. The detector never clicks and never
decides which unit or global level a slot holds; it only reports geometry.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2

from army_training_scanner import ArmyTrainingScannerError, _load_regions, _read_image, _region_crop
from ui_variants import UIVariantError, resolve_asset_path, resolve_variant

SCREEN = "army_training"
ANCHOR_REGION = "unit_troop_train_button"
CHECK_REGION = "unit_troop_coount_scroll_button"
# Regions that belong to one slot and are translated together with its anchor.
SLOT_REGIONS = (
    "unit_troop_level",
    "current_unit_troop_count",
    "unit_troop_count_to_train",
    "unit_troop_coount_scroll",
    "unit_troop_coount_scroll_button",
    "unit_troop_require_silver_to_train",
    "unit_troop_require_time_to_train",
    "unit_troop_food_production_load",
    "unit_troop_train_button",
)

# Provisional values; validated only on the two clean fixtures (scores 1.0, stride 261 px).
ANCHOR_THRESHOLD = 0.90
CHECK_THRESHOLD = 0.90
SLOT_STRIDE = 261
STRIDE_TOLERANCE = 2
DY_TOLERANCE = 3

STATUS_OK = "ok"
STATUS_NONE = "none"
STATUS_AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Slot:
    index: int  # reading order in this frame: top-left to bottom-right
    row: int
    column: int
    dx: int
    dy: int
    anchor_score: float
    check_score: float
    regions: dict


@dataclass(frozen=True)
class SlotLayout:
    status: str
    reason: str
    slots: tuple
    anchors: tuple  # (x, y, score) of every Train button candidate, top-left to bottom-right


def _find_anchors(image, template, threshold):
    """Return non-overlapping template matches at or above the threshold."""
    scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    height, width = template.shape[:2]
    found = []
    while True:
        _, best, _, (x, y) = cv2.minMaxLoc(scores)
        if best < threshold:
            break
        found.append((int(x), int(y), float(best)))
        scores[max(0, y - height + 1):y + height, max(0, x - width + 1):x + width] = -1.0
    return sorted(found)


def _group_rows(anchors):
    """Group matches into rows by y, each row ordered left to right."""
    rows = []
    for anchor in sorted(anchors, key=lambda item: (item[1], item[0])):
        if rows and anchor[1] - rows[-1][0][1] <= DY_TOLERANCE:
            rows[-1].append(anchor)
        else:
            rows.append([anchor])
    return [sorted(row) for row in rows]


def _check_score(image, template, expected_x, expected_y, margin):
    x0, y0 = expected_x - margin, expected_y - margin
    height, width = template.shape[:2]
    x1, y1 = expected_x + width + margin, expected_y + height + margin
    if x0 < 0 or y0 < 0 or x1 > image.shape[1] or y1 > image.shape[0]:
        return None
    roi = image[y0:y1, x0:x1]
    return float(cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED).max())


def _ambiguous(reason, anchors):
    return SlotLayout(STATUS_AMBIGUOUS, reason, (), tuple(anchors))


def locate_slots(image, regions, variant):
    """Locate slots in a BGR image using the army_training regions of one UI variant."""
    anchor_region = regions[ANCHOR_REGION]
    check_region = regions[CHECK_REGION]
    anchor_template = cv2.imread(str(resolve_asset_path(variant, anchor_region["template"])), cv2.IMREAD_COLOR)
    check_template = cv2.imread(str(resolve_asset_path(variant, check_region["template"])), cv2.IMREAD_COLOR)
    if anchor_template is None or check_template is None:
        raise ArmyTrainingScannerError("Cannot read slot anchor or check template.")

    anchors = _find_anchors(image, anchor_template, ANCHOR_THRESHOLD)
    if not anchors:
        return SlotLayout(STATUS_NONE, "no Train button found", (), ())

    rows = _group_rows(anchors)
    anchors = [anchor for row in rows for anchor in row]
    for upper, lower in zip(rows, rows[1:]):
        if lower[0][1] - upper[0][1] < anchor_template.shape[0]:
            return _ambiguous("Train button rows overlap vertically", anchors)
    for row in rows:
        for (left_x, _, _), (right_x, _, _) in zip(row, row[1:]):
            if abs(right_x - left_x - SLOT_STRIDE) > STRIDE_TOLERANCE:
                return _ambiguous(f"irregular slot spacing: {right_x - left_x} px", anchors)

    slots = []
    positions = [(row_index, column) for row_index, row in enumerate(rows) for column in range(len(row))]
    for index, ((x, y, anchor_score), (row_index, column)) in enumerate(zip(anchors, positions)):
        dx, dy = x - int(anchor_region["x"]), y - int(anchor_region["y"])
        check_score = _check_score(
            image,
            check_template,
            int(check_region["x"]) + dx,
            int(check_region["y"]) + dy,
            DY_TOLERANCE,
        )
        if check_score is None:
            return _ambiguous(f"slot {index} slider region is outside the image", anchors)
        if check_score < CHECK_THRESHOLD:
            return _ambiguous(f"slot {index} slider not confirmed (score {check_score:.3f})", anchors)
        translated = {}
        for name in SLOT_REGIONS:
            region = regions[name]
            translated[name] = {
                "x": int(region["x"]) + dx,
                "y": int(region["y"]) + dy,
                "w": int(region["w"]),
                "h": int(region["h"]),
            }
        slots.append(Slot(index, row_index, column, dx, dy, anchor_score, check_score, translated))
    return SlotLayout(STATUS_OK, "", tuple(slots), tuple(anchors))


def slot_crop(image, slot, region_name):
    """Crop one named element of one slot from the same image the slot was located in."""
    if region_name not in slot.regions:
        raise ArmyTrainingScannerError(f"Unknown slot region: {region_name}")
    return _region_crop(image, slot.regions[region_name])


def find_slots(image_path, screen=SCREEN, regions_path=None, variant_id=None):
    """Read an image file and locate the visible slots without touching the game."""
    variant = resolve_variant(variant_id)
    regions_path = Path(regions_path) if regions_path is not None else variant["regions"]
    regions = _load_regions(regions_path).get(screen)
    if not isinstance(regions, dict):
        raise ArmyTrainingScannerError(f"Missing regions for screen '{screen}'.")
    missing = [name for name in (*SLOT_REGIONS, ANCHOR_REGION, CHECK_REGION) if name not in regions]
    if missing:
        raise ArmyTrainingScannerError(f"Missing slot regions: {', '.join(missing)}")
    return locate_slots(_read_image(image_path), regions, variant)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Report visible army training slots (read-only).")
    parser.add_argument("input", help="Path to a Barracks screenshot.")
    parser.add_argument("--variant", default=None, help="UI variant id.")
    args = parser.parse_args(argv)
    try:
        layout = find_slots(args.input, variant_id=args.variant)
    except (ArmyTrainingScannerError, UIVariantError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": layout.status,
        "reason": layout.reason,
        "anchors": layout.anchors,
        "slots": [slot.__dict__ for slot in layout.slots],
    }, indent=2))
    return 0 if layout.status == STATUS_OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
