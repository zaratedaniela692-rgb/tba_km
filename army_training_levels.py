"""Read the presumed highest visible selector level without clicking the game."""

from dataclasses import dataclass

import cv2
import pytesseract
from pytesseract import Output

from army_training_scanner import ArmyTrainingScannerError

from army_training_slots import slot_crop

BADGE_SCALE = 5
BADGE_MIN_DISTANCE = 90
BADGE_EDGE_THRESHOLD = 80
BADGE_CENTER_THRESHOLD = 25
BADGE_MIN_RADIUS = 35
BADGE_MAX_RADIUS = 60
BADGE_X_CENTER = 10
BADGE_X_TOLERANCE = 3
ADJACENT_ROW_MIN_DISTANCE = 20
ADJACENT_ROW_MAX_DISTANCE = 30
BADGE_RADIUS_MIN_MARGIN = 0.5
BADGE_LABEL_SCALES = (0.65, 1.2)
BADGE_LABEL_OCR_MIN_CONFIDENCE = 60
BADGE_LABEL_PADDING = 30
ROMAN_LEVELS = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9}


@dataclass(frozen=True)
class SelectorLevelReading:
    status: str
    reason: str
    badge_centers: tuple
    highest_badge: tuple | None
    highest_visible_level: int | None = None
    one_below_visible_level: int | None = None
    confidence: float | None = None
    uses_default_highest_assumption: bool = True


@dataclass(frozen=True)
class LayoutLevelReading:
    status: str
    reason: str
    global_highest_visible_level: int | None
    one_below_visible_level: int | None
    highest_slot_indices: tuple
    one_below_slot_indices: tuple
    slot_readings: tuple


def detect_selector_badges(selector):
    """Return badge centers (x, y, radius) in selector pixels, ordered top to bottom."""
    gray = cv2.cvtColor(selector, cv2.COLOR_BGR2GRAY)
    scaled = cv2.resize(gray, None, fx=BADGE_SCALE, fy=BADGE_SCALE, interpolation=cv2.INTER_CUBIC)
    circles = cv2.HoughCircles(
        scaled,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=BADGE_MIN_DISTANCE,
        param1=BADGE_EDGE_THRESHOLD,
        param2=BADGE_CENTER_THRESHOLD,
        minRadius=BADGE_MIN_RADIUS,
        maxRadius=BADGE_MAX_RADIUS,
    )
    if circles is None:
        return ()
    found = []
    for x, y, radius in circles[0]:
        x, y, radius = x / BADGE_SCALE, y / BADGE_SCALE, radius / BADGE_SCALE
        if abs(x - BADGE_X_CENTER) <= BADGE_X_TOLERANCE:
            found.append((round(x, 2), round(y, 2), round(radius, 2)))
    return tuple(sorted(found, key=lambda badge: badge[1]))


