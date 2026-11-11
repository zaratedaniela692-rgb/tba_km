from pathlib import Path

import pytest

import army_training_inspector as inspector
from army_training_scanner import ArmyTrainingScannerError, _read_image

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    "guardsmen": ROOT / "screenshots" / "army_training" / "pelny.png",
    "specialists": ROOT / "screenshots" / "army_training" / "specialist_view.png",
}


@pytest.mark.parametrize("unit_type", ("guardsmen", "specialists"))
def test_inspector_confirms_fixture_category_and_reports_slots_without_actions(monkeypatch, unit_type):
    image = _read_image(FIXTURES[unit_type])
    monkeypatch.setattr(inspector, "_read_slot_report", lambda frame, slot: {
        "frame_index": slot.index, "selector_levels": {"status": "unknown"},
        "readings": {"status": "unknown"},
    })

    report = inspector.inspect_image(image, expected_unit_type=unit_type)

    assert report["status"] == "INSPECTED_READ_ONLY"
    assert report["category"]["unit_type"] == unit_type
    assert report["category"]["score"] == pytest.approx(1.0)
    assert report["slot_count"] == 3
    assert report["actions_executed"] is False
    assert report["queue_modified"] is False


def test_expected_category_mismatch_blocks_slot_report(monkeypatch):
    image = _read_image(FIXTURES["specialists"])
    slot_reports = []
    monkeypatch.setattr(inspector, "_read_slot_report", lambda frame, slot: slot_reports.append(slot))

    report = inspector.inspect_image(image, expected_unit_type="guardsmen")

    assert report["status"] == "BLOCKED_UNIT_TYPE_MISMATCH"
    assert report["category"]["unit_type"] == "specialists"
    assert slot_reports == []
    assert report["actions_executed"] is False


def test_ambiguous_category_stops_before_slot_detection(monkeypatch):
    image = _read_image(FIXTURES["specialists"])
    monkeypatch.setattr(inspector, "read_selected_category", lambda frame, variant: {
        "status": "ambiguous", "matches": ["guardsmen", "specialists"],
    })
    monkeypatch.setattr(inspector, "locate_slots", lambda *args: pytest.fail("slot detection must not run"))

    report = inspector.inspect_image(image)

    assert report["status"] == "BLOCKED_CATEGORY_RECOGNITION"
    assert report["actions_executed"] is False


def test_inspector_preserves_unknown_ocr_readings(monkeypatch):
    image = _read_image(FIXTURES["specialists"])
    def unavailable(*args):
        raise ArmyTrainingScannerError("Tesseract OCR was not found.")

    monkeypatch.setattr(inspector, "read_slot_selector_levels", unavailable)
    monkeypatch.setattr(inspector, "read_slot_readings", unavailable)

    report = inspector.inspect_image(image, expected_unit_type="specialists")

    assert report["status"] == "INSPECTED_READ_ONLY"
    assert all(slot["selector_levels"]["status"] == "unknown" for slot in report["slots"])
    assert all(slot["readings"]["status"] == "unknown" for slot in report["slots"])


def test_wrong_frame_size_is_blocked():
    import numpy as np

    report = inspector.inspect_image(np.zeros((720, 1280, 3), dtype=np.uint8))

    assert report["status"] == "BLOCKED_FRAME_SIZE"
    assert report["actions_executed"] is False