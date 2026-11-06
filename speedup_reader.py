"""Read the remaining time of the speedup dialog ("13 d.:7 g."); read-only.

Light digits on a dark bar. Glyphs are segmented first so a merged or lost glyph cannot
change a number, then each digit is read alone at two scales and accepted only if both agree.
"""

import cv2
import numpy as np
import pytesseract

from army_training_scanner import ArmyTrainingScannerError, _load_regions, _region_crop
from speedup_readings import ParsedReading, parse_remaining_time
from ui_variants import resolve_variant

REGION_SCREEN = "speedup"
REGION_NAME = "speedup_remaining_time"
INK_THRESHOLD = 170
MIN_COMPONENT_AREA = 3
MAX_DOT_SIZE = 3
GLYPH_HEIGHTS = range(8, 14)  # the hourglass icon is taller and is dropped
MAX_DAY_DIGITS = 3
MAX_HOUR_DIGITS = 2
DIGIT_SCALES = (6, 10)
DIGIT_PAD = 2
DIGIT_BORDER = 30
# Digits confirmed by two independent reads on the supplied fixtures.
VERIFIED_DIGITS = frozenset("13467")


def _components(gray):
    _, _, stats, _ = cv2.connectedComponentsWithStats((gray > INK_THRESHOLD).astype(np.uint8), connectivity=8)
    return sorted(tuple(int(v) for v in row[:4]) for row in stats[1:] if row[4] >= MIN_COMPONENT_AREA)


def _split_label(components):
    """(day digits, hour digits) of `digits d . : digits g .`, or None for any other layout."""
    dots = [c for c in components if c[2] <= MAX_DOT_SIZE and c[3] <= MAX_DOT_SIZE]
    glyphs = [c for c in components if c not in dots and c[3] in GLYPH_HEIGHTS]
    if len(dots) < 2 or len(glyphs) < 4:
        return None
    first_dot, last_dot = dots[0], dots[-1]
    before_first_dot = [g for g in glyphs if g[0] + g[2] <= first_dot[0]]
    if not before_first_dot or last_dot[0] < glyphs[-1][0] + glyphs[-1][2]:
        return None
    day_label = before_first_dot[-1]
    day_digits = before_first_dot[:-1]
    hour_digits = [g for g in glyphs if g[0] > day_label[0] and g is not glyphs[-1]]
    if not 1 <= len(day_digits) <= MAX_DAY_DIGITS or not 1 <= len(hour_digits) <= MAX_HOUR_DIGITS:
        return None
    return day_digits, hour_digits


def _read_digit(gray, component, scale):
    x, y, width, height = component
    patch = gray[max(0, y - DIGIT_PAD):y + height + DIGIT_PAD, max(0, x - DIGIT_PAD):x + width + DIGIT_PAD]
    enlarged = cv2.resize(patch, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, mask = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
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


def read_remaining_time(image, variant=None):
    """Remaining task time in seconds (day/hour resolution); `value` is None unless unambiguous."""
    variant = variant or resolve_variant()
    region = _load_regions(variant["regions"])[REGION_SCREEN][REGION_NAME]
    gray = cv2.cvtColor(_region_crop(image, region), cv2.COLOR_BGR2GRAY)
    parts = _split_label(_components(gray))
    if parts is None:
        return ParsedReading("", None, None, "layout_unrecognized")
    days, hours = (_read_number(gray, digits) for digits in parts)
    raw = f"{days or '?'}d.:{hours or '?'}g."
    if days is None or hours is None:
        return ParsedReading(raw, None, None, "digit_unverified")
    return parse_remaining_time(raw, 100.0)
