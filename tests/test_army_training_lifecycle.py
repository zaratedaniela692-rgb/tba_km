from datetime import datetime, timedelta, timezone

from army_training_lifecycle import advance_training_lifecycle, confirm_help_action
from army_training_process import NumericReading, Slot, SlotObservation, TrainingGoal, enqueue_training_goal
from task_controller import create_task_queue, enqueue_task, mark_task_started

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def active_task(quick_finish=False):
    queue = create_task_queue("p", post_order_delay_seconds=2, help_to_speedup_delay_seconds=0.2)
    task = enqueue_task(queue, "army_training", quick_finish=quick_finish, now=NOW)
    mark_task_started(queue, task["task_id"], 3600, now=NOW)
    return queue, queue["tasks"][0]


def stock_goal_queue(city_count):
    queue = create_task_queue("p")
    task = enqueue_training_goal(queue, TrainingGoal("p", Slot(7, 1)), NOW)
    task = queue["tasks"][0]
    task["status"] = "waiting_completion"
    task["started_at"] = NOW.isoformat()
    task["initial_remaining_seconds"] = 3600
    task["last_remaining_seconds"] = 3600
    task["payload"]["process"]["state"] = "waiting_training"
    observation = SlotObservation(
        profile_id="p",
        slot=Slot(7, 1),
        observed_at=NOW + timedelta(hours=1),
        source="fixture",
        training_status="idle",
        highest_unlocked_level=NumericReading(7, 90),
        city_count=NumericReading(city_count, 90),
        queue_limits={6: NumericReading(1000, 90), 7: NumericReading(1000, 90)},
        selection_verified=True,
    )
    return queue, task, observation


def test_help_click_is_proposed_only_after_delay_and_confirmed_visual_state():
    queue, task = active_task()

    early = advance_training_lifecycle(queue, task["task_id"], NOW + timedelta(seconds=1), "active", "help")
    ready = advance_training_lifecycle(queue, task["task_id"], NOW + timedelta(seconds=2), "active", "help")

    assert early["action"] == "wait"
    assert ready == {"status": "waiting_help_delay", "action": "click_help", "reason": "help_button_confirmed"}
    assert task["status"] == "waiting_help_delay"


def test_help_confirmation_requires_speedup_state_and_starts_settle_delay():
    queue, task = active_task()
    click_time = NOW + timedelta(seconds=2)

    result = confirm_help_action(queue, task["task_id"], click_time, "active", "speedup")

    assert result["status"] == "waiting_speedup"
    assert task["help_requested_at"] == click_time.isoformat()
    assert task["speedup_check_at"] == (click_time + timedelta(seconds=0.2)).isoformat()

    confirmed = advance_training_lifecycle(queue, task["task_id"], click_time + timedelta(seconds=0.2), "active", "speedup", dry_run=False)
    assert confirmed["status"] == "waiting_completion"


def test_uncertain_help_click_pauses_queue():
    queue, task = active_task()

    result = confirm_help_action(queue, task["task_id"], NOW + timedelta(seconds=2), "active", "unknown")

    assert result["status"] == "paused"
    assert queue["paused"] is True
    assert task["status"] == "waiting_help_delay"


def test_quick_finish_requires_manual_acceleration_flow():
    queue, task = active_task(quick_finish=True)
    confirm_help_action(queue, task["task_id"], NOW + timedelta(seconds=2), "active", "speedup")
    advance_training_lifecycle(queue, task["task_id"], NOW + timedelta(seconds=2.2), "active", "speedup", dry_run=False)

    result = advance_training_lifecycle(queue, task["task_id"], NOW + timedelta(seconds=3), "active", "speedup")

    assert result["action"] == "manual_acceleration_required"
    assert task["status"] == "ready_to_accelerate"


def test_stock_goal_completion_requires_fresh_observation_and_reconciles():
    queue, task, observation = stock_goal_queue(city_count=2000)

    preview = advance_training_lifecycle(queue, task["task_id"], observation.observed_at, "idle", observation=observation)
    assert preview["action"] == "complete_and_reconcile"
    assert task["status"] == "waiting_completion"

    result = advance_training_lifecycle(
        queue, task["task_id"], observation.observed_at, "idle", observation=observation, dry_run=False,
    )
    assert result["reason"] == "stock_threshold_met"
    assert task["status"] == "completed"


def test_stock_goal_is_requeued_when_fresh_stock_remains_below_threshold():
    queue, task, observation = stock_goal_queue(city_count=0)

    result = advance_training_lifecycle(
        queue, task["task_id"], observation.observed_at, "idle", observation=observation, dry_run=False,
    )

    assert result["action"] == "requeue_goal"
    assert task["status"] == "queued"
    assert task["payload"]["process"]["state"] == "needs_preflight"


def test_stock_goal_does_not_complete_without_fresh_reobservation():
    queue, task, _ = stock_goal_queue(city_count=2000)

    result = advance_training_lifecycle(queue, task["task_id"], NOW, "idle", dry_run=False)

    assert result["action"] == "reobserve_stock"
    assert task["status"] == "waiting_completion"
