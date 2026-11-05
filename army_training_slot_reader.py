"""Read-only numeric readings for one located army training slot.

Each reading is taken from that slot's own regions only; limits are never shared
between slots. Values come with OCR confidence so callers can reject weak reads.
"""

from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from army_training_process import NumericReading
from army_training_scanner import ArmyTrainingScannerError
from army_training_slots import slot_crop
from tools.resource_ocr import parse_resource_amount

# Provisional; picked on the two clean fixtures (confidence 80-96 on correct reads).
CITY_COUNT_THRESHOLDS = (170, 190, 210)
CITY_COUNT_SCALES = (2, 4)
SILVER_WHITE_THRESHOLD = 150
PAD = 20
TIGHT_PAD = 30


@dataclass(frozen=True)
class SlotReadings:
    slot_index: int
    queue_limit: NumericReading
    city_count: NumericReading
    silver_cost: NumericReading


def _ocr(image, whitelist):
    config = f"--psm 7 -c tessedit_char_whitelist={whitelist}"
    try:
        data = pytesseract.image_to_data(image, config=config, output_type=Output.DICT)
    except pytesseract.TesseractNotFoundError as error:
        raise ArmyTrainingScannerError("Tesseract OCR was not found.") from error
    tokens, confidences = [], []
    for token, confidence in zip(data["text"], data["conf"]):
        token = token.strip()
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            continue
        if token and confidence >= 0:
            tokens.append(token)
            confidences.append(confidence)
    return "".join(tokens), (min(confidences) if confidences else None)


def _padded(mask):
    return cv2.copyMakeBorder(255 - mask, PAD, PAD, PAD, PAD, cv2.BORDER_CONSTANT, value=255)


def _enlarge(crop, factor=4):
    return cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)


def _to_int(text):
    digits = text.replace(",", "").replace("+", "")
    return int(digits) if digits.isdigit() else None


def _read_queue_limit(crop):
    # Dark text on a light bubble; the leading "+" must stay in the whitelist for stable confidence.
    gray = cv2.cvtColor(_enlarge(crop), cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    raw, confidence = _ocr(cv2.copyMakeBorder(mask, PAD, PAD, PAD, PAD, cv2.BORDER_CONSTANT, value=255), "+0123456789,")
    return NumericReading(_to_int(raw), confidence, raw)


def _read_city_count(crop):
    # Cream digits over artwork; a lone "0" is only stable when the glyph box is cropped tightly.
    best = NumericReading(None, None, "")
    for scale in CITY_COUNT_SCALES:
        big = _enlarge(crop, scale).astype(int)
        blue, green, red = big[..., 0], big[..., 1], big[..., 2]
        for threshold in CITY_COUNT_THRESHOLDS:
            mask = ((red >= threshold) & (green >= threshold) & (red - blue >= 20)).astype(np.uint8) * 255
            ys, xs = np.nonzero(mask)
            if ys.size == 0:
                continue
            glyphs = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            padded = cv2.copyMakeBorder(255 - glyphs, TIGHT_PAD, TIGHT_PAD, TIGHT_PAD, TIGHT_PAD, cv2.BORDER_CONSTANT, value=255)
            raw, confidence = _ocr(padded, "0123456789")
            value = _to_int(raw)
            if value is not None and confidence is not None and (best.confidence is None or confidence > best.confidence):
                best = NumericReading(value, confidence, raw)
    return best


def _read_silver_cost(crop):
    mask = (_enlarge(crop).min(axis=2) >= SILVER_WHITE_THRESHOLD).astype(np.uint8) * 255
    raw, confidence = _ocr(_padded(mask), "0123456789.,KMBT")
    return NumericReading(parse_resource_amount(raw), confidence, raw)


def read_slot_readings(image, slot):
    """Read limit, trained city count and silver cost of the currently selected level in one slot."""
    return SlotReadings(
        slot.index,
        _read_queue_limit(slot_crop(image, slot, "unit_troop_count_to_train")),
        _read_city_count(slot_crop(image, slot, "current_unit_troop_count")),
        _read_silver_cost(slot_crop(image, slot, "unit_troop_require_silver_to_train")),
    )
