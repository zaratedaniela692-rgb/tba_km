"""Read the remaining time of the speedup dialog ("13 d.:7 g."); read-only.

Light digits on a dark bar. Glyphs are segmented first so a merged or lost glyph cannot
change a number, then each digit is read alone at two scales and accepted only if both agree.
"""

import os
import re
import shutil
from pathlib import Path

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
UNIT_SCALES = (8, 12)
UNIT_PAD = 3
UNIT_BORDER = 40
MINUTE_OCR_SCALES = (4, 6)
MINUTE_OCR_PSMS = (7, 8)
# Digits confirmed on fixtures; informational only, not an acceptance whitelist.
VERIFIED_DIGITS = frozenset("13467")


def configure_tesseract(executable=None):
    """Use an explicit executable, PATH lookup, or the standard Windows install path."""
    candidates = [executable, os.environ.get("TESSERACT_CMD"), shutil.which("tesseract")]
    if os.name == "nt":
        candidates.extend((
            str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe"),
            str(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tesseract-OCR" / "tesseract.exe"),
        ))

    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if resolved:
            pytesseract.pytesseract.tesseract_cmd = resolved
            return resolved
    return None


def _components(gray):
    _, _, stats, _ = cv2.connectedComponentsWithStats((gray > INK_THRESHOLD).astype(np.uint8), connectivity=8)
    return sorted(tuple(int(v) for v in row[:4]) for row in stats[1:] if row[4] >= MIN_COMPONENT_AREA)


def _split_label(components):
    """Return the two digit groups and their adjacent unit glyphs, or None for unknown layouts."""
    dots = [c for c in components if c[2] <= MAX_DOT_SIZE and c[3] <= MAX_DOT_SIZE]
    glyphs = [c for c in components if c not in dots and c[3] in GLYPH_HEIGHTS]
    if len(dots) < 2 or len(glyphs) < 4:
        return None
    first_dot, last_dot = dots[0], dots[-1]
    before_first_dot = [g for g in glyphs if g[0] + g[2] <= first_dot[0]]
    if not before_first_dot or last_dot[0] < glyphs[-1][0] + glyphs[-1][2]:
        return None
    first_unit = before_first_dot[-1]
    before_last_dot = [g for g in glyphs if g[0] + g[2] <= last_dot[0]]
    if not before_last_dot:
        return None
    second_unit = before_last_dot[-1]
    first_digits = before_first_dot[:-1]
    second_digits = [
        g for g in glyphs
        if g[0] > first_unit[0] and g[0] + g[2] <= second_unit[0]
    ]
    if not 1 <= len(first_digits) <= MAX_DAY_DIGITS or not 1 <= len(second_digits) <= MAX_HOUR_DIGITS:
        return None
    return first_digits, first_unit, second_digits, second_unit


def _crop_timer_text(gray, parts):
    """Exclude adjacent icons by cropping to the detected timer glyph bounds."""
    first_digits, first_unit, second_digits, second_unit = parts
    boxes = first_digits + [first_unit] + second_digits + [second_unit]
    x0 = max(0, min(box[0] for box in boxes) - 1)
    y0 = max(0, min(box[1] for box in boxes) - 1)
    x1 = min(gray.shape[1], max(box[0] + box[2] for box in boxes) + 1)
    y1 = min(gray.shape[0], max(box[1] + box[3] for box in boxes) + 1)
    return gray[y0:y1, x0:x1]


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
    """Read digits when both scales agree; VERIFIED_DIGITS only records fixture coverage."""
    reads = ["".join(_read_digit(gray, digit, scale) or "?" for digit in digits) for scale in DIGIT_SCALES]
    if len(set(reads)) != 1 or "?" in reads[0]:
        return None
    return reads[0]


def _read_unit(gray, component):
    x, y, width, height = component
    patch = gray[
        max(0, y - UNIT_PAD):y + height + UNIT_PAD,
        max(0, x - UNIT_PAD):x + width + UNIT_PAD,
    ]
    variants = []
    for scale in UNIT_SCALES:
        enlarged = cv2.resize(patch, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        _, mask = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        variants.append(cv2.copyMakeBorder(
            mask, UNIT_BORDER, UNIT_BORDER, UNIT_BORDER, UNIT_BORDER,
            cv2.BORDER_CONSTANT, value=255,
        ))

    height = max(variant.shape[0] for variant in variants)
    canvas = np.full((height, sum(variant.shape[1] for variant in variants) + UNIT_BORDER, 3), 255, dtype=np.uint8)
    offset = 0
    for variant in variants:
        top = (height - variant.shape[0]) // 2
        canvas[top:top + variant.shape[0], offset:offset + variant.shape[1]] = cv2.cvtColor(variant, cv2.COLOR_GRAY2BGR)
        offset += variant.shape[1] + UNIT_BORDER

    try:
        text = pytesseract.image_to_string(
            canvas,
            config="--psm 7 -c tessedit_char_whitelist=dDgGhHmMsS",
        ).strip().lower()
    except pytesseract.TesseractNotFoundError as error:
        raise ArmyTrainingScannerError("Tesseract OCR was not found.") from error
    return text[0] if len(text) == 2 and text[0] == text[1] and text[0] in {"d", "g", "h", "m", "s"} else None


def _read_minute_timer(gray):
    reads = []
    for scale in MINUTE_OCR_SCALES:
        enlarged = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        for psm in MINUTE_OCR_PSMS:
            try:
                text = pytesseract.image_to_string(
                    enlarged,
                    config=f"--psm {psm} -c tessedit_char_whitelist=0123456789dDgGhHmMsS",
                ).strip()
            except pytesseract.TesseractNotFoundError as error:
                raise ArmyTrainingScannerError("Tesseract OCR was not found.") from error
            normalized = re.sub(r"^\s*[hH]\s*(?=\d)", "", text, count=1)
            reading = parse_remaining_time(normalized, 100.0)
            reads.append((text, reading.value, reading.status))

    values = {value for _, value, _ in reads}
    raw = " / ".join(text for text, _, _ in reads)
    if len(values) == 1 and None not in values:
        return ParsedReading(reads[0][0], next(iter(values)), 100.0, "ok")
    agreement = max((sum(value == candidate for _, value, _ in reads) for candidate in values), default=0)
    return ParsedReading(raw, None, agreement * 100 / len(reads), "minute_ocr_disagreement")


def read_remaining_time(image, variant=None, tesseract_cmd=None):
    """Read timer values from their recognized units; ambiguous values remain unset."""
    configure_tesseract(tesseract_cmd)
    variant = variant or resolve_variant()
    region = _load_regions(variant["regions"])[REGION_SCREEN][REGION_NAME]
    gray = cv2.cvtColor(_region_crop(image, region), cv2.COLOR_BGR2GRAY)
    if gray.size == 0 or float(gray.std()) < 1.0:
        return ParsedReading("", None, None, "layout_unrecognized")
    parts = _split_label(_components(gray))
    if parts is None:
        return _read_minute_timer(gray)
    first_digits, first_unit_component, second_digits, second_unit_component = parts
    first, second = _read_number(gray, first_digits), _read_number(gray, second_digits)
    first_unit, second_unit = (
        _read_unit(gray, component)
        for component in (first_unit_component, second_unit_component)
    )
    raw = f"{first or '?'}{first_unit or '?'}.:{second or '?'}{second_unit or '?'}."
    if first is None or second is None or first_unit is None or second_unit is None:
        minute_reading = _read_minute_timer(_crop_timer_text(gray, parts))
        return minute_reading if minute_reading.value is not None else ParsedReading(raw, None, None, "digit_unverified")
    return parse_remaining_time(raw, 100.0)
