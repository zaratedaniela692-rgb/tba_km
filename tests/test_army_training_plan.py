from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from army_training_plan import (
    TrainingPlanError,
    confirm_active_order_run_completed,
    create_guard_training_plan,
    load_plan,
    profile_plan_path,
    record_training_check,
    save_plan,
    start_next_order,
)
from army_training_scanner import read_army_training_snapshot


BASE_TIME = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def test_guard_plan_contains_six_orders_and_nine_runs():
    plan = create_guard_training_plan("account-a")

    assert len(plan["orders"]) == 6
    assert sum(order["requested_runs"] for order in plan["orders"]) == 9
    assert "flying" not in {order["unit_type"] for order in plan["orders"]}
    for unit_type in ("archers", "spearmen", "cavalry"):
        orders = [order for order in plan["orders"] if order["unit_type"] == unit_type]
        assert [(order["global_level"], order["requested_runs"]) for order in orders] == [(5, 1), (4, 2)]


def test_only_one_order_can_be_active():
    plan = create_guard_training_plan("account-a")
    first = start_next_order(plan, BASE_TIME)

    assert first["order_id"] == "archers_level_5"
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
    assert lower_order["order_id"] == "archers_level_4"

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
    assert snapshot["queue_count"] is not None
    assert isinstance(snapshot["queue_count"], int)
