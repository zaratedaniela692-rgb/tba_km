"""Read the displayed full-queue training time of one slot ("11 d. 15 g."); read-only.

The label is a day/hour estimate, not a countdown. Glyphs are segmented first: the
"d." and "g." markers fix how many digits belong to each number, so a merged or lost
glyph can never turn 11 into 1. Each digit is then read on its own at several scales and
accepted only if all reads agree. Only the "d." and "g." units seen on the fixtures exist.
"""

import cv2
import numpy as np
import pytesseract

from army_training_process import NumericReading
from army_training_scanner import ArmyTrainingScannerError
from army_training_slots import slot_crop

SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR
INK_THRESHOLD = 100  # dark brown ink on a light label; ink reaches gray ~50
MIN_COMPONENT_AREA = 3
MAX_DOT_SIZE = 3
MAX_GLYPH_WIDTH = 9  # a merged pair of digits is wider and must not pass as one digit
MAX_DAY_DIGITS = 3
MAX_HOUR_DIGITS = 2
DIGIT_SCALES = (6, 10)
DIGIT_PAD = 2
DIGIT_BORDER = 30
VERIFIED_DIGITS = frozenset("12345")
LABEL_DAYS = "d"
LABEL_HOURS = "g"


def _components(gray):
    count, _, stats, _ = cv2.connectedComponentsWithStats((gray < INK_THRESHOLD).astype(np.uint8), connectivity=8)
    found = [tuple(int(v) for v in row) for row in stats[1:] if row[4] >= MIN_COMPONENT_AREA]
    return sorted(found)  # (x, y, w, h, area), left to right


def _is_dot(component):
    return component[2] <= MAX_DOT_SIZE and component[3] <= MAX_DOT_SIZE


def _split_label(components):
    """Return (day digits, hour digits) as `digits d . digits g .`, or None for any other layout."""
    dots = [index for index, component in enumerate(components) if _is_dot(component)]
    if len(dots) != 2 or dots[1] != len(components) - 1 or dots[0] < 2 or dots[1] - dots[0] < 3:
        return None
    day_digits = components[:dots[0] - 1]  # the glyph before the first dot is the "d"
    hour_digits = components[dots[0] + 1:dots[1] - 1]  # the glyph before the last dot is the "g"
    if not 1 <= len(day_digits) <= MAX_DAY_DIGITS or not 1 <= len(hour_digits) <= MAX_HOUR_DIGITS:
        return None
    if any(component[2] > MAX_GLYPH_WIDTH for component in day_digits + hour_digits):
        return None
    return day_digits, hour_digits


def _read_digit(gray, component, scale):
    x, y, width, height, _ = component
    patch = gray[max(0, y - DIGIT_PAD):y + height + DIGIT_PAD, max(0, x - DIGIT_PAD):x + width + DIGIT_PAD]
    enlarged = cv2.resize(patch, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, mask = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    padded = cv2.copyMakeBorder(mask, DIGIT_BORDER, DIGIT_BORDER, DIGIT_BORDER, DIGIT_BORDER, cv2.BORDER_CONSTANT, value=255)
    try:
        text = pytesseract.image_to_string(padded, config="--psm 10 -c tessedit_char_whitelist=0123456789").strip()
    except pytesseract.TesseractNotFoundError as error:
        raise ArmyTrainingScannerError("Tesseract OCR was not found.") from error
    return text if len(text) == 1 else None


def _read_number(gray, digits):
    """Digits of one number, or None unless every scale reads every glyph identically."""
    reads = ["".join(_read_digit(gray, digit, scale) or "?" for digit in digits) for scale in DIGIT_SCALES]
    if len(set(reads)) != 1 or "?" in reads[0] or not set(reads[0]) <= VERIFIED_DIGITS:
        return None
    return reads[0]


def read_slot_training_time(image, slot):
    """Full-queue time in seconds (day/hour resolution); the value is None unless unambiguous.

    Confidence is 100 when every digit read agreed, otherwise None; it is not Tesseract's score.
    """
    gray = cv2.cvtColor(slot_crop(image, slot, "unit_troop_require_time_to_train"), cv2.COLOR_BGR2GRAY)
    parts = _split_label(_components(gray))
    if parts is None:
        return NumericReading(None, None, "layout_unrecognized")
    days, hours = (_read_number(gray, digits) for digits in parts)
    if days is None or hours is None or int(hours) >= 24:
        return NumericReading(None, None, f"{days or '?'}{LABEL_DAYS}.{hours or '?'}{LABEL_HOURS}.")
    raw = f"{days}{LABEL_DAYS}.{hours}{LABEL_HOURS}."
    return NumericReading(int(days) * SECONDS_PER_DAY + int(hours) * SECONDS_PER_HOUR, 100.0, raw)
