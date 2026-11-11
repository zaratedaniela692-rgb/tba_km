from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from army_training_plan import create_guard_training_plan
from task_controller import (
    TASK_TYPES,
    TaskQueueError,
    create_task_queue,
    effective_priority,
    enqueue_task,
    get_next_task,
    validate_task_queue,
    mark_task_started,
    mark_help_requested,
    mark_speedup_available,
    record_acceleration_unavailable,
    resume_task_queue,
    save_task_queue,
    load_task_queue,
    update_task_remaining_time,
    enqueue_next_training_run,
    start_training_task,
    complete_training_task,
    task_parallelism_blocker,
)


BASE_TIME = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("invalid_archive", ("hold", "retry"))
def test_resume_rejects_invalid_archives_without_mutating_tasks(invalid_archive):
    from task_controller import resume_army_training

    queue = create_task_queue("account-a")
    enqueue_task(queue, "army_training", task_id="first", now=BASE_TIME)
    second = enqueue_task(queue, "army_training", task_id="second", now=BASE_TIME)
    queue["army_training_hold"] = {
        "at": BASE_TIME.isoformat(), "task_id": "first", "reason": "silver_insufficient",
    }
    if invalid_archive == "hold":
        queue["army_training_hold_history"] = {}
    else:
        second["resource_retry_history"] = {}
    before = deepcopy(queue)

    with pytest.raises(TaskQueueError, match="must be a list"):
        resume_army_training(queue, BASE_TIME)
    assert queue == before


def test_three_silver_failures_hold_only_new_army_and_resume_retains_history(tmp_path):
    from task_controller import record_resource_retry_failure, resume_army_training, complete_task

    queue = create_task_queue("account-a", resource_retry_seconds=60)
    task = enqueue_task(queue, "army_training", task_id="silver", now=BASE_TIME)
    other_army = enqueue_task(queue, "army_training", task_id="other-army", now=BASE_TIME)
    building = enqueue_task(queue, "building_upgrade", task_id="building", now=BASE_TIME)
    fallback = enqueue_task(queue, "army_training", task_id="finish", now=BASE_TIME,
                            payload={"goal_kind": "finish_training_v1"})
    for attempt in range(3):
        now = BASE_TIME + timedelta(seconds=attempt * 60)
        record_resource_retry_failure(queue, "silver", "silver_insufficient", "not_implemented", now)
        assert task["status"] == "waiting_resources"
        if attempt < 2:
            before = deepcopy(queue)
            with pytest.raises(TaskQueueError, match="not due"):
                record_resource_retry_failure(queue, "silver", "silver_insufficient", "not_implemented", now)
            assert queue == before
    assert task["resource_retry"]["attempts"] == 3
    assert "3/3" in queue["army_training_hold"]["reason"]
    assert "not_implemented" in queue["army_training_hold"]["reason"]
    assert other_army["status"] == "queued"
    assert queue["paused"] is False
    assert get_next_task(queue, {}, now=now)["task_id"] == fallback["task_id"]
    complete_task(queue, fallback["task_id"], "finished", now)
    assert get_next_task(queue, {}, now=now)["task_id"] == building["task_id"]
    with pytest.raises(TaskQueueError, match="held"):
        mark_task_started(queue, other_army["task_id"], 100, now)
    path = save_task_queue(queue, tmp_path / "tasks.json")
    assert load_task_queue(path) == queue
    history = deepcopy(task["resource_retry"]["history"])
    queue.update(paused=True, pause_reason="operator_pause")
    assert resume_army_training(queue, now) is True
    assert queue["paused"] is True
    assert task["resource_retry"]["attempts"] == 0
    assert task["resource_retry_history"][0]["history"] == history
    assert queue["army_training_hold_history"][0]["hold"]["task_id"] == "silver"
    before = deepcopy(queue)
    assert resume_army_training(queue, now) is False
    assert queue == before
    record_resource_retry_failure(queue, "silver", "silver_insufficient", "not_implemented", now)
    assert task["resource_retry"]["attempts"] == 1
    assert "army_training_hold" not in queue


