import pytest

from speedup_planner import (
    DAY,
    HOUR,
    SpeedupPlanError,
    plan_speedups,
)

M = 60


def total(plan):
    return sum(duration * count for duration, count in plan.uses)


def test_nothing_to_do_when_no_time_remains():
    plan = plan_speedups(0, {HOUR: 50})

    assert plan.status == "nothing_to_do"
    assert plan.uses == ()


def test_shortfall_uses_nothing_and_reports_missing_time():
    plan = plan_speedups(10 * HOUR, {HOUR: 3, 3 * HOUR: 1})

    assert plan.status == "shortfall"
    assert plan.uses == ()
    assert plan.shortfall_seconds == 10 * HOUR - 6 * HOUR


def test_short_task_uses_preferred_hours_largest_first():
    plan = plan_speedups(12 * HOUR, {HOUR: 40, 3 * HOUR: 40, 8 * HOUR: 40, 15 * M: 99})

    assert dict(plan.uses) == {8 * HOUR: 1, 3 * HOUR: 1, HOUR: 1}
    assert plan.breached_floors == ()
    assert [decision["selected_duration_seconds"] for decision in plan.decisions] == [8 * HOUR, 3 * HOUR, HOUR]
    assert [decision["strategy"] for decision in plan.decisions] == ["preferred_fit"] * 3
    assert [decision["remaining_before_seconds"] for decision in plan.decisions] == [12 * HOUR, 4 * HOUR, HOUR]
    assert plan.decisions[0]["candidates_seconds"] == (HOUR, 3 * HOUR, 8 * HOUR)


def test_mid_task_prefers_8h_and_15h():
    plan = plan_speedups(10 * DAY, {HOUR: 50, 8 * HOUR: 50, 15 * HOUR: 50, DAY: 50})

    assert set(d for d, _ in plan.uses) == {15 * HOUR, 8 * HOUR}
    assert total(plan) >= 10 * DAY


def test_long_task_prefers_days_over_hours():
    plan = plan_speedups(200 * DAY, {HOUR: 500, 3 * DAY: 40, 7 * DAY: 40, 30 * DAY: 40})

    assert set(d for d, _ in plan.uses) <= {3 * DAY, 7 * DAY, 30 * DAY}
    assert total(plan) >= 200 * DAY


def test_last_item_may_overshoot_when_nothing_smaller_fits():
    plan = plan_speedups(30 * M, {HOUR: 20})

    assert plan.uses == ((HOUR, 1),)


def test_floor_is_kept_when_other_items_can_finish():
    inventory = {HOUR: 10, 3 * HOUR: 30}

    plan = plan_speedups(6 * HOUR, inventory)

    assert dict(plan.uses) == {3 * HOUR: 2}
    assert plan.breached_floors == ()


def test_large_items_keep_a_floor_of_three():
    plan = plan_speedups(3 * DAY, {3 * DAY: 3, HOUR: 100})

    assert 3 * DAY not in dict(plan.uses)
    assert plan.breached_floors == ()


def test_floor_is_breached_and_reported_only_when_needed():
    plan = plan_speedups(6 * DAY, {3 * DAY: 3})

    assert plan.status == "ok"
    assert plan.uses == ((3 * DAY, 2),)
    assert plan.breached_floors == (3 * DAY,)


def test_unused_duration_below_floor_is_not_a_breach():
    plan = plan_speedups(3 * HOUR, {HOUR: 2, 3 * HOUR: 20})

    assert plan.uses == ((3 * HOUR, 1),)
    assert plan.breached_floors == ()


def test_zero_quantities_are_ignored():
    plan = plan_speedups(HOUR, {HOUR: 0, 3 * HOUR: 11})

    assert plan.uses == ((3 * HOUR, 1),)


@pytest.mark.parametrize("remaining", (-1, 1.5, True, "5"))
def test_invalid_remaining_time_is_rejected(remaining):
    with pytest.raises(SpeedupPlanError):
        plan_speedups(remaining, {HOUR: 1})


@pytest.mark.parametrize("inventory", ({0: 1}, {HOUR: -1}, {HOUR: 1.5}, {HOUR: True}, {"1h": 1}, [HOUR]))
def test_invalid_inventory_is_rejected(inventory):
    with pytest.raises(SpeedupPlanError):
        plan_speedups(HOUR, inventory)
