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
