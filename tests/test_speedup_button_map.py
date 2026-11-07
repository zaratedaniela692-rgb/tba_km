from pathlib import Path
import json

import cv2
import pytest

from speedup_button_map import ButtonMapError, build_button_map

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "data" / "speedup"
TEMPLATE = cv2.imread(str(ROOT / "templates" / "speedup" / "speedup_use_button.png"))
VIEWPORT = {"x": 0, "y": 0, "w": 562, "h": 418}


@pytest.fixture(scope="module")
def checkpoint_images():
    images = {}
    for step in (3, 11, 16):
        path = FIXTURES / "checkpoint_{:03d}.png".format(step)
        image = cv2.imread(str(path))
        assert image is not None, "Missing checkpoint fixture: {}".format(path)
        images[step] = image
    return images


def test_maps_only_complete_use_buttons_at_each_checkpoint(checkpoint_images):
    result = build_button_map(checkpoint_images, VIEWPORT, TEMPLATE, "template.png")

    assert [
        [button["duration_label"] for button in checkpoint["buttons"]]
        for checkpoint in result["checkpoints"]
    ] == [
        ["15m", "1h", "3h", "8h"],
        ["15h", "1d", "3d"],
        ["3d", "7d", "30d"],
    ]
    assert result["coordinate_space"] == "speedup_inventory_viewport"
    assert result["preferred_scroll_count_by_duration"] == {
        "15m": 3,
        "1h": 3,
        "3h": 3,
        "8h": 3,
        "15h": 11,
        "1d": 11,
        "3d": 11,
        "7d": 16,
        "30d": 16,
    }


def test_positions_are_viewport_relative_and_repeat_owned_durations(checkpoint_images):
    result = build_button_map(checkpoint_images, VIEWPORT, TEMPLATE, "template.png")
    by_step = {checkpoint["scroll_count"]: checkpoint["buttons"] for checkpoint in result["checkpoints"]}

    assert by_step[3][0]["rectangle"] == {"x": 372, "y": 30, "width": 145, "height": 27}
    assert by_step[3][0]["center"] == {"x": 444, "y": 43}
    assert by_step[11][-1]["duration_label"] == "3d"
    assert by_step[16][0]["duration_label"] == "3d"
    assert [button["duration_label"] for button in by_step[16]] == ["3d", "7d", "30d"]
    assert all(button["match_confidence"] >= 0.95 for buttons in by_step.values() for button in buttons)


def test_shop_buy_and_clipped_step_eleven_button_are_not_mapped(checkpoint_images):
    result = build_button_map(checkpoint_images, VIEWPORT, TEMPLATE, "template.png")
    by_step = {checkpoint["scroll_count"]: checkpoint["buttons"] for checkpoint in result["checkpoints"]}

    assert "7d" not in [button["duration_label"] for button in by_step[11]]
    assert sum(button["duration_label"] == "30d" for button in by_step[16]) == 1


def test_unexpected_detection_count_blocks_the_map(checkpoint_images):
    images = dict(checkpoint_images)
    images[11] = cv2.imread(str(FIXTURES / "checkpoint_003.png"))

    with pytest.raises(ButtonMapError, match="checkpoint 11: expected 3 complete Use buttons"):
        build_button_map(images, VIEWPORT, TEMPLATE, "template.png")