def test_army_resume_does_not_modify_active_task_or_marker(tmp_path):
    from army_state import open_training_marker
    from task_controller import resume_army_training

    queue = create_task_queue("account-a")
    active = enqueue_task(queue, "army_training", task_id="active", now=BASE_TIME)
    mark_task_started(queue, "active", 1000, BASE_TIME)
    queue["army_training_hold"] = {"at": BASE_TIME.isoformat(), "task_id": "old", "reason": "silver_insufficient"}
    marker = tmp_path / "army_state.json"
    open_training_marker(marker, "order", "active", {}, BASE_TIME, BASE_TIME + timedelta(hours=1))
    before, marker_before = deepcopy(active), marker.read_bytes()
    assert resume_army_training(queue, BASE_TIME) is True
    assert active == before
    assert marker.read_bytes() == marker_before


@pytest.mark.parametrize(("active_type", "active_status", "remaining", "expected"), (
    ("building_upgrade", "waiting_completion", 61, None),
    ("building_upgrade", "waiting_completion", 60, "parallel_wait_not_ready"),
    ("building_upgrade", "waiting_completion", None, "parallel_wait_not_ready"),
    ("building_upgrade", "waiting_help_delay", 300, "parallel_wait_not_ready"),
    ("army_training", "waiting_completion", 300, "same_type_active"),
    ("army_training", "waiting_help_delay", None, "same_type_active"),
))
def test_parallelism_rule_agrees_with_selection_and_confirmed_start(active_type, active_status, remaining, expected):
    queue = create_task_queue("account-a")
    pending = enqueue_task(queue, "army_training", task_id="pending", now=BASE_TIME)
    active = enqueue_task(queue, active_type, task_id="active", now=BASE_TIME)
    active.update(status=active_status, last_remaining_seconds=remaining)
    before = deepcopy(queue)

    assert task_parallelism_blocker(pending, [active], 60) == expected
    assert queue == before
    selected = get_next_task(queue, {}, now=BASE_TIME)
    if expected is None:
        assert selected["task_id"] == pending["task_id"]
        mark_task_started(queue, pending["task_id"], 100, now=BASE_TIME)
        assert pending["status"] == "waiting_help_delay"
    else:
        assert selected is None
        with pytest.raises(TaskQueueError):
            mark_task_started(queue, pending["task_id"], 100, now=BASE_TIME)
        assert queue == before


def test_parallelism_rule_requires_every_active_task_to_allow_start():
    task = {"task_type": "army_training"}
    ready = {"task_type": "building_upgrade", "status": "waiting_completion", "last_remaining_seconds": 61}
    not_ready = {"task_type": "academy_research", "status": "waiting_completion", "last_remaining_seconds": 60}
    assert task_parallelism_blocker(task, [], 60) is None
    assert task_parallelism_blocker(task, [ready, not_ready], 60) == "parallel_wait_not_ready"


def test_task_types_are_explicit_and_queue_is_profile_scoped():
    queue = create_task_queue("account-a")
    task = enqueue_task(
        queue,
        "army_training",
        payload={"global_level": 5, "match_number": 1},
        required_resources={"silver": 1200},
        now=BASE_TIME,
    )

    assert TASK_TYPES == {"army_training", "building_upgrade", "academy_research"}
    assert queue["profile_id"] == "account-a"
    assert task["task_type"] == "army_training"
    assert task["status"] == "queued"
    assert task["required_resources"] == {"silver": 1200}


def test_insufficient_silver_keeps_task_pending_and_other_type_can_run():
    queue = create_task_queue("account-a", resource_retry_seconds=60)
    training = enqueue_task(
        queue,
        "army_training",
        required_resources={"silver": 1200},
        now=BASE_TIME,
    )
    building = enqueue_task(queue, "building_upgrade", now=BASE_TIME)

    selected = get_next_task(queue, {"silver": 1000}, now=BASE_TIME)

    assert selected["task_id"] == building["task_id"]
    assert training["status"] == "waiting_resources"
    assert training["completed_at"] is None
    assert training["next_check_at"] == (BASE_TIME + timedelta(seconds=60)).isoformat()


