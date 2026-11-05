from pathlib import Path

import cv2
import numpy as np
import pytest

from army_training_scanner import _load_regions, _read_image
from army_training_slots import (
    STATUS_AMBIGUOUS,
    STATUS_NONE,
    STATUS_OK,
    find_slots,
    locate_slots,
    slot_crop,
)
from ui_variants import resolve_variant

SCREENSHOTS = Path(__file__).resolve().parents[1] / "screenshots" / "army_training"
ACTIVE = SCREENSHOTS / "pelny.png"
EMPTY = SCREENSHOTS / "pelny_army_training_empty_queue.png"


def _locate(image):
    variant = resolve_variant()
    regions = _load_regions(variant["regions"])["army_training"]
    return locate_slots(image, regions, variant)


@pytest.mark.parametrize("path, expected_dy", [(ACTIVE, 0), (EMPTY, -1)])
def test_finds_three_slots_left_to_right(path, expected_dy):
    layout = find_slots(path)

    assert layout.status == STATUS_OK
    assert [slot.index for slot in layout.slots] == [0, 1, 2]
    assert [(slot.row, slot.column) for slot in layout.slots] == [(0, 0), (0, 1), (0, 2)]
    assert [slot.dx for slot in layout.slots] == [0, 261, 522]
    assert {slot.dy for slot in layout.slots} == {expected_dy}
    assert all(slot.anchor_score >= 0.99 and slot.check_score >= 0.99 for slot in layout.slots)


def test_slot_regions_are_translated_with_the_slot():
    first, second, _ = find_slots(ACTIVE).slots

    for name, region in first.regions.items():
        assert second.regions[name]["x"] == region["x"] + 261
        assert second.regions[name]["y"] == region["y"]
    assert "current_trainin_army" not in first.regions


@pytest.mark.parametrize("path", [ACTIVE, EMPTY])
def test_every_slot_can_be_cropped_for_reading(path):
    image = _read_image(path)
    layout = _locate(image)
    train_template = cv2.imread(str(Path(__file__).resolve().parents[1] / "templates" / "army_training" / "unit_troop_train_button.png"))

    assert layout.status == STATUS_OK
    for slot in layout.slots:
        crop = slot_crop(image, slot, "unit_troop_train_button")
        assert crop.shape == train_template.shape
        assert cv2.matchTemplate(crop, train_template, cv2.TM_CCOEFF_NORMED)[0, 0] >= 0.99


def test_unknown_slot_region_is_rejected():
    image = _read_image(ACTIVE)
    slot = _locate(image).slots[0]

    with pytest.raises(ValueError):
        slot_crop(image, slot, "current_trainin_army")


def test_second_row_after_scrolling_is_ordered_top_left_to_bottom_right():
    image = _read_image(ACTIVE)
    image[840:1080, :] = image[540:780, :].copy()

    layout = _locate(image)

    assert layout.status == STATUS_OK
    assert [(slot.row, slot.column) for slot in layout.slots] == [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]
    assert [slot.index for slot in layout.slots] == list(range(6))
    assert {slot.dy for slot in layout.slots[3:]} == {300}
    assert [slot.dx for slot in layout.slots[3:]] == [0, 261, 522]


def test_fourth_slot_in_the_first_row_is_found():
    image = _read_image(ACTIVE)
    image[:, 1429:1691] = image[:, 1168:1430].copy()

    layout = _locate(image)

    assert layout.status == STATUS_OK
    assert [slot.dx for slot in layout.slots] == [0, 261, 522, 783]


def test_blank_image_has_no_slots():
    layout = _locate(np.zeros((1080, 1920, 3), dtype=np.uint8))

    assert layout.status == STATUS_NONE
    assert layout.slots == ()


def test_missing_middle_slot_is_ambiguous():
    image = _read_image(ACTIVE)
    image[700:760, 1020:1160] = 0

    layout = _locate(image)

    assert layout.status == STATUS_AMBIGUOUS
    assert layout.slots == ()
    assert len(layout.anchors) == 2


def test_horizontally_displaced_slot_is_ambiguous():
    image = _read_image(ACTIVE)
    image[:, 1176:1440] = image[:, 1168:1432].copy()

    assert _locate(image).status == STATUS_AMBIGUOUS


def test_vertically_displaced_slot_is_ambiguous():
    image = _read_image(ACTIVE)
    image[706:760, 1290:1420] = image[700:754, 1290:1420].copy()

    assert _locate(image).status == STATUS_AMBIGUOUS


def test_unconfirmed_slider_is_ambiguous():
    image = _read_image(ACTIVE)
    image[640:672, 1100:1160] = 0

    layout = _locate(image)

    assert layout.status == STATUS_AMBIGUOUS
    assert layout.slots == ()
