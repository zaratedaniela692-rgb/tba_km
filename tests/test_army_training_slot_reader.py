from pathlib import Path

import pytest

from army_training_slot_reader import read_slot_readings
from army_training_slots import find_slots
from army_training_scanner import _read_image

SCREENSHOTS = Path(__file__).resolve().parents[1] / "screenshots" / "army_training"
ACTIVE = SCREENSHOTS / "pelny.png"
EMPTY = SCREENSHOTS / "pelny_army_training_empty_queue.png"


def _readings(path):
    image = _read_image(path)
    return [read_slot_readings(image, slot) for slot in find_slots(path).slots]


@pytest.fixture(scope="module")
def active():
    return _readings(ACTIVE)


@pytest.fixture(scope="module")
def empty():
    return _readings(EMPTY)


def test_each_slot_keeps_its_own_queue_limit_on_the_active_screen(active):
    readings = active

    assert [r.queue_limit.value for r in readings] == [31310, 31310, 15655]
    assert all(r.queue_limit.reliable(70) for r in readings)


def test_each_slot_keeps_its_own_queue_limit_on_the_empty_queue_screen(empty):
    readings = empty

    assert [r.queue_limit.value for r in readings] == [1565, 31310, 31310]
    assert all(r.queue_limit.reliable(70) for r in readings)


def test_empty_queue_city_counts_and_silver_cost_are_read_per_slot(empty):
    readings = empty

    assert [r.city_count.value for r in readings] == [1861, 13069, 14765]
    assert all(r.city_count.reliable(70) for r in readings)
    assert {r.silver_cost.value for r in readings} == {12_600_000}
    assert all(r.silver_cost.reliable(70) for r in readings)


def test_active_screen_silver_cost_is_read_per_slot(active):
    readings = active

    assert {r.silver_cost.value for r in readings} == {9_290_000}
    assert all(r.silver_cost.reliable(70) for r in readings)


def test_active_screen_city_counts_are_read_per_slot(active):
    assert [r.city_count.value for r in active] == [0, 0, 0]
    assert all(r.city_count.reliable(70) for r in active)
