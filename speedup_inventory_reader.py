"""Read owned speedup quantities from the approved static checkpoints."""

import re
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract

from speedup_button_map import locate_use_buttons
from speedup_readings import ParsedReading, parse_duration, parse_quantity
from speedup_reader import configure_tesseract

OCR_SCALES = (4, 6)
OCR_PRIMARY_PSM = 8
OCR_FALLBACK_PSM = 7
CROP_LEFT_INSET = 5
CROP_RIGHT_INSET = 3
BUTTON_OFFSET_CONSISTENCY_TOLERANCE = 1


class InventoryReadError(ValueError):
    """The checkpoint image does not support a complete inventory reading."""


@dataclass(frozen=True)
class InventoryItemReading:
    duration_label: str
    duration_seconds: int
    quantity: ParsedReading
    scroll_count: int
    button_rectangle: dict
    button_center: dict


@dataclass(frozen=True)
class CheckpointInventoryReading:
    status: str
    items: tuple
    reason: str = ""
    checkpoint_steps: tuple = ()
    match_diagnostics: tuple = ()
    quantity_diagnostics: tuple = ()

    @property
    def inventory(self):
        if self.status != "complete":
            return None
        return {item.duration_seconds: item.quantity.value for item in self.items}


def _quantity_crop(viewport_image, button, quantity_region, use_region):
    offset_x = int(quantity_region["x"]) - int(use_region["x"])
    offset_y = int(quantity_region["y"]) - int(use_region["y"])
    rectangle = button["rectangle"]
    left = int(rectangle["x"]) + offset_x + CROP_LEFT_INSET
    top = int(rectangle["y"]) + offset_y
    right = int(rectangle["x"]) + offset_x + int(quantity_region["w"]) - CROP_RIGHT_INSET
    bottom = top + int(quantity_region["h"])
    crop = viewport_image[top:bottom, left:right]
    if crop.shape[:2] != (int(quantity_region["h"]), right - left):
        raise InventoryReadError("quantity_region_outside_viewport")
    return crop


def _ocr_digits(crop, scale, psm):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    enlarged = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return pytesseract.image_to_string(
        enlarged,
        config=f"--psm {psm} -c tessedit_char_whitelist=0123456789",
    ).strip()


def _read_quantity(crop, ocr_fn):
    primary_reads = tuple(ocr_fn(crop, scale, OCR_PRIMARY_PSM) for scale in OCR_SCALES)
    primary_normalized = tuple(re.sub(r"\s+", "", raw) for raw in primary_reads)
    raw_evidence = " / ".join(primary_reads)
    if not primary_normalized[0] or len(set(primary_normalized)) != 1:
        fallback_reads = tuple(ocr_fn(crop, scale, OCR_FALLBACK_PSM) for scale in OCR_SCALES)
        normalized = tuple(re.sub(r"\s+", "", raw) for raw in fallback_reads)
        raw_evidence += f"; psm{OCR_FALLBACK_PSM}: " + " / ".join(fallback_reads)
        if not normalized[0] or len(set(normalized)) != 1:
            agreement = max(normalized.count(value) for value in set(normalized)) / len(normalized)
            status = "ocr_disagreement" if any(normalized) else "unreadable"
            return ParsedReading(raw_evidence, None, agreement * 100, status)
    else:
        normalized = primary_normalized

    parsed = parse_quantity(normalized[0], 100.0)
    return ParsedReading(raw_evidence, parsed.value, parsed.confidence, parsed.status)