def test_training_wait_allows_other_task_only_when_more_than_one_minute_remains():
    queue = create_task_queue("account-a")
    training = enqueue_task(queue, "army_training", now=BASE_TIME)
    mark_task_started(
        queue,
        training["task_id"],
        initial_remaining_seconds=300,
        now=BASE_TIME,
    )
    mark_help_requested(queue, training["task_id"], now=BASE_TIME + timedelta(seconds=2))
    mark_speedup_available(queue, training["task_id"], now=BASE_TIME + timedelta(seconds=2.2))
    building = enqueue_task(queue, "building_upgrade", now=BASE_TIME)

    update_task_remaining_time(queue, training["task_id"], 61)
    selected = get_next_task(queue, {}, now=BASE_TIME + timedelta(seconds=3))
    assert selected["task_id"] == building["task_id"]

    building["status"] = "queued"
    update_task_remaining_time(queue, training["task_id"], 60)
    assert get_next_task(queue, {}, now=BASE_TIME + timedelta(seconds=3)) is None


def test_help_and_speedup_have_separate_timed_states():
    queue = create_task_queue("account-a", post_order_delay_seconds=2, help_to_speedup_delay_seconds=0.2)
    task = enqueue_task(queue, "army_training", quick_finish=True, now=BASE_TIME)
    mark_task_started(queue, task["task_id"], initial_remaining_seconds=300, now=BASE_TIME)

    assert task["status"] == "waiting_help_delay"
    assert task["help_due_at"] == (BASE_TIME + timedelta(seconds=2)).isoformat()
    try:
        mark_help_requested(queue, task["task_id"], now=BASE_TIME + timedelta(seconds=1))
    except TaskQueueError:
        pass
    else:
        raise AssertionError("Help must not be clicked before the configured delay.")

    mark_help_requested(queue, task["task_id"], now=BASE_TIME + timedelta(seconds=2))
    assert task["status"] == "waiting_speedup"
    assert task["speedup_check_at"] == (BASE_TIME + timedelta(seconds=2.2)).isoformat()
    mark_speedup_available(queue, task["task_id"], now=BASE_TIME + timedelta(seconds=2.2))
    assert task["status"] == "ready_to_accelerate"


def test_missing_speedups_pause_profile_until_manual_resume():
    queue = create_task_queue("account-a")
    task = enqueue_task(queue, "army_training", quick_finish=True, now=BASE_TIME)
    mark_task_started(queue, task["task_id"], initial_remaining_seconds=300, now=BASE_TIME)
    mark_help_requested(queue, task["task_id"], now=BASE_TIME + timedelta(seconds=2))
    mark_speedup_available(queue, task["task_id"], now=BASE_TIME + timedelta(seconds=2.2))

    record_acceleration_unavailable(queue, task["task_id"], now=BASE_TIME + timedelta(seconds=3))

    assert queue["paused"] is True
    assert task["status"] == "waiting_speedups"
    assert get_next_task(queue, {}, now=BASE_TIME + timedelta(minutes=5)) is None

    resume_task_queue(queue, now=BASE_TIME + timedelta(seconds=4))
    assert queue["paused"] is False
    assert task["status"] == "waiting_speedup"
    mark_speedup_available(queue, task["task_id"], now=BASE_TIME + timedelta(seconds=4))
    assert task["status"] == "ready_to_accelerate"


def test_resource_wait_is_rechecked_and_profile_queue_persists(tmp_path):
    queue = create_task_queue("account-a", resource_retry_seconds=30)
    task = enqueue_task(
        queue,
        "army_training",
        required_resources={"silver": 1200},
        now=BASE_TIME,
    )
    assert get_next_task(queue, {"silver": 1000}, now=BASE_TIME) is None
    assert task["status"] == "waiting_resources"

    assert get_next_task(queue, {"silver": 1200}, now=BASE_TIME + timedelta(seconds=30))["task_id"] == task["task_id"]
    assert task["status"] == "queued"

    path = save_task_queue(queue, tmp_path / "account-a" / "tasks.json")
    loaded = load_task_queue(path, expected_profile_id="account-a")
    assert loaded == queue


