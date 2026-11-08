"""Pure parsers for speedup timer, duration, and inventory quantity OCR."""

import re
from dataclasses import dataclass

MIN_CONFIDENCE = 70.0
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 60 * SECONDS_PER_MINUTE
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR

_TIME_PATTERN = re.compile(
    r"^\s*(?:(?P<days>\d+)\s*d\s*\.?(?:\s*:?\s*"
    r"(?P<hours>\d+)\s*(?:g|h)\s*\.?)?(?:\s*:?\s*"
    r"(?P<minutes>\d+)\s*(?:min|m)\s*\.?)?|"
    r"(?P<hours_only>\d+)\s*(?:g|h)\s*\.?(?:\s*:?\s*"
    r"(?P<hours_minutes>\d+)\s*(?:min|m)\s*\.?)?|"
    r"(?P<minutes_only>\d+)\s*(?:min|m)\s*\.?)\s*$",
    re.IGNORECASE,
)
_DURATION_PATTERN = re.compile(r"^\s*(?P<amount>\d+)\s*(?P<unit>m|min|g|h|d)\s*\.?\s*$", re.IGNORECASE)
_QUANTITY_PATTERN = re.compile(r"^\s*\d+(?:[,. ]\d{3})*\s*$")


@dataclass(frozen=True)
class ParsedReading:
    raw: str
    value: int | None
    confidence: float | None
    status: str


def _confidence_is_valid(confidence, minimum_confidence):
    return (
        confidence is not None
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and minimum_confidence <= confidence <= 100
    )


def parse_remaining_time(raw_text, confidence=None, minimum_confidence=MIN_CONFIDENCE):
    """Parse day/hour timer text such as ``13 d. : 7 g.`` into seconds."""
    raw = raw_text if isinstance(raw_text, str) else ""
    if not _confidence_is_valid(confidence, minimum_confidence):
        return ParsedReading(raw, None, confidence, "low_confidence" if confidence is not None else "unreadable")

    match = _TIME_PATTERN.fullmatch(raw)
    if match is None:
        return ParsedReading(raw, None, confidence, "unrecognized_time")

    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or match.group("hours_only") or 0)
    minutes = int(match.group("minutes") or match.group("hours_minutes") or match.group("minutes_only") or 0)
    if hours > 23:
        return ParsedReading(raw, None, confidence, "hours_out_of_range")
    if minutes > 59:
        return ParsedReading(raw, None, confidence, "minutes_out_of_range")

    seconds = days * SECONDS_PER_DAY + hours * SECONDS_PER_HOUR + minutes * SECONDS_PER_MINUTE
    return ParsedReading(raw, seconds, float(confidence), "ok")


def parse_duration(raw_text, confidence=None, minimum_confidence=MIN_CONFIDENCE):
    """Parse an inventory label, accepting Polish ``g`` and English ``h`` for hours."""
    raw = raw_text if isinstance(raw_text, str) else ""
    if not _confidence_is_valid(confidence, minimum_confidence):
        return ParsedReading(raw, None, confidence, "low_confidence" if confidence is not None else "unreadable")

    match = _DURATION_PATTERN.fullmatch(raw)
    if match is None:
        return ParsedReading(raw, None, confidence, "unrecognized_duration")

    amount = int(match.group("amount"))
    unit = match.group("unit").lower()
    multiplier = {
        "m": SECONDS_PER_MINUTE,
        "min": SECONDS_PER_MINUTE,
        "g": SECONDS_PER_HOUR,
        "h": SECONDS_PER_HOUR,
        "d": SECONDS_PER_DAY,
    }[unit]
    if amount <= 0:
        return ParsedReading(raw, None, confidence, "duration_out_of_range")
    return ParsedReading(raw, amount * multiplier, float(confidence), "ok")


def parse_quantity(raw_text, confidence=None, minimum_confidence=MIN_CONFIDENCE):
    """Parse integer counts with optional three-digit grouping separators."""
    raw = raw_text if isinstance(raw_text, str) else ""
    if not _confidence_is_valid(confidence, minimum_confidence):
        return ParsedReading(raw, None, confidence, "low_confidence" if confidence is not None else "unreadable")
    if _QUANTITY_PATTERN.fullmatch(raw) is None:
        return ParsedReading(raw, None, confidence, "unrecognized_quantity")

    quantity = int(re.sub(r"[,. ]", "", raw.strip()))
    return ParsedReading(raw, quantity, float(confidence), "ok")