def read_checkpoint_viewport(
    viewport_image,
    checkpoint,
    button_template,
    quantity_region,
    use_region,
    expected_viewport_size=(562, 418),
    ocr_fn=None,
    duration_seconds=None,
    verify_only=False,
):
    """Read mapped quantities, optionally limiting OCR to one requested duration."""
    if viewport_image is None or viewport_image.shape[:2] != (expected_viewport_size[1], expected_viewport_size[0]):
        return CheckpointInventoryReading("incomplete", (), "unexpected_viewport_size")

    step = checkpoint.get("scroll_count")
    expected_buttons = checkpoint.get("buttons", ())
    expected_size = (int(expected_viewport_size[0]), int(expected_viewport_size[1]))
    try:
        found_buttons = locate_use_buttons(
            viewport_image,
            {"x": 0, "y": 0, "w": expected_viewport_size[0], "h": expected_viewport_size[1]},
            button_template,
        )
    except (ValueError, cv2.error) as error:
        return CheckpointInventoryReading(
            "incomplete", (), f"button_match_failed:{error}",
            match_diagnostics=({"error": str(error)},),
        )

    match_diagnostics = tuple({
        "duration_label": expected.get("duration_label"),
        "expected_rectangle": dict(expected.get("rectangle", {})),
        "detected_rectangle": {
            "x": found["x"], "y": found["y"],
            "width": found["width"], "height": found["height"],
        },
        "offset": {
            "x": found["x"] - int(expected.get("rectangle", {}).get("x", -10000)),
            "y": found["y"] - int(expected.get("rectangle", {}).get("y", -10000)),
        },
        "confidence": found["confidence"],
    } for found, expected in zip(found_buttons, expected_buttons))

    if len(found_buttons) != len(expected_buttons):
        return CheckpointInventoryReading(
            "incomplete", (), "use_button_count_mismatch",
            match_diagnostics=match_diagnostics + ({
                "expected_count": len(expected_buttons),
                "detected_count": len(found_buttons),
                "detected_rectangles": tuple({
                    "x": found["x"], "y": found["y"],
                    "width": found["width"], "height": found["height"],
                    "confidence": found["confidence"],
                } for found in found_buttons),
            },),
        )
    effective_buttons = []
    offsets = []
    for found, expected in zip(found_buttons, expected_buttons):
        rectangle = expected.get("rectangle", {})
        delta_x = found["x"] - int(rectangle.get("x", -10000))
        delta_y = found["y"] - int(rectangle.get("y", -10000))
        if (
            found["x"] < 0 or found["y"] < 0
            or found["x"] + found["width"] > expected_size[0]
            or found["y"] + found["height"] > expected_size[1]
        ):
            return CheckpointInventoryReading(
                "incomplete", (), "use_button_outside_viewport",
                match_diagnostics=match_diagnostics,
            )
        offsets.append((delta_x, delta_y))
        effective = dict(expected)
        effective["rectangle"] = {
            "x": found["x"],
            "y": found["y"],
            "width": found["width"],
            "height": found["height"],
        }
        effective["center"] = {
            "x": found["x"] + found["width"] // 2,
            "y": found["y"] + found["height"] // 2,
        }
        effective_buttons.append(effective)

    if offsets:
        base_offset = offsets[0]
        if any(
            abs(delta_x - base_offset[0]) > BUTTON_OFFSET_CONSISTENCY_TOLERANCE
            or abs(delta_y - base_offset[1]) > BUTTON_OFFSET_CONSISTENCY_TOLERANCE
            for delta_x, delta_y in offsets[1:]
        ):
            return CheckpointInventoryReading(
                "incomplete", (), "use_button_offsets_inconsistent",
                match_diagnostics=match_diagnostics,
            )

    if verify_only:
        return CheckpointInventoryReading(
            "complete", (), checkpoint_steps=(int(step),), match_diagnostics=match_diagnostics,
        )

    configure_tesseract()
    ocr_fn = ocr_fn or _ocr_digits
    if duration_seconds is not None:
        effective_buttons = [
            button for button in effective_buttons
            if parse_duration(button.get("duration_label", ""), 100.0).value == duration_seconds
        ]
        if len(effective_buttons) != 1:
            return CheckpointInventoryReading(
                "incomplete", (), "target_duration_not_unique",
                match_diagnostics=match_diagnostics,
            )
    items = []
    quantity_diagnostics = []
    for button in effective_buttons:
        duration = parse_duration(button.get("duration_label", ""), 100.0)
        if duration.value is None:
            return CheckpointInventoryReading(
                "incomplete", tuple(items), "mapped_duration_invalid",
                match_diagnostics=match_diagnostics,
                quantity_diagnostics=tuple(quantity_diagnostics),
            )
        try:
            crop = _quantity_crop(viewport_image, button, quantity_region, use_region)
            quantity = _read_quantity(crop, ocr_fn)
        except (InventoryReadError, pytesseract.TesseractNotFoundError, OSError) as error:
            quantity_diagnostics.append({
                "duration_label": button["duration_label"],
                "duration_seconds": duration.value,
                "status": "error",
                "reason": str(error),
                "button_rectangle": dict(button["rectangle"]),
            })
            return CheckpointInventoryReading(
                "incomplete", tuple(items), f"quantity_ocr_failed:{error}",
                match_diagnostics=match_diagnostics,
                quantity_diagnostics=tuple(quantity_diagnostics),
            )
        quantity_diagnostics.append({
            "duration_label": button["duration_label"],
            "duration_seconds": duration.value,
            "raw_ocr": quantity.raw,
            "quantity": quantity.value,
            "confidence": quantity.confidence,
            "status": quantity.status,
            "button_rectangle": dict(button["rectangle"]),
        })
        if quantity.value is None:
            return CheckpointInventoryReading(
                "incomplete", tuple(items), f"quantity_unreadable:{button['duration_label']}:{quantity.status}",
                match_diagnostics=match_diagnostics,
                quantity_diagnostics=tuple(quantity_diagnostics),
            )
        items.append(InventoryItemReading(
            button["duration_label"],
            duration.value,
            quantity,
            int(step),
            dict(button["rectangle"]),
            dict(button["center"]),
        ))

    return CheckpointInventoryReading(
        "complete", tuple(items), checkpoint_steps=(int(step),),
        match_diagnostics=match_diagnostics,
        quantity_diagnostics=tuple(quantity_diagnostics),
    )


def combine_checkpoint_readings(readings):
    """Combine checkpoint rows and reject inconsistent repeated durations."""
    readings = tuple(readings)
    if not readings or any(reading.status != "complete" for reading in readings):
        reason = next((reading.reason for reading in readings if reading.status != "complete"), "no_checkpoint_readings")
        return CheckpointInventoryReading("incomplete", (), reason)

    by_duration = {}
    for reading in readings:
        for item in reading.items:
            previous = by_duration.get(item.duration_seconds)
            if previous is not None and previous.quantity.value != item.quantity.value:
                return CheckpointInventoryReading(
                    "incomplete", (), f"duplicate_quantity_conflict:{item.duration_label}",
                    tuple(step for current in readings for step in current.checkpoint_steps),
                )
            if previous is None or item.scroll_count < previous.scroll_count:
                by_duration[item.duration_seconds] = item

    steps = tuple(step for reading in readings for step in reading.checkpoint_steps)
    items = tuple(by_duration[duration] for duration in sorted(by_duration))
    return CheckpointInventoryReading("complete", items, checkpoint_steps=steps)