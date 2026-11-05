#!/usr/bin/env python3
"""Build a read-only army-training dry-run report from one screenshot."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytesseract

from army_training_scanner import ArmyTrainingScannerError, read_army_training_snapshot
from army_training_levels import read_layout_selector_levels
from army_training_slot_reader import read_slot_readings
from army_training_slots import STATUS_OK, locate_slots
from tools.resource_ocr import ResourceReadError, read_image, read_resource_region
from ui_variants import UIVariantError, resolve_variant


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_SCREENSHOT = ROOT_DIR / "screenshots" / "army_training" / "pelny.png"
WORLD_MAP_FRAME_OFFSET_Y = 39
TRAINING_TARGET = {"global_level": 5, "match_number": 1}


class ArmyTrainingDryRunError(ValueError):
    """Raised when a dry-run report cannot be built safely."""


def _target_candidate_kind(level_reading, target_level):
    highest = level_reading["highest_visible_level"]
    if highest == target_level - 1:
        return "target_unavailable_one_level_below"
    if highest == target_level:
        return "target_at_presumed_highest"
    if level_reading["one_below_visible_level"] == target_level:
        return "target_at_one_below_position"
    return None


def build_dry_run_report(image_path=DEFAULT_SCREENSHOT, variant_id=None):
    variant = resolve_variant(variant_id)
    regions_data = json.loads(variant["regions"].read_text(encoding="utf-8"))
    world_map_regions = regions_data.get("world_map")
    if not isinstance(world_map_regions, dict):
        raise ArmyTrainingDryRunError("Brak regionów world_map wymaganych do odczytu HUD.")

    image = read_image(image_path)
    resources = {}
    for name in ("food", "silver"):
        region_name = f"{name}_count"
        source_region = world_map_regions.get(region_name)
        if not isinstance(source_region, dict):
            raise ArmyTrainingDryRunError(f"Brak regionu '{region_name}'.")
        region = dict(source_region)
        region["y"] = int(region["y"]) + WORLD_MAP_FRAME_OFFSET_Y
        resources[name] = read_resource_region(image, region)

    try:
        training = read_army_training_snapshot(image_path, variant_id=variant_id)
    except (ArmyTrainingScannerError, ResourceReadError, OSError, ValueError) as error:
        raise ArmyTrainingDryRunError(f"Nie można rozpoznać stanu Koszar: {error}") from error

    slot_layout = locate_slots(image, regions_data.get("army_training", {}), variant)
    slot_analysis = []
    layout_levels = None
    if slot_layout.status == STATUS_OK:
        layout_levels = read_layout_selector_levels(image, slot_layout.slots)
        for slot, level in zip(slot_layout.slots, layout_levels.slot_readings):
            readings = read_slot_readings(image, slot)
            slot_analysis.append({
                "frame_index": slot.index,
                "row": slot.row,
                "column": slot.column,
                "dx": slot.dx,
                "dy": slot.dy,
                "anchor_score": slot.anchor_score,
                "slider_score": slot.check_score,
                "level": {
                    "status": level.status,
                    "reason": level.reason,
                    "highest_visible_level": level.highest_visible_level,
                    "one_below_visible_level": level.one_below_visible_level,
                    "confidence": level.confidence,
                    "uses_default_highest_assumption": level.uses_default_highest_assumption,
                },
                "readings": {
                    "queue_limit": asdict(readings.queue_limit),
                    "city_count": asdict(readings.city_count),
                    "silver_cost": asdict(readings.silver_cost),
                },
            })

    blockers = []
    if any(
        reading["value"] is None
        or not reading["confidence_ok"]
        or reading["color"] == "unknown"
        for reading in resources.values()
    ):
        blockers.append("resource_read_uncertain")
    if resources["food"]["color"] == "red":
        blockers.append("food_is_red")
    if training["status"] == "active":
        blockers.append("training_already_active")
    elif training["status"] == "unknown":
        blockers.append("training_state_unknown")

    if slot_layout.status != STATUS_OK:
        blockers.append(f"slot_layout_{slot_layout.status}")
    elif layout_levels is None or layout_levels.status != "candidate":
        blockers.append("slot_level_read_uncertain")

    target_candidates = []
    for slot in slot_analysis:
        level = slot["level"]
        if level["status"] != "candidate":
            continue
        candidate_kind = _target_candidate_kind(level, TRAINING_TARGET["global_level"])
        if candidate_kind is None:
            continue
        target_candidates.append({"frame_index": slot["frame_index"], "kind": candidate_kind})

    if not target_candidates:
        blockers.append("target_level_not_confirmed_in_visible_slots")
    else:
        blockers.append("target_match_number_unverified")
        if not any(
            slot_analysis[candidate["frame_index"]]["readings"]["silver_cost"]["value"] is not None
            and slot_analysis[candidate["frame_index"]]["readings"]["silver_cost"]["confidence"] >= 70
            for candidate in target_candidates
        ):
            blockers.append("training_cost_unverified")

    manager_decision = {
        "status": "not_evaluated",
        "reason": "target_match_number_unverified" if target_candidates else "target_level_not_confirmed_in_visible_slots",
    }

    return {
        "mode": "dry_run",
        "image": str(Path(image_path)),
        "actions_executed": False,
        "queue_modified": False,
        "target": dict(TRAINING_TARGET),
        "status": "BLOCKED" if blockers else "READY_FOR_FURTHER_CHECKS",
        "blockers": blockers,
        "resources": resources,
        "training": training,
        "slot_layout": {
            "status": slot_layout.status,
            "reason": slot_layout.reason,
            "visible_slot_count": len(slot_layout.slots),
            "global_highest_visible_level": (
                layout_levels.global_highest_visible_level if layout_levels is not None else None
            ),
            "one_below_visible_level": layout_levels.one_below_visible_level if layout_levels is not None else None,
            "slots": slot_analysis,
        },
        "target_candidates": target_candidates,
        "manager_decision": manager_decision,
        "planned_steps": [
            {
                "action": "locate_training_slot",
                "position": target_candidates,
                "reason": manager_decision["reason"],
            },
            {
                "action": "read_training_cost_and_quantity",
                "position": target_candidates,
                "reason": "Odczyty per slot są raportowane, ale nie są wiązane z celem bez potwierdzonego match_number.",
            },
            {
                "action": "start_training",
                "position": None,
                "reason": (
                    "Dry-run nie wykonuje kliknięć; aktywne szkolenie blokuje start."
                    if training["status"] == "active"
                    else "Dry-run nie wykonuje kliknięć."
                ),
            },
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Utwórz raport dry-run szkolenia armii bez klikania.")
    parser.add_argument("--input", default=str(DEFAULT_SCREENSHOT), help="PNG screena Koszar")
    parser.add_argument("--variant", help="wariant interfejsu; domyślnie legacy")
    parser.add_argument("--tesseract", help="jawna ścieżka do tesseract.exe")
    args = parser.parse_args()

    if args.tesseract:
        pytesseract.pytesseract.tesseract_cmd = args.tesseract

    try:
        report = build_dry_run_report(args.input, variant_id=args.variant)
    except (
        ArmyTrainingDryRunError,
        ResourceReadError,
        UIVariantError,
        OSError,
        ValueError,
        pytesseract.TesseractNotFoundError,
    ) as error:
        print(f"Błąd dry-run: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())