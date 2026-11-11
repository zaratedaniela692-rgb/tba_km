from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import army_training_live_e2e as live
from army_training_scanner import _read_image
from army_training_slots import find_slots

ROOT = Path(__file__).resolve().parents[1]
EMPTY = ROOT / "screenshots" / "army_training" / "pelny_army_training_empty_queue.png"


def _live_fixtures(monkeypatch, post_status="active"):
    image = _read_image(EMPTY)
    variant = live.resolve_variant()
    regions = live._load_regions(variant["regions"])
    layout = find_slots(EMPTY)
    clicked = []
    captured = []

    monkeypatch.setattr(live, "capture_primary_monitor", lambda: (image.copy(), (0, 0)))
    monkeypatch.setattr(live, "observe_foreground_profile", lambda **kwargs: {
        "status": "routed", "client_id": "desktop", "profile_id": "player_12345",
    })
    monkeypatch.setattr(live, "_read_current_training_state", lambda frame, selected_variant: {"status": "idle"})
    monkeypatch.setattr(live, "_slot_position_is_same", lambda frame, selected_variant, expected: (True, layout.slots[0]))
    monkeypatch.setattr(live, "_select_requested_level", lambda frame, slot, requested_level: {
        "level": requested_level, "badge_index": 1, "local_x": 10, "local_y": 40,
        "screen_x": 656, "screen_y": 403, "badge_count": 3,
        "lowest_visible_level": 5, "highest_visible_level": 7, "selector_shape": (118, 21),
    })
    monkeypatch.setattr(live, "_requested_level_is_selected", lambda frame, slot, selection: True)
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


def test_preview_is_for_first_visible_slot_and_does_not_click(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)

    result = live.run_one_shot(execute=False, click_fn=click)

    assert result["slot_frame_index"] == 0
    assert result["requested_level"] == 6
    assert result["selection_confirmed"] is False
    assert result["status"] == "PREVIEW_ONLY"
    assert clicked == []
    assert result["queue_modified"] is False


def test_execute_requires_exact_confirmation(monkeypatch):
    _, _, _, _, click = _live_fixtures(monkeypatch)

    with pytest.raises(live.LiveTrainingError, match="confirmation phrase"):
        live.run_one_shot(execute=True, confirmation="yes", click_fn=click)


def test_preview_reports_navigation_required_without_sending_input(monkeypatch):
    clicked = []
    _, _, image, layout, click = _live_fixtures(monkeypatch)

    result = live.run_one_shot(
        execute=False,
        click_fn=click,
        ensure_screen_fn=lambda **kwargs: {
            "status": "NAVIGATION_REQUIRED", "actions_executed": False,
            "layout_status": "none", "layout_reason": "no Train button found",
        },
    )

    assert result["status"] == "NAVIGATION_REQUIRED"
    assert result["actions_executed"] is False
    assert result["queue_modified"] is False
    assert clicked == []


def test_live_one_shot_reports_navigation_side_effect_and_route(monkeypatch):
    clicked, _, image, layout, click = _live_fixtures(monkeypatch)
    navigation = {"status": "BARRACKS_OPENED", "actions_executed": True, "visible_slots": 3}

    result = live.run_one_shot(
        execute=True,
        confirmation=live.CONFIRMATION_PHRASE.format(level=6),
        click_fn=click,
        sleep_fn=lambda _: None,
        ensure_screen_fn=lambda **kwargs: {
            "status": "BARRACKS_READY", "actions_executed": True,
            "navigation": navigation, "frame": image.copy(), "origin": (0, 0), "layout": layout,
        },
    )

    assert result["status"] == "START_CONFIRMED"
    assert result["actions_executed"] is True
    assert result["route"]["profile_id"] == "player_12345"
    assert result["navigation"] == navigation
    assert len(clicked) == 2


def test_unresolved_foreground_route_blocks_navigation_and_training(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)
    navigation_calls = []
    monkeypatch.setattr(live, "observe_foreground_profile", lambda **kwargs: {
        "status": "blocked", "client_id": "desktop", "profile_id": None,
    })

    result = live.run_one_shot(
        execute=True,
        confirmation=live.CONFIRMATION_PHRASE.format(level=6),
        click_fn=click,
        ensure_screen_fn=lambda **kwargs: navigation_calls.append(kwargs),
    )

    assert result["status"] == "BLOCKED_ROUTE"
    assert result["actions_executed"] is False
    assert clicked == []
    assert navigation_calls == []


def test_non_1920_capture_is_rejected_before_actions(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)
    monkeypatch.setattr(live, "capture_primary_monitor", lambda: (np.zeros((720, 1280, 3), dtype=np.uint8), (0, 0)))

    result = live.run_one_shot(click_fn=click)
    assert result["status"] == "BLOCKED_INITIAL_CAPTURE"
    assert "Expected primary-monitor frame" in result["blockers"][0]
    assert clicked == []


def test_non_guardsmen_category_is_rejected_before_any_click(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)
    monkeypatch.setattr(live, "read_selected_category", lambda frame, variant: {
        "status": "confirmed", "unit_type": "specialists",
    })

    result = live.run_one_shot(execute=True, confirmation=live.CONFIRMATION_PHRASE.format(level=6), click_fn=click)

    assert result["status"] == "BLOCKED_CATEGORY_RECOGNITION"
    assert result["actions_executed"] is False

    assert clicked == []


