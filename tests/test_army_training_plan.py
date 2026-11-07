from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from army_training_plan import (
    TrainingPlanError,
    confirm_active_order_run_completed,
    create_guard_training_plan,
    evaluate_slot_replenishment,
    get_active_training_target,
    load_plan,
    profile_plan_path,
    record_training_check,
    save_plan,
    start_next_order,
)
from army_training_scanner import read_army_training_snapshot


BASE_TIME = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def test_slot_replenishment_uses_eighty_percent_of_its_own_reference_limit():
    result = evaluate_slot_replenishment(
        global_level=5,
        match_number=1,
        highest_unlocked_level=5,
        current_troop_count=1600,
        current_count_confidence=96,
        queue_limits_by_level={4: 1000, 5: 700},
        training_level=5,
        unit_type="guardsmen",
    )

    assert result == {
        "status": "satisfied",
        "slot": {"unit_type": "guardsmen", "global_level": 5, "match_number": 1},
        "highest_unlocked_level": 5,
        "reference_level": 4,
        "training_level": 5,
        "current_troop_count": 1600,
        "reference_queue_limit": 1000,
        "selected_level_queue_limit": 700,
        "target_count": 2000,
        "completion_count": 1600,
        "remaining_count": 400,
        "count_confidence": 96,
        "minimum_count_confidence": 70,
        "count_confidence_ok": True,
        "recommended_training_count": 0,
    }


def test_slot_replenishment_caps_order_by_gap_and_slot_specific_queue_limit():
    near_goal = evaluate_slot_replenishment(5, 1, 5, 1599, 96, {4: 1000, 5: 700}, 5, unit_type="guardsmen")
    large_gap = evaluate_slot_replenishment(5, 1, 5, 0, 96, {4: 1000, 5: 700}, 5, unit_type="guardsmen")
    other_slot = evaluate_slot_replenishment(5, 2, 5, 0, 96, {4: 500, 5: 300}, 5, unit_type="guardsmen")

    assert near_goal["status"] == "replenish"
    assert near_goal["recommended_training_count"] == 401
    assert large_gap["recommended_training_count"] == 700
    assert other_slot["target_count"] == 1000
    assert other_slot["recommended_training_count"] == 300


@pytest.mark.parametrize(
    "arguments",
    [
        (5, 1, 5, -1, 96, {4: 100, 5: 50}, 5),
        (5, 1, 1, 0, 96, {1: 50}, 1),
        (5, 1, 5, 0, 96, {5: 0}, 5),
        (5, 1, 5, True, 96, {4: 100, 5: 50}, 5),
        (5, 1, 5, 0, 96, {5: 50}, 5),
    ],
)
def test_slot_replenishment_rejects_invalid_counts_and_limits(arguments):
    with pytest.raises(TrainingPlanError):
        evaluate_slot_replenishment(*arguments, unit_type="guardsmen")


def test_slot_replenishment_does_not_decide_from_uncertain_ocr():
    result = evaluate_slot_replenishment(5, 1, 5, 1600, 69, {4: 1000, 5: 700}, 5, unit_type="guardsmen")

    assert result["status"] == "uncertain"
    assert result["count_confidence_ok"] is False
    assert result["remaining_count"] is None
    assert result["recommended_training_count"] == 0


def test_guard_plan_contains_six_slot_targets_and_nine_runs():
    plan = create_guard_training_plan("account-a")

    assert len(plan["orders"]) == 6
    assert sum(order["requested_runs"] for order in plan["orders"]) == 9
    assert [(order["global_level"], order["match_number"], order["requested_runs"]) for order in plan["orders"]] == [
        (5, 1, 1),
        (4, 1, 2),
        (5, 2, 1),
        (4, 2, 2),
        (5, 3, 1),
        (4, 3, 2),
    ]
    assert all("unit_type" not in order for order in plan["orders"])