def test_parallel_start_is_rejected_when_active_task_is_too_close_to_completion():
    queue = create_task_queue("account-a")
    training = enqueue_task(queue, "army_training", now=BASE_TIME)
    mark_task_started(queue, training["task_id"], initial_remaining_seconds=300, now=BASE_TIME)
    mark_help_requested(queue, training["task_id"], now=BASE_TIME + timedelta(seconds=2))
    mark_speedup_available(queue, training["task_id"], now=BASE_TIME + timedelta(seconds=2.2))
    training["status"] = "waiting_completion"
    update_task_remaining_time(queue, training["task_id"], 60)
    building = enqueue_task(queue, "building_upgrade", now=BASE_TIME)

    try:
        mark_task_started(queue, building["task_id"], initial_remaining_seconds=90, now=BASE_TIME + timedelta(seconds=3))
    except TaskQueueError:
        pass
    else:
        raise AssertionError("Parallel task start must be blocked at the one-minute boundary.")


def test_training_plan_materializes_one_run_and_syncs_confirmed_completion():
    plan = create_guard_training_plan("account-a")
    queue = create_task_queue("account-a", post_order_delay_seconds=1)

    task = enqueue_next_training_run(
        queue,
        plan,
        required_resources={"silver": 1200},
        quick_finish=True,
        now=BASE_TIME,
    )
    assert task["task_type"] == "army_training"
    assert task["payload"] == {
        "training_order_id": "level_5_match_1",
        "global_level": 5,
        "match_number": 1,
        "run_number": 1,
        "requested_runs": 1,
    }
    assert enqueue_next_training_run(queue, plan, now=BASE_TIME)["task_id"] == task["task_id"]
    assert plan["active_order_id"] is None

    start_training_task(queue, plan, task["task_id"], 300, now=BASE_TIME)
    mark_help_requested(queue, task["task_id"], now=BASE_TIME + timedelta(seconds=1))
    mark_speedup_available(queue, task["task_id"], now=BASE_TIME + timedelta(seconds=1.2))
    complete_training_task(queue, plan, task["task_id"], now=BASE_TIME + timedelta(seconds=2))

    assert plan["orders"][0]["completed_runs"] == 1
    assert plan["orders"][0]["status"] == "completed"
    assert plan["active_order_id"] is None
    assert enqueue_next_training_run(queue, plan, now=BASE_TIME + timedelta(seconds=6)) is None

    next_task = enqueue_next_training_run(queue, plan, now=BASE_TIME + timedelta(seconds=7))
    assert next_task["payload"]["training_order_id"] == "level_4_match_1"
    assert next_task["payload"]["run_number"] == 1


def test_repeated_training_order_advances_only_after_confirmed_run():
    plan = create_guard_training_plan("account-a")
    queue = create_task_queue("account-a", post_order_delay_seconds=1)
    first = enqueue_next_training_run(queue, plan, now=BASE_TIME)
    start_training_task(queue, plan, first["task_id"], 100, now=BASE_TIME)
    mark_help_requested(queue, first["task_id"], now=BASE_TIME + timedelta(seconds=1))
    mark_speedup_available(queue, first["task_id"], now=BASE_TIME + timedelta(seconds=1.2))
    complete_training_task(queue, plan, first["task_id"], now=BASE_TIME + timedelta(seconds=2))

    second = enqueue_next_training_run(queue, plan, now=BASE_TIME + timedelta(seconds=7))
    start_training_task(queue, plan, second["task_id"], 100, now=BASE_TIME + timedelta(seconds=7))
    mark_help_requested(queue, second["task_id"], now=BASE_TIME + timedelta(seconds=8))
    mark_speedup_available(queue, second["task_id"], now=BASE_TIME + timedelta(seconds=8.2))
    complete_training_task(queue, plan, second["task_id"], now=BASE_TIME + timedelta(seconds=9))

    repeated = enqueue_next_training_run(queue, plan, now=BASE_TIME + timedelta(seconds=14))
    assert repeated["payload"]["training_order_id"] == "level_4_match_1"
    assert repeated["payload"]["run_number"] == 2
    start_training_task(queue, plan, repeated["task_id"], 100, now=BASE_TIME + timedelta(seconds=14))
    mark_help_requested(queue, repeated["task_id"], now=BASE_TIME + timedelta(seconds=15))
    mark_speedup_available(queue, repeated["task_id"], now=BASE_TIME + timedelta(seconds=15.2))
    complete_training_task(queue, plan, repeated["task_id"], now=BASE_TIME + timedelta(seconds=16))

    next_run = enqueue_next_training_run(queue, plan, now=BASE_TIME + timedelta(seconds=21))
    assert next_run["payload"]["training_order_id"] == "level_5_match_2"
    assert next_run["payload"]["run_number"] == 1
    assert plan["orders"][1]["completed_runs"] == 2
    assert plan["orders"][1]["status"] == "completed"


