from pathlib import Path

import cv2
import numpy as np
import pytest

import speedup_reader
from speedup_reader import read_remaining_time

SHOTS = Path(__file__).resolve().parents[1] / "screenshots" / "speedup_module"
DAY, HOUR = 86400, 3600


def _read(name):
    return read_remaining_time(cv2.imread(str(SHOTS / f"{name}.png")))


@pytest.mark.parametrize(
    "name, seconds",
    (
        ("speedup_view", 13 * DAY + 7 * HOUR),
        ("speedup_view2", 13 * DAY + 4 * HOUR),
        ("speedup_view3", 13 * DAY + 1 * HOUR),
        ("after_click_7days_speedup", 6 * DAY + 1 * HOUR),
    ),
)
def test_timer_is_read_from_each_fixture(name, seconds):
    reading = _read(name)

    assert reading.status == "ok"
    assert reading.value == seconds


def test_live_run_timer_with_previously_unverified_digits_is_read():
    image = cv2.imread(str(Path(__file__).resolve().parents[1] / "tests" / "data" / "speedup" / "timer_5d20h.png"))

    reading = read_remaining_time(image)

    assert reading.status == "ok"
    assert reading.raw == "5d.:20g."
    assert reading.value == 5 * DAY + 20 * HOUR
    assert reading.confidence == 100.0


def test_minute_only_timer_uses_consensus_ocr_fallback(monkeypatch):
    image = cv2.imread(str(SHOTS / "speedup_view.png"))
    monkeypatch.setattr(speedup_reader, "_split_label", lambda _components: None)
    answers = iter(("42m", "42m", "42m", "42m"))
    monkeypatch.setattr(speedup_reader.pytesseract, "image_to_string", lambda *_args, **_kwargs: next(answers))

    reading = read_remaining_time(image)

    assert reading.status == "ok"
    assert reading.value == 42 * 60
    assert reading.raw == "42m"


def test_minute_only_timer_ocr_disagreement_remains_unknown(monkeypatch):
    image = cv2.imread(str(SHOTS / "speedup_view.png"))
    monkeypatch.setattr(speedup_reader, "_split_label", lambda _components: None)
    answers = iter(("42m", "42m", "41m", "42m"))
    monkeypatch.setattr(speedup_reader.pytesseract, "image_to_string", lambda *_args, **_kwargs: next(answers))

    reading = read_remaining_time(image)

    assert reading.value is None
    assert reading.status == "minute_ocr_disagreement"


@pytest.mark.parametrize(
    ("first", "first_unit", "second", "second_unit", "expected"),
    [
        ("14", "g", "56", "m", 14 * HOUR + 56 * 60),
        ("30", "m", "05", "s", 30 * 60 + 5),
    ],
)
def test_segmented_timer_uses_recognized_units(monkeypatch, first, first_unit, second, second_unit, expected):
    image = cv2.imread(str(SHOTS / "speedup_view.png"))
    first_digits, first_marker = [(1, 1, 1, 10)], (10, 1, 1, 10)
    second_digits, second_marker = [(20, 1, 1, 10)], (30, 1, 1, 10)
    monkeypatch.setattr(
        speedup_reader,
        "_split_label",
        lambda _components: (first_digits, first_marker, second_digits, second_marker),
    )
    monkeypatch.setattr(
        speedup_reader,
        "_read_number",
        lambda _gray, digits: first if digits is first_digits else second,
    )
    monkeypatch.setattr(
        speedup_reader,
        "_read_unit",
        lambda _gray, marker: first_unit if marker is first_marker else second_unit,
    )

    reading = read_remaining_time(image)

    assert reading.status == "ok"
    assert reading.value == expected


def test_unverified_digit_is_accepted_when_both_scales_agree(monkeypatch):
    monkeypatch.setattr(speedup_reader, "_read_digit", lambda *args: "8")

    number = speedup_reader._read_number(np.zeros((4, 4), dtype=np.uint8), [(0, 0, 1, 1)])

    assert number == "8"
    assert speedup_reader.VERIFIED_DIGITS == frozenset("13467")


def test_disagreement_for_an_unverified_digit_is_still_rejected(monkeypatch):
    answers = iter(("8", "3"))
    monkeypatch.setattr(speedup_reader, "_read_digit", lambda *args: next(answers))

    assert speedup_reader._read_number(np.zeros((4, 4), dtype=np.uint8), [(0, 0, 1, 1)]) is None


def test_disagreeing_scales_are_rejected(monkeypatch):
    answers = iter("1313131313")
    monkeypatch.setattr(speedup_reader, "_read_digit", lambda *args: next(answers, "7"))

    assert _read("speedup_view").value is None


def test_blank_region_is_an_unrecognized_layout():
    reading = read_remaining_time(np.zeros((1080, 1920, 3), dtype=np.uint8))

    assert reading.value is None
    assert reading.status == "layout_unrecognized"
