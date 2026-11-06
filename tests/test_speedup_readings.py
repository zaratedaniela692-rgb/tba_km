import pytest

from speedup_readings import (
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    parse_duration,
    parse_quantity,
    parse_remaining_time,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("13 d. : 7 g.", 13 * SECONDS_PER_DAY + 7 * SECONDS_PER_HOUR),
        ("13d:7g", 13 * SECONDS_PER_DAY + 7 * SECONDS_PER_HOUR),
        ("6 d. 1 g.", 6 * SECONDS_PER_DAY + SECONDS_PER_HOUR),
        ("7 g.", 7 * SECONDS_PER_HOUR),
        ("2 d.", 2 * SECONDS_PER_DAY),
    ],
)
def test_parse_remaining_time(raw, expected):
    result = parse_remaining_time(raw, confidence=92)

    assert result.value == expected
    assert result.status == "ok"


@pytest.mark.parametrize("raw", ["", "13 d. :", "13 d. : 24 g.", "13 days", "? d. : 7 g."])
def test_parse_remaining_time_fails_closed(raw):
    result = parse_remaining_time(raw, confidence=92)

    assert result.value is None
    assert result.status != "ok"


def test_parse_remaining_time_rejects_low_confidence():
    result = parse_remaining_time("13 d. : 7 g.", confidence=69.9)

    assert result.value is None
    assert result.status == "low_confidence"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1m.", SECONDS_PER_MINUTE),
        ("15m", 15 * SECONDS_PER_MINUTE),
        ("1g.", SECONDS_PER_HOUR),
        ("8g.", 8 * SECONDS_PER_HOUR),
        ("15h", 15 * SECONDS_PER_HOUR),
        ("1d.", SECONDS_PER_DAY),
        ("30d", 30 * SECONDS_PER_DAY),
    ],
)
def test_parse_duration(raw, expected):
    result = parse_duration(raw, confidence=90)

    assert result.value == expected
    assert result.status == "ok"


@pytest.mark.parametrize("raw", ["", "0d", "two days", "7x", "1.5h"])
def test_parse_duration_fails_closed(raw):
    result = parse_duration(raw, confidence=90)

    assert result.value is None
    assert result.status != "ok"


@pytest.mark.parametrize(("raw", "expected"), [("151", 151), ("4,797", 4797), ("5.186", 5186), ("31 310", 31310)])
def test_parse_quantity(raw, expected):
    result = parse_quantity(raw, confidence=95)

    assert result.value == expected
    assert result.status == "ok"


@pytest.mark.parametrize("raw", ["", "1,5", "12,34", "-1", "1.2.3"])
def test_parse_quantity_fails_closed(raw):
    result = parse_quantity(raw, confidence=95)

    assert result.value is None
    assert result.status == "unrecognized_quantity"


def test_quantity_never_defaults_to_zero_on_low_confidence():
    result = parse_quantity("244", confidence=20)

    assert result.value is None
    assert result.status == "low_confidence"