"""Pure parsers for speedup timer, duration, and inventory quantity OCR."""

import re
from dataclasses import dataclass

MIN_CONFIDENCE = 70.0
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 60 * SECONDS_PER_MINUTE
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR
SECONDS_PER_SECOND = 1

_TIME_TOKEN_PATTERN = re.compile(r"(?P<amount>\d+)\s*(?P<unit>min|[dghms])", re.IGNORECASE)
_TIME_SEPARATOR_PATTERN = re.compile(r"[\s:.]*")
_TIME_TRAILING_PATTERN = re.compile(r"[\s.]*")
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
    """Parse one to three ordered timer units, such as ``13d 7g`` or ``30m 05s``."""
    raw = raw_text if isinstance(raw_text, str) else ""
    if not _confidence_is_valid(confidence, minimum_confidence):
        return ParsedReading(raw, None, confidence, "low_confidence" if confidence is not None else "unreadable")

    tokens = []
    position = 0
    for match in _TIME_TOKEN_PATTERN.finditer(raw):
        separator = raw[position:match.start()]
        if (not tokens and separator.strip()) or (tokens and _TIME_SEPARATOR_PATTERN.fullmatch(separator) is None):
            return ParsedReading(raw, None, confidence, "unrecognized_time")
        unit = match.group("unit").lower()
        rank = {"d": 4, "g": 3, "h": 3, "m": 2, "min": 2, "s": 1}[unit]
        tokens.append((int(match.group("amount")), unit, rank))
        position = match.end()

    if not tokens or len(tokens) > 3 or _TIME_TRAILING_PATTERN.fullmatch(raw[position:]) is None:
        return ParsedReading(raw, None, confidence, "unrecognized_time")

    ranks = [rank for _, _, rank in tokens]
    if any(left <= right for left, right in zip(ranks, ranks[1:])):
        return ParsedReading(raw, None, confidence, "unrecognized_time")

    multipliers = {4: SECONDS_PER_DAY, 3: SECONDS_PER_HOUR, 2: SECONDS_PER_MINUTE, 1: SECONDS_PER_SECOND}
    total_seconds = 0
    for amount, unit, rank in tokens:
        if rank == 3 and amount > 23:
            return ParsedReading(raw, None, confidence, "hours_out_of_range")
        if rank in (2, 1) and amount > 59:
            status = "minutes_out_of_range" if rank == 2 else "seconds_out_of_range"
            return ParsedReading(raw, None, confidence, status)
        total_seconds += amount * multipliers[rank]

    return ParsedReading(raw, total_seconds, float(confidence), "ok")


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