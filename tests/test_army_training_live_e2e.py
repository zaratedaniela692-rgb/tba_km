from pathlib import Path

import cv2
import numpy as np
import pytest

import army_training_live_e2e as live
from army_training_levels import read_slot_selector_levels
from army_training_scanner import _read_image
from army_training_slots import find_slots

ROOT = Path(__file__).resolve().parents[1]
EMPTY = ROOT / "screenshots" / "army_training" / "pelny_army_training_empty_queue.png"


def _live_fixtures(monkeypatch, post_status="active"):
    image = _read_image(EMPTY)
    variant = live.resolve_variant()
    regions = live._load_regions(variant["regions"])
    layout = find_slots(EMPTY)
    actual_level = read_slot_selector_levels(image, layout.slots[1])
    clicked = []
    captured = []

    monkeypatch.setattr(live, "capture_primary_monitor", lambda: (image.copy(), (0, 0)))
    monkeypatch.setattr(live, "_read_current_training_state", lambda frame, selected_variant: {"status": "idle"})
    monkeypatch.setattr(live, "_slot_position_is_same", lambda frame, selected_variant, expected: (True, layout.slots[1]))
    monkeypatch.setattr(live, "_verify_selected_level", lambda frame, slot, requested, y: True)
    monkeypatch.setattr(live, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(live, "_build_selected_slot_plan", lambda frame, selected_variant, slot: {
        "training": {"status": "idle"}, "readings": {}, "resources": {},
        "target_count": 62620, "completion_count": 50096,
        "planned_quantity": 31310, "blockers": [],
    })

    def click(point, origin):
        clicked.append((point, origin))

    def capture():
        captured.append(True)
        state = post_status if len(clicked) >= 2 else "idle"
        monkeypatch.setattr(live, "_read_current_training_state", lambda frame, selected_variant: {"status": state})
        return image.copy(), (0, 0)

    monkeypatch.setattr(live, "capture_primary_monitor", capture)
    return clicked, captured, image, layout, click


def test_preview_is_for_second_visible_slot_and_does_not_click(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)

    result = live.run_one_shot(execute=False, click_fn=click)

    assert result["slot_frame_index"] == 1
    assert result["requested_level"] == 6
    assert result["status"] == "PREVIEW_ONLY"
    assert clicked == []
    assert result["queue_modified"] is False


def test_execute_requires_exact_confirmation(monkeypatch):
    _, _, _, _, click = _live_fixtures(monkeypatch)

    with pytest.raises(live.LiveTrainingError, match="confirmation phrase"):
        live.run_one_shot(execute=True, confirmation="yes", click_fn=click)


def test_selected_lower_level_is_verified_by_enlarged_second_last_badge(monkeypatch):
    image = _read_image(EMPTY)
    slot = find_slots(EMPTY).slots[1]
    badges = ((10.0, 7.0, 9.0), (10.0, 33.0, 12.0), (10.0, 58.0, 9.0))
    monkeypatch.setattr("army_training_live_e2e.detect_selector_badges", lambda selector: badges)
    monkeypatch.setattr("army_training_live_e2e._read_badge_label", lambda selector, badge: (6, 90.0))

    assert live._verify_selected_level(image, slot, 6, 33.0)
    assert not live._verify_selected_level(image, slot, 7, 33.0)


def test_non_1920_capture_is_rejected_before_actions(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)
    monkeypatch.setattr(live, "capture_primary_monitor", lambda: (np.zeros((720, 1280, 3), dtype=np.uint8), (0, 0)))

    with pytest.raises(live.LiveTrainingError, match="Expected primary-monitor frame"):
        live.run_one_shot(click_fn=click)
    assert clicked == []


def test_preflight_block_stops_after_level_selection_without_train(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)
    monkeypatch.setattr(live, "_build_selected_slot_plan", lambda frame, selected_variant, slot: {
        "training": {"status": "idle"}, "readings": {}, "resources": {},
        "target_count": 62620, "completion_count": 50096,
        "planned_quantity": 31310, "blockers": ["silver_insufficient_or_uncertain"],
    })

    result = live.run_one_shot(execute=True, confirmation=live.CONFIRMATION_PHRASE, click_fn=click)

    assert result["status"] == "BLOCKED_AFTER_LEVEL_CLICK"
    assert result["actions_executed"] is True
    assert result["level_click_issued"] is True
    assert "train_click_issued" not in result
    assert len(clicked) == 1


def test_capture_failure_after_level_click_reports_action_and_unknown(monkeypatch):
    clicked, captured, _, _, click = _live_fixtures(monkeypatch)

    def fail_after_selector_click():
        captured.append(True)
        if len(captured) == 2:
            raise OSError("capture device failed")
        image = _read_image(EMPTY)
        return image, (0, 0)

    monkeypatch.setattr(live, "capture_primary_monitor", fail_after_selector_click)

    result = live.run_one_shot(
        execute=True,
        confirmation=live.CONFIRMATION_PHRASE,
        click_fn=click,
        sleep_fn=lambda _: None,
    )

    assert result["status"] == "UNKNOWN_AFTER_LEVEL_CLICK"
    assert result["actions_executed"] is True
    assert result["level_click_issued"] is True
    assert result["blockers"][0].startswith("post_selection_check_failed_stop_without_retry")
    assert len(clicked) == 1


def test_one_train_click_and_active_confirmation(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)

    result = live.run_one_shot(execute=True, confirmation=live.CONFIRMATION_PHRASE, click_fn=click, sleep_fn=lambda _: None)

    assert result["status"] == "START_CONFIRMED"
    assert result["train_click_issued"] is True
    assert result["post_click_training_state"] == "active"
    assert result["queue_modified"] is True
    assert len(clicked) == 2


def test_train_click_exception_is_unknown_and_never_retried(monkeypatch):
    _, _, _, _, _ = _live_fixtures(monkeypatch)
    click_attempts = []

    def click(point, origin):
        click_attempts.append((point, origin))
        if len(click_attempts) == 2:
            raise OSError("click acknowledgement lost")

    result = live.run_one_shot(
        execute=True,
        confirmation=live.CONFIRMATION_PHRASE,
        click_fn=click,
        sleep_fn=lambda _: None,
    )

    assert result["status"] == "UNKNOWN_AFTER_TRAIN_CLICK_ATTEMPT"
    assert result["actions_executed"] is True
    assert result["train_click_attempted"] is True
    assert result["queue_modified"] == "unknown"
    assert result["blockers"][0].startswith("train_click_result_uncertain_do_not_retry")
    assert len(click_attempts) == 2


def test_uncertain_post_click_does_not_retry(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch, post_status="unknown")

    result = live.run_one_shot(execute=True, confirmation=live.CONFIRMATION_PHRASE, click_fn=click, sleep_fn=lambda _: None)

    assert result["status"] == "UNKNOWN_AFTER_CLICK"
    assert result["queue_modified"] == "unknown"
    assert result["blockers"] == ["train_click_not_visually_confirmed_do_not_retry"]
    assert len(clicked) == 2
