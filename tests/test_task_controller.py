from datetime import datetime, timedelta, timezone

from army_training_plan import create_guard_training_plan
from task_controller import (
    TASK_TYPES,
    TaskQueueError,
    create_task_queue,
    enqueue_task,
    get_next_task,
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
)


BASE_TIME = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


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