def test_preflight_block_stops_after_level_selection_without_train(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)
    monkeypatch.setattr(live, "_build_selected_slot_plan", lambda frame, selected_variant, slot: {
        "training": {"status": "idle"}, "readings": {}, "resources": {},
        "target_count": 62620, "completion_count": 50096,
        "planned_quantity": 31310, "blockers": ["silver_insufficient_or_uncertain"],
    })

    result = live.run_one_shot(execute=True, confirmation=live.CONFIRMATION_PHRASE.format(level=6), click_fn=click)

    assert result["status"] == "BLOCKED_AFTER_LEVEL_CLICK"
    assert result["actions_executed"] is True
    assert result["level_click_issued"] is True
    assert "train_click_issued" not in result
    assert len(clicked) == 1


def test_confirmed_selection_still_requires_same_slot_and_fresh_preflight(monkeypatch):
    clicked, captured, _, _, click = _live_fixtures(monkeypatch)
    slot_checks = []

    def same_slot(frame, variant, expected):
        slot_checks.append(True)
        return True, find_slots(EMPTY).slots[0]

    monkeypatch.setattr(live, "_slot_position_is_same", same_slot)

    result = live.run_one_shot(
        execute=True,
        confirmation=live.CONFIRMATION_PHRASE.format(level=6),
        click_fn=click,
        sleep_fn=lambda _: None,
    )

    assert result["selection_confirmed"] is True
    assert result["status"] == "START_CONFIRMED"
    assert len(slot_checks) == 3
    assert len(clicked) == 2
    assert len(captured) >= 4


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
        confirmation=live.CONFIRMATION_PHRASE.format(level=6),
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

    result = live.run_one_shot(execute=True, confirmation=live.CONFIRMATION_PHRASE.format(level=6), click_fn=click, sleep_fn=lambda _: None)

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
        confirmation=live.CONFIRMATION_PHRASE.format(level=6),
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

    result = live.run_one_shot(execute=True, confirmation=live.CONFIRMATION_PHRASE.format(level=6), click_fn=click, sleep_fn=lambda _: None)

    assert result["status"] == "UNKNOWN_AFTER_CLICK"
    assert result["queue_modified"] == "unknown"
    assert result["blockers"] == ["train_click_not_visually_confirmed_do_not_retry"]
    assert len(clicked) == 2


def test_unconfirmed_requested_level_stops_before_preflight_and_train(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)
    monkeypatch.setattr(live, "_requested_level_is_selected", lambda frame, slot, selection: False)
    plan_calls = []
    monkeypatch.setattr(live, "_build_selected_slot_plan", lambda *args, **kwargs: plan_calls.append(True))

    result = live.run_one_shot(
        execute=True,
        confirmation=live.CONFIRMATION_PHRASE.format(level=6),
        click_fn=click,
        sleep_fn=lambda _: None,
    )

    assert result["status"] == "BLOCKED_AFTER_LEVEL_CLICK"
    assert result["selection_confirmed"] is False
    assert result["blockers"] == ["requested_level_not_visually_confirmed"]
    assert result["queue_modified"] is False
    assert len(clicked) == 1
    assert plan_calls == []


def test_requested_level_must_still_be_selected_immediately_before_train(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)
    selected_checks = iter((True, False))
    monkeypatch.setattr(live, "_requested_level_is_selected", lambda frame, slot, selection: next(selected_checks))

    result = live.run_one_shot(
        execute=True,
        confirmation=live.CONFIRMATION_PHRASE.format(level=6),
        click_fn=click,
        sleep_fn=lambda _: None,
    )

    assert result["status"] == "BLOCKED_AFTER_LEVEL_CLICK"
    assert result["selection_confirmed"] is True
    assert result["blockers"] == ["requested_level_not_visually_confirmed_before_train"]
    assert result["queue_modified"] is False
    assert len(clicked) == 1


def test_guardsmen_category_must_still_be_selected_before_train(monkeypatch):
    clicked, _, _, _, click = _live_fixtures(monkeypatch)
    categories = iter(("guardsmen", "guardsmen", "specialists"))
    monkeypatch.setattr(live, "read_selected_category", lambda frame, variant: {
        "status": "confirmed", "unit_type": next(categories),
    })

    result = live.run_one_shot(
        execute=True,
        confirmation=live.CONFIRMATION_PHRASE.format(level=6),
        click_fn=click,
        sleep_fn=lambda _: None,
    )

    assert result["status"] == "BLOCKED_AFTER_LEVEL_CLICK"
    assert result["blockers"] == ["guardsmen_category_not_confirmed_before_train"]
    assert result["queue_modified"] is False
    assert len(clicked) == 1


def test_requested_level_maps_only_inside_consecutive_visible_range(monkeypatch):
    layout = find_slots(EMPTY)
    centers = ((10.0, 15.0, 4.0), (10.0, 40.0, 4.0), (10.0, 65.0, 6.0))
    monkeypatch.setattr(live, "read_slot_selector_levels", lambda frame, slot: SimpleNamespace(
        status="candidate", lowest_visible_level=5, highest_visible_level=7, badge_centers=centers,
    ))

    selection = live._select_requested_level(_read_image(EMPTY), layout.slots[0], 6)

    assert selection["badge_index"] == 1
    assert (selection["local_x"], selection["local_y"]) == (10, 40)
    with pytest.raises(live.LiveTrainingError, match="not in the slot"):
        live._select_requested_level(_read_image(EMPTY), layout.slots[0], 4)