def _later(seconds):
    return BASE_TIME + timedelta(seconds=seconds)


def test_higher_priority_added_later_is_selected_first():
    queue = create_task_queue("account-a")
    enqueue_task(queue, "building_upgrade", now=_later(0))
    academy = enqueue_task(queue, "academy_research", priority=1, now=_later(1))

    assert get_next_task(queue, {}, now=_later(2))["task_id"] == academy["task_id"]


def test_type_default_and_task_override_decide_priority():
    queue = create_task_queue("account-a")
    queue["settings"]["task_type_priorities"] = {"building_upgrade": 2}
    building = enqueue_task(queue, "building_upgrade", now=_later(0))
    academy = enqueue_task(queue, "academy_research", now=_later(1))

    assert effective_priority(queue, building) == 2
    assert effective_priority(queue, academy) == 3
    assert get_next_task(queue, {}, now=_later(2))["task_id"] == building["task_id"]

    academy["priority"] = 1
    assert get_next_task(queue, {}, now=_later(2))["task_id"] == academy["task_id"]


def test_army_training_defaults_to_highest_priority():
    queue = create_task_queue("account-a")
    enqueue_task(queue, "building_upgrade", now=_later(0))
    training = enqueue_task(queue, "army_training", now=_later(1))

    assert effective_priority(queue, training) == 1
    assert get_next_task(queue, {}, now=_later(2))["task_id"] == training["task_id"]


def test_equal_priority_is_fifo_by_creation_time():
    queue = create_task_queue("account-a")
    first = enqueue_task(queue, "building_upgrade", now=_later(0))
    enqueue_task(queue, "academy_research", now=_later(1))
    # Creation time wins over list position.
    queue["tasks"].reverse()

    assert get_next_task(queue, {}, now=_later(2))["task_id"] == first["task_id"]


def test_blocked_high_priority_does_not_block_lower_and_returns_first_when_ready():
    queue = create_task_queue("account-a", resource_retry_seconds=60)
    high = enqueue_task(queue, "academy_research", priority=1, required_resources={"silver": 500}, now=_later(0))
    low = enqueue_task(queue, "building_upgrade", priority=4, now=_later(0))

    assert get_next_task(queue, {"silver": 0}, now=_later(1))["task_id"] == low["task_id"]
    assert high["status"] == "waiting_resources"

    assert get_next_task(queue, {"silver": 500}, now=_later(61))["task_id"] == high["task_id"]


def test_active_task_of_same_type_still_blocks_regardless_of_priority():
    queue = create_task_queue("account-a")
    active = enqueue_task(queue, "building_upgrade", priority=5, now=_later(0))
    mark_task_started(queue, active["task_id"], initial_remaining_seconds=300, now=_later(0))
    enqueue_task(queue, "building_upgrade", priority=1, now=_later(1))

    assert get_next_task(queue, {}, now=_later(2)) is None


def test_invalid_priorities_are_rejected():
    queue = create_task_queue("account-a")
    for bad in (0, 6, True, "high", 2.5):
        try:
            enqueue_task(queue, "building_upgrade", priority=bad)
        except TaskQueueError:
            continue
        raise AssertionError(f"Priority {bad!r} must be rejected.")

    queue["settings"]["task_type_priorities"] = {"building_upgrade": 9}
    try:
        validate_task_queue(queue)
    except TaskQueueError:
        pass
    else:
        raise AssertionError("Invalid type priority must be rejected.")


def test_queue_without_priority_fields_still_validates_and_orders_by_type_default():
    queue = create_task_queue("account-a")
    building = enqueue_task(queue, "building_upgrade", now=_later(0))
    training = enqueue_task(queue, "army_training", now=_later(1))
    for task in queue["tasks"]:
        del task["priority"]

    assert validate_task_queue(queue) is True
    assert effective_priority(queue, building) == 3
    assert get_next_task(queue, {}, now=_later(2))["task_id"] == training["task_id"]
