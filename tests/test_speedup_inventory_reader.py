import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from speedup_inventory_reader import combine_checkpoint_readings, read_checkpoint_viewport

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "data" / "speedup"
MAP = json.loads((ROOT / "speedup_button_map.json").read_text(encoding="utf-8"))
TEMPLATE = cv2.imread(str(ROOT / "templates" / "speedup" / "speedup_use_button.png"))
QUANTITY_REGION = {"x": 755, "y": 446, "w": 42, "h": 22}
USE_REGION = {"x": 1050, "y": 445, "w": 145, "h": 27}
EXPECTED = {
    3: {"15m": 4833, "1h": 5219, "3h": 3309, "8h": 410},
    11: {"15h": 593, "1d": 475, "3d": 492},
    16: {"3d": 492, "7d": 233, "30d": 1},
}


def _read(step, ocr_fn=None):
    checkpoint = next(entry for entry in MAP["checkpoints"] if entry["scroll_count"] == step)
    image = cv2.imread(str(FIXTURES / f"checkpoint_{step:03d}.png"))
    return read_checkpoint_viewport(
        image, checkpoint, TEMPLATE, QUANTITY_REGION, USE_REGION, ocr_fn=ocr_fn,
    )


@pytest.mark.parametrize("step", (3, 11, 16))
def test_reads_all_owned_quantities_at_each_checkpoint(step):
    reading = _read(step)

    assert reading.status == "complete"
    assert {item.duration_label: item.quantity.value for item in reading.items} == EXPECTED[step]
    assert all(item.quantity.confidence == 100.0 for item in reading.items)


def test_small_uniform_viewport_shift_uses_live_button_positions_for_ocr_and_clicks():
    checkpoint = next(entry for entry in MAP["checkpoints"] if entry["scroll_count"] == 3)
    image = cv2.imread(str(FIXTURES / "checkpoint_003.png"))
    shifted = cv2.warpAffine(
        image,
        np.float32(((1, 0, 2), (0, 1, 4))),
        (image.shape[1], image.shape[0]),
        borderMode=cv2.BORDER_REPLICATE,
    )

    reading = read_checkpoint_viewport(
        shifted, checkpoint, TEMPLATE, QUANTITY_REGION, USE_REGION,
    )

    assert reading.status == "complete"
    assert {item.duration_label: item.quantity.value for item in reading.items} == EXPECTED[3]
    assert reading.items[0].button_rectangle["x"] == checkpoint["buttons"][0]["rectangle"]["x"] + 2
    assert reading.items[0].button_rectangle["y"] == checkpoint["buttons"][0]["rectangle"]["y"] + 4
    assert reading.items[0].button_center["x"] == checkpoint["buttons"][0]["center"]["x"] + 2
    assert reading.items[0].button_center["y"] == checkpoint["buttons"][0]["center"]["y"] + 4


def test_large_uniform_checkpoint_16_shift_uses_live_button_positions():
    checkpoint = next(entry for entry in MAP["checkpoints"] if entry["scroll_count"] == 16)
    image = cv2.imread(str(FIXTURES / "checkpoint_016.png"))
    shifted = cv2.warpAffine(
        image,
        np.float32(((1, 0, 12), (0, 1, 9))),
        (image.shape[1], image.shape[0]),
        borderMode=cv2.BORDER_REPLICATE,
    )

    reading = read_checkpoint_viewport(
        shifted, checkpoint, TEMPLATE, QUANTITY_REGION, USE_REGION,
    )

    assert reading.status == "complete"
    assert {item.duration_label: item.quantity.value for item in reading.items} == EXPECTED[16]
    assert reading.items[0].button_center["x"] == checkpoint["buttons"][0]["center"]["x"] + 12
    assert reading.items[0].button_center["y"] == checkpoint["buttons"][0]["center"]["y"] + 9
    assert reading.match_diagnostics[0]["offset"] == {"x": 12, "y": 9}
    assert reading.match_diagnostics[0]["confidence"] >= MAP["minimum_match_score"]


def test_target_duration_read_ocr_processes_only_one_quantity():
    checkpoint = next(entry for entry in MAP["checkpoints"] if entry["scroll_count"] == 3)
    image = cv2.imread(str(FIXTURES / "checkpoint_003.png"))
    ocr_calls = []

    reading = read_checkpoint_viewport(
        image, checkpoint, TEMPLATE, QUANTITY_REGION, USE_REGION,
        ocr_fn=lambda crop, scale, psm: ocr_calls.append((crop.shape, scale, psm)) or "5285",
        duration_seconds=3600,
    )

    assert reading.status == "complete"
    assert [(item.duration_label, item.quantity.value) for item in reading.items] == [("1h", 5285)]
    assert len(ocr_calls) == 2
    assert [call[1] for call in ocr_calls] == [4, 6]


def test_combines_checkpoints_and_deduplicates_repeated_three_day_item():
    combined = combine_checkpoint_readings(tuple(_read(step) for step in (3, 11, 16)))

    assert combined.status == "complete"
    assert combined.inventory == {
        900: 4833,
        3600: 5219,
        10800: 3309,
        28800: 410,
        54000: 593,
        86400: 475,
        259200: 492,
        604800: 233,
        2592000: 1,
    }
    assert len(combined.items) == 9


def test_repeated_duration_conflict_blocks_complete_inventory():
    readings = [_read(11), _read(16)]
    changed = readings[1].items[0]
    readings[1] = type(readings[1])(
        "complete", (type(changed)(changed.duration_label, changed.duration_seconds,
        type(changed.quantity)(changed.quantity.raw, 491, 100.0, "ok"), changed.scroll_count,
        changed.button_rectangle, changed.button_center), *readings[1].items[1:]),
        checkpoint_steps=(16,),
    )

    combined = combine_checkpoint_readings(readings)

    assert combined.status == "incomplete"
    assert combined.inventory is None
    assert combined.reason == "duplicate_quantity_conflict:3d"


def test_disagreeing_ocr_passes_are_not_accepted_as_a_quantity():
    answers = iter(("233", "234"))
    reading = _read(16, lambda *_: next(answers))

    assert reading.status == "incomplete"
    assert reading.items == ()
    assert reading.reason == "quantity_unreadable:3d:ocr_disagreement"


def test_missing_or_misplaced_button_blocks_checkpoint_read():
    checkpoint = dict(next(entry for entry in MAP["checkpoints"] if entry["scroll_count"] == 16))
    checkpoint["buttons"] = [dict(button) for button in checkpoint["buttons"]]
    checkpoint["buttons"][0]["rectangle"] = dict(checkpoint["buttons"][0]["rectangle"], y=55)
    image = cv2.imread(str(FIXTURES / "checkpoint_016.png"))

    reading = read_checkpoint_viewport(image, checkpoint, TEMPLATE, QUANTITY_REGION, USE_REGION, ocr_fn=lambda *_: "492")

    assert reading.status == "incomplete"
    assert reading.reason == "use_button_offsets_inconsistent"
    assert reading.match_diagnostics[0]["offset"] == {"x": 0, "y": -5}


def test_blank_frame_is_incomplete_not_empty_inventory():
    reading = read_checkpoint_viewport(
        np.zeros((418, 562, 3), dtype=np.uint8), MAP["checkpoints"][0], TEMPLATE,
        QUANTITY_REGION, USE_REGION, ocr_fn=lambda *_: "0",
    )

    assert reading.status == "incomplete"
    assert reading.inventory is None
    assert reading.reason == "use_button_count_mismatch"
    assert reading.match_diagnostics[-1]["expected_count"] == 4
    assert reading.match_diagnostics[-1]["detected_count"] == 0