def test_only_one_order_can_be_active():
    plan = create_guard_training_plan("account-a")
    first = start_next_order(plan, BASE_TIME)

    assert first["order_id"] == "level_5_match_1"
    assert get_active_training_target(plan) == {"global_level": 5, "match_number": 1}
    assert start_next_order(plan, BASE_TIME + timedelta(minutes=1)) is None
    assert record_training_check(plan, BASE_TIME + timedelta(minutes=30)) == (
        BASE_TIME + timedelta(minutes=75)
    ).isoformat()


def test_repeat_order_requires_two_confirmed_completions_and_reset_delay():
    plan = create_guard_training_plan("account-a")
    start_next_order(plan, BASE_TIME)
    confirm_active_order_run_completed(plan, BASE_TIME + timedelta(minutes=10))

    lower_order = start_next_order(plan, BASE_TIME + timedelta(minutes=10, seconds=4))
    assert lower_order is None
    lower_order = start_next_order(plan, BASE_TIME + timedelta(minutes=10, seconds=5))
    assert lower_order["order_id"] == "level_4_match_1"
    assert get_active_training_target(plan) == {"global_level": 4, "match_number": 1}

    first_run = confirm_active_order_run_completed(plan, BASE_TIME + timedelta(minutes=20))
    assert first_run["completed_runs"] == 1
    assert first_run["requested_runs"] == 2
    assert first_run["status"] == "pending"

    start_next_order(plan, BASE_TIME + timedelta(minutes=20, seconds=5))
    second_run = confirm_active_order_run_completed(plan, BASE_TIME + timedelta(minutes=30))
    assert second_run["completed_runs"] == 2
    assert second_run["status"] == "completed"


def test_plans_are_saved_separately_and_profile_mismatch_is_rejected(tmp_path):
    first_plan = create_guard_training_plan("account-a")
    second_plan = create_guard_training_plan("account-b")
    first_path = save_plan(first_plan, profile_plan_path("account-a", tmp_path))
    second_path = save_plan(second_plan, profile_plan_path("account-b", tmp_path))

    assert first_path != second_path
    assert load_plan(first_path, expected_profile_id="account-a")["profile_id"] == "account-a"
    assert load_plan(second_path, expected_profile_id="account-b")["profile_id"] == "account-b"
    with pytest.raises(TrainingPlanError, match="innego profilu"):
        load_plan(first_path, expected_profile_id="account-b")


def test_army_training_snapshot_detects_active_training_and_speedup_button():
    image_path = Path(__file__).resolve().parents[1] / "screenshots" / "army_training" / "pelny.png"
    snapshot = read_army_training_snapshot(image_path)

    assert snapshot["has_active_training"] is True
    assert snapshot["speedup_button_detected"] is True
    assert snapshot["status"] == "active"
    assert isinstance(snapshot["trained_unit_count_raw"], str)
    if snapshot["trained_unit_count"] is not None:
        assert isinstance(snapshot["trained_unit_count"], int)
        assert isinstance(snapshot["trained_unit_count_confidence"], float)
        assert 0 <= snapshot["trained_unit_count_confidence"] <= 100


def test_army_training_snapshot_detects_empty_queue_from_unit_image():
    image_path = Path(__file__).resolve().parents[1] / "screenshots" / "army_training" / "pelny_army_training_empty_queue.png"

    snapshot = read_army_training_snapshot(image_path)

    assert snapshot["has_active_training"] is False
    assert snapshot["status"] == "idle"
    assert snapshot["training_unit_image_detail"] < 8


@pytest.mark.parametrize("image_name", ("army_training1.png", "army_training3.png", "army_training4.png"))
def test_army_training_snapshot_detects_active_unit_image(image_name):
    image_path = Path(__file__).resolve().parents[1] / "templates" / image_name

    snapshot = read_army_training_snapshot(image_path)

    assert snapshot["has_active_training"] is True
    assert snapshot["status"] == "active"
    assert snapshot["training_unit_image_detail"] >= 20
