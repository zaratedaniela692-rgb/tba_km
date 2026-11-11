from pathlib import Path

import numpy as np
import pytest

import army_training_levels
from army_training_levels import detect_selector_badges, read_layout_selector_levels, read_slot_selector_levels
from army_training_scanner import _read_image
from army_training_slots import find_slots, slot_crop

SCREENSHOTS = Path(__file__).resolve().parents[1] / "screenshots" / "army_training"
ACTIVE = SCREENSHOTS / "pelny.png"
EMPTY = SCREENSHOTS / "pelny_army_training_empty_queue.png"


@pytest.fixture(scope="module")
def active_layout_levels():
    image = _read_image(ACTIVE)
    return read_layout_selector_levels(image, find_slots(ACTIVE).slots)


@pytest.fixture(scope="module")
def empty_layout_levels():
    image = _read_image(EMPTY)
    return read_layout_selector_levels(image, find_slots(EMPTY).slots)


@pytest.mark.parametrize(
    "fixture_name, expected_counts, expected_maxima",
    [("active_layout_levels", [5, 5, 5], [5, 5, 5]), ("empty_layout_levels", [3, 2, 2], [7, 7, 7])],
)
def test_reads_highest_visible_level_per_slot(request, fixture_name, expected_counts, expected_maxima):
    layout = request.getfixturevalue(fixture_name)

    assert [len(reading.badge_centers) for reading in layout.slot_readings] == expected_counts
    assert all(reading.status == "candidate" for reading in layout.slot_readings)
    assert [reading.highest_visible_level for reading in layout.slot_readings] == expected_maxima
    assert all(reading.confidence >= 70 for reading in layout.slot_readings)
    assert all(reading.highest_badge == max(reading.badge_centers, key=lambda badge: badge[2]) for reading in layout.slot_readings)
    assert all(reading.uses_default_highest_assumption for reading in layout.slot_readings)


@pytest.mark.parametrize(
    "fixture_name, expected_global, expected_below, expected_indices",
    [("active_layout_levels", 5, 4, (0, 1, 2)), ("empty_layout_levels", 7, 6, (0, 1, 2))],
)
def test_layout_reports_global_max_and_one_below(request, fixture_name, expected_global, expected_below, expected_indices):
    layout = request.getfixturevalue(fixture_name)

    assert layout.status == "candidate"
    assert layout.global_highest_visible_level == expected_global
    assert layout.one_below_visible_level == expected_global - 1
    assert layout.highest_slot_indices == expected_indices
    assert layout.one_below_slot_indices == expected_indices
    assert [reading.one_below_visible_level for reading in layout.slot_readings] == [expected_below] * 3


def test_empty_selector_has_no_badge_candidates():
    assert detect_selector_badges(np.zeros((118, 21, 3), dtype=np.uint8)) == ()


def test_unreadable_selector_level_makes_layout_unknown():
    image = _read_image(ACTIVE)
    slot = find_slots(ACTIVE).slots[0]
    region = slot.regions["unit_troop_level"]
    x, y, width, height = (region[key] for key in ("x", "y", "w", "h"))
    image[y + 25:y + height, x:x + width] = 0

    reading = read_slot_selector_levels(image, slot)

    assert reading.status == "unknown"
    assert reading.highest_visible_level is None


def test_local_one_or_two_is_not_misreported_as_global_level(monkeypatch):
    image = _read_image(ACTIVE)
    slot = find_slots(ACTIVE).slots[0]
    monkeypatch.setattr("army_training_levels._read_badge_label", lambda selector, badge: (2, 95.0))

    reading = read_slot_selector_levels(image, slot)

    assert reading.status == "unsupported"
    assert reading.reason == "local_level_may_map_to_global_viii_or_ix"


def test_largest_badge_not_at_end_is_unknown(monkeypatch):
    image = _read_image(ACTIVE)
    slot = find_slots(ACTIVE).slots[0]
    badges = ((10.0, 7.0, 12.0), (10.0, 32.0, 9.0), (10.0, 57.0, 9.0))
    monkeypatch.setattr("army_training_levels.detect_selector_badges", lambda selector: badges)

    reading = read_slot_selector_levels(image, slot)

    assert reading.status == "unknown"
    assert reading.reason == "largest_badge_not_last_level"


def test_roman_label_consensus_uses_the_minimum_accepted_confidence(monkeypatch):
    outputs = iter((
        {"text": ["V"], "conf": ["91.0"]},
        {"text": ["v"], "conf": ["76.0"]},
    ))
    monkeypatch.setattr(army_training_levels.pytesseract, "image_to_data", lambda *args, **kwargs: next(outputs))

    reading = army_training_levels._read_consensus_roman_label(np.zeros((4, 4), dtype=np.uint8), (7, 10))

    assert reading == ("V", 76.0)


def test_roman_label_consensus_rejects_disagreement(monkeypatch):
    outputs = iter((
        {"text": ["V"], "conf": ["91.0"]},
        {"text": ["VII"], "conf": ["88.0"]},
    ))
    monkeypatch.setattr(army_training_levels.pytesseract, "image_to_data", lambda *args, **kwargs: next(outputs))

    reading = army_training_levels._read_consensus_roman_label(np.zeros((4, 4), dtype=np.uint8), (7, 10))

    assert reading is None