def _read_badge_label(selector, badge):
    x, y, radius = (int(value) for value in badge)
    readings = []
    for mode, scale, psms in (("masked", BADGE_LABEL_SCALES[0], (7, 10)), ("raw", BADGE_LABEL_SCALES[1], (8, 13))):
        crop_radius = max(3, int(radius * scale))
        crop = selector[
            max(0, y - crop_radius):min(selector.shape[0], y + crop_radius + 1),
            max(0, x - crop_radius):min(selector.shape[1], x + crop_radius + 1),
        ]
        enlarged = cv2.resize(crop, None, fx=12, fy=12, interpolation=cv2.INTER_CUBIC)
        if mode == "masked":
            hsv = cv2.cvtColor(enlarged, cv2.COLOR_BGR2HSV)
            mask = ((hsv[:, :, 2] > 170) & (hsv[:, :, 1] < 140)).astype("uint8") * 255
            nonzero = cv2.findNonZero(mask)
            if nonzero is None:
                continue
            xs, ys = nonzero.T
            mask = mask[max(0, ys.min() - 3):min(mask.shape[0], ys.max() + 4), max(0, xs.min() - 3):min(mask.shape[1], xs.max() + 4)]
            prepared = cv2.copyMakeBorder(255 - mask, BADGE_LABEL_PADDING, BADGE_LABEL_PADDING, BADGE_LABEL_PADDING, BADGE_LABEL_PADDING, cv2.BORDER_CONSTANT, value=255)
        else:
            prepared = enlarged
        mode_readings = []
        for psm in psms:
            try:
                data = pytesseract.image_to_data(
                    prepared,
                    config=f"--psm {psm} -c tessedit_char_whitelist=IVXivx",
                    output_type=Output.DICT,
                )
            except pytesseract.TesseractNotFoundError as error:
                raise ArmyTrainingScannerError("Tesseract OCR was not found.") from error
            for token, confidence in zip(data["text"], data["conf"]):
                token = token.strip().upper()
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    continue
                if token in ROMAN_LEVELS and confidence >= BADGE_LABEL_OCR_MIN_CONFIDENCE:
                    mode_readings.append((token, confidence))
        if len(mode_readings) == len(psms) and mode_readings[0][0] == mode_readings[1][0]:
            readings.append((mode_readings[0][0], min(mode_readings[0][1], mode_readings[1][1])))

    if not readings or len({label for label, _ in readings}) != 1:
        return None
    label, confidence = max(readings, key=lambda reading: reading[1])
    return ROMAN_LEVELS[label], confidence


def read_slot_selector_levels(image, slot):
    """Read only the last visible level label in one slot."""
    selector = slot_crop(image, slot, "unit_troop_level")
    badges = detect_selector_badges(selector)
    if not badges:
        return SelectorLevelReading("unknown", "no_level_badges_found", (), None)
    largest_index = max(range(len(badges)), key=lambda index: badges[index][2])
    highest = badges[largest_index]
    other_radii = [badge[2] for index, badge in enumerate(badges) if index != largest_index]
    if other_radii and highest[2] - max(other_radii) < BADGE_RADIUS_MIN_MARGIN:
        return SelectorLevelReading("unknown", "largest_badge_not_distinct", badges, highest)
    if largest_index != len(badges) - 1:
        return SelectorLevelReading("unknown", "largest_badge_not_last_level", badges, highest)
    highest_reading = _read_badge_label(selector, highest)
    if highest_reading is None:
        return SelectorLevelReading("unknown", "highest_badge_label_uncertain", badges, highest)
    if highest_reading[0] <= 2:
        return SelectorLevelReading(
            "unsupported",
            "local_level_may_map_to_global_viii_or_ix",
            badges,
            highest,
            highest_visible_level=highest_reading[0],
            confidence=highest_reading[1],
        )
    one_below = badges[-2] if len(badges) >= 2 else None
    one_below_level = None
    if one_below is not None:
        distance = highest[1] - one_below[1]
        if ADJACENT_ROW_MIN_DISTANCE <= distance <= ADJACENT_ROW_MAX_DISTANCE:
            one_below_level = highest_reading[0] - 1
    return SelectorLevelReading(
        "candidate",
        "highest_visible_badge_label_read",
        badges,
        highest,
        highest_visible_level=highest_reading[0],
        one_below_visible_level=one_below_level,
        confidence=highest_reading[1],
    )


def read_layout_selector_levels(image, slots):
    """Read each slot's maximum visible level and identify slots at global max and max-1."""
    readings = tuple(read_slot_selector_levels(image, slot) for slot in slots)
    if not readings or any(reading.status != "candidate" for reading in readings):
        return LayoutLevelReading("unknown", "one_or_more_slot_levels_uncertain", None, None, (), (), readings)
    global_max = max(reading.highest_visible_level for reading in readings)
    return LayoutLevelReading(
        "candidate",
        "slot_maxima_read",
        global_max,
        global_max - 1 if global_max > 1 else None,
        tuple(index for index, reading in enumerate(readings) if reading.highest_visible_level == global_max),
        tuple(index for index, reading in enumerate(readings) if reading.one_below_visible_level == global_max - 1),
        readings,
    )
