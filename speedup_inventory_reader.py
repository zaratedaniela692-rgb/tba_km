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
OCR_PSMS = (8,)
CROP_LEFT_INSET = 5
CROP_RIGHT_INSET = 3
BUTTON_POSITION_TOLERANCE = 6
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
    raw_reads = tuple(ocr_fn(crop, scale, psm) for scale in OCR_SCALES for psm in OCR_PSMS)
    normalized = tuple(re.sub(r"\s+", "", raw) for raw in raw_reads)
    raw_evidence = " / ".join(raw_reads)
    if not normalized[0] or len(set(normalized)) != 1:
        agreement = max(normalized.count(value) for value in set(normalized)) / len(normalized)
        return ParsedReading(raw_evidence, None, agreement * 100, "ocr_disagreement" if any(normalized) else "unreadable")

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
):
    """Read mapped quantities, optionally limiting OCR to one requested duration."""
    if viewport_image is None or viewport_image.shape[:2] != (expected_viewport_size[1], expected_viewport_size[0]):
        return CheckpointInventoryReading("incomplete", (), "unexpected_viewport_size")

    step = checkpoint.get("scroll_count")
    expected_buttons = checkpoint.get("buttons", ())
    try:
        found_buttons = locate_use_buttons(
            viewport_image,
            {"x": 0, "y": 0, "w": expected_viewport_size[0], "h": expected_viewport_size[1]},
            button_template,
        )
    except (ValueError, cv2.error) as error:
        return CheckpointInventoryReading("incomplete", (), f"button_match_failed:{error}")

    if len(found_buttons) != len(expected_buttons):
        return CheckpointInventoryReading("incomplete", (), "use_button_count_mismatch")
    effective_buttons = []
    offsets = []
    for found, expected in zip(found_buttons, expected_buttons):
        rectangle = expected.get("rectangle", {})
        delta_x = found["x"] - int(rectangle.get("x", -10000))
        delta_y = found["y"] - int(rectangle.get("y", -10000))
        if abs(delta_x) > BUTTON_POSITION_TOLERANCE or abs(delta_y) > BUTTON_POSITION_TOLERANCE:
            return CheckpointInventoryReading("incomplete", (), "use_button_position_mismatch")
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
            return CheckpointInventoryReading("incomplete", (), "use_button_offsets_inconsistent")

    configure_tesseract()
    ocr_fn = ocr_fn or _ocr_digits
    if duration_seconds is not None:
        effective_buttons = [
            button for button in effective_buttons
            if parse_duration(button.get("duration_label", ""), 100.0).value == duration_seconds
        ]
        if len(effective_buttons) != 1:
            return CheckpointInventoryReading("incomplete", (), "target_duration_not_unique")
    items = []
    for button in effective_buttons:
        duration = parse_duration(button.get("duration_label", ""), 100.0)
        if duration.value is None:
            return CheckpointInventoryReading("incomplete", tuple(items), "mapped_duration_invalid")
        try:
            crop = _quantity_crop(viewport_image, button, quantity_region, use_region)
            quantity = _read_quantity(crop, ocr_fn)
        except (InventoryReadError, pytesseract.TesseractNotFoundError, OSError) as error:
            return CheckpointInventoryReading("incomplete", tuple(items), f"quantity_ocr_failed:{error}")
        if quantity.value is None:
            return CheckpointInventoryReading("incomplete", tuple(items), f"quantity_unreadable:{button['duration_label']}:{quantity.status}")
        items.append(InventoryItemReading(
            button["duration_label"],
            duration.value,
            quantity,
            int(step),
            dict(button["rectangle"]),
            dict(button["center"]),
        ))

    return CheckpointInventoryReading("complete", tuple(items), checkpoint_steps=(int(step),))


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