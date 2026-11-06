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


def test_unverified_digit_is_rejected_not_guessed(monkeypatch):
    monkeypatch.setattr(speedup_reader, "_read_digit", lambda *args: "8")

    reading = _read("speedup_view")

    assert reading.value is None
    assert reading.status == "digit_unverified"


def test_disagreeing_scales_are_rejected(monkeypatch):
    answers = iter("1313131313")
    monkeypatch.setattr(speedup_reader, "_read_digit", lambda *args: next(answers, "7"))

    assert _read("speedup_view").value is None


def test_blank_region_is_an_unrecognized_layout():
    reading = read_remaining_time(np.zeros((1080, 1920, 3), dtype=np.uint8))

    assert reading.value is None
    assert reading.status == "layout_unrecognized"
