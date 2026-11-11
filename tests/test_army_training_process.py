from dataclasses import replace
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from army_training_process import (
    NumericReading,
    ProcessState,
    Slot,
    SlotObservation,
    TrainingGoal,
    decide_training_goal,
    enqueue_training_goal,
    goal_task_id,
    migrate_legacy_training_goals,
    reconcile_training_goal,
    resume_training_goal,
    TrainingProcessError,
)
from task_controller import create_task_queue, get_next_task, load_task_queue, mark_task_started, save_task_queue


NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
GOAL = TrainingGoal("account-a", Slot("guardsmen", 5, 1))


def observation(count=0):
    return SlotObservation(
        "account-a", Slot("guardsmen", 5, 1), NOW, "frame-1.png", "idle",
        NumericReading(5, 99), NumericReading(count, 96),
        {4: NumericReading(1000, 96), 5: NumericReading(700, 96)}, True,
    )


def test_decision_is_pure_and_uses_slot_limits():
    evidence = observation()
    result = decide_training_goal(GOAL, evidence, NOW)
    assert result.state == ProcessState.NEEDS_PREFLIGHT
    assert result.target_count == 2000
    assert result.training_count == 700
    assert evidence.city_count.value == 0
    assert decide_training_goal(GOAL, observation(1600), NOW).state == ProcessState.SATISFIED


@pytest.mark.parametrize("changes, reason", [
    ({"profile_id": "account-b"}, "profile_mismatch"),
    ({"slot": Slot("guardsmen", 5, 2)}, "slot_mismatch"),
    ({"observed_at": NOW - timedelta(seconds=31)}, "stale_or_future_observation"),
    ({"observed_at": NOW + timedelta(seconds=1)}, "stale_or_future_observation"),
    ({"selection_verified": False}, "selection_unverified"),
    ({"training_status": "unknown"}, "training_state_unknown"),
    ({"city_count": NumericReading(None, None)}, "city_count_uncertain"),
    ({"city_count": NumericReading(2000, 69)}, "city_count_uncertain"),
    ({"queue_limits": {4: NumericReading(1000, 69)}}, "reference_limit_uncertain"),
])
def test_uncertain_evidence_blocks_action(changes, reason):
    result = decide_training_goal(GOAL, replace(observation(), **changes), NOW)
    assert result.state == ProcessState.BLOCKED
    assert result.reason == reason
    assert result.training_count == 0


def test_active_training_cannot_satisfy_goal_or_start_another_order():
    result = decide_training_goal(GOAL, replace(observation(2000), training_status="active"), NOW)
    assert result.state == ProcessState.WAITING_TRAINING
    assert result.training_count == 0


def test_slot_one_level_below_target_completes_goal_without_other_readings():
    queue = create_task_queue(GOAL.profile_id)
    enqueue_training_goal(queue, GOAL, NOW)
    task = queue["tasks"][0]
    evidence = replace(
        observation(),
        highest_unlocked_level=NumericReading(4, 96),
        city_count=NumericReading(None, None),
        queue_limits={},
        selection_verified=False,
    )

    decision = reconcile_training_goal(queue, task["task_id"], evidence, NOW, dry_run=False)

    assert decision.state == ProcessState.SATISFIED
    assert decision.reason == "target_level_unavailable_for_slot"
    stored = queue["tasks"][0]
    assert stored["status"] == "completed"
    assert stored["payload"]["process"]["history"][-1]["reason"] == "target_level_unavailable_for_slot"
    assert decision.training_count == 0


def test_slot_more_than_one_level_below_target_stays_blocked():
    evidence = replace(observation(), highest_unlocked_level=NumericReading(3, 96))

    decision = decide_training_goal(GOAL, evidence, NOW)

    assert decision.state == ProcessState.BLOCKED
    assert decision.reason == "target_level_unavailable_for_slot"


def test_goal_is_idempotent_and_dry_run_does_not_change_queue():
    queue = create_task_queue(GOAL.profile_id)
    task = enqueue_training_goal(queue, GOAL, NOW)
    assert enqueue_training_goal(queue, GOAL, NOW) == task
    original = deepcopy(queue)
    result = reconcile_training_goal(queue, task["task_id"], observation(1600), NOW)
    assert result.state == ProcessState.SATISFIED
    assert queue == original


def test_goal_identity_includes_unit_type_and_non_guard_decisions_block():
    queue = create_task_queue(GOAL.profile_id)
    guard_goal = enqueue_training_goal(queue, GOAL, NOW)
    specialist_goal = TrainingGoal("account-a", Slot("specialists", 5, 1))
    specialist_task = enqueue_training_goal(queue, specialist_goal, NOW)

    assert guard_goal["task_id"] == "army_stock:unit_guardsmen:level_5:match_1"
    assert specialist_task["task_id"] == "army_stock:unit_specialists:level_5:match_1"
    assert goal_task_id(GOAL.slot) != goal_task_id(specialist_goal.slot)
    decision = decide_training_goal(specialist_goal, observation(), NOW)
    assert (decision.state, decision.reason) == (ProcessState.BLOCKED, "unit_type_not_supported_for_training")


def test_legacy_goal_migrates_to_guardsmen_without_changing_lifecycle_identity():
    queue = create_task_queue(GOAL.profile_id)
    enqueue_training_goal(queue, GOAL, NOW)
    task = queue["tasks"][0]
    task["task_id"] = "army_stock:level_5:match_1"
    task["payload"]["slot"].pop("unit_type")
    task["status"] = "waiting_completion"
    history = deepcopy(task["payload"]["process"]["history"])

    assert migrate_legacy_training_goals(queue) is True
    assert task["payload"]["slot"] == {"unit_type": "guardsmen", "global_level": 5, "match_number": 1}
    assert task["task_id"] == "army_stock:level_5:match_1"
    assert task["status"] == "waiting_completion"
    assert task["payload"]["process"]["history"] == history
    assert enqueue_training_goal(queue, GOAL, NOW) == task
    assert len(queue["tasks"]) == 1


def test_satisfied_goal_is_saved_without_inventing_completed_runs(tmp_path):
    queue = create_task_queue(GOAL.profile_id)
    task = enqueue_training_goal(queue, GOAL, NOW)
    reconcile_training_goal(queue, task["task_id"], observation(1600), NOW, dry_run=False)
    path = save_task_queue(queue, tmp_path / "tasks.json")
    restored = load_task_queue(path, expected_profile_id=GOAL.profile_id)
    stored_task = restored["tasks"][0]
    assert stored_task["status"] == "completed"
    assert stored_task["started_at"] is None
    assert "completed_runs" not in stored_task["payload"]
    assert stored_task["payload"]["process"]["history"][-1]["reason"] == "stock_threshold_met"
    assert stored_task["payload"]["process"]["observation"]["source"] == "frame-1.png"


def test_restart_invalidates_decision_and_stock_can_be_rechecked(tmp_path):
    queue = create_task_queue(GOAL.profile_id)
    task = enqueue_training_goal(queue, GOAL, NOW)
    reconcile_training_goal(queue, task["task_id"], observation(1600), NOW, dry_run=False)
    restored = load_task_queue(save_task_queue(queue, tmp_path / "tasks.json"))
    resumed = resume_training_goal(restored, task["task_id"], NOW)
    assert resumed["payload"]["process"]["state"] == "reconcile"
    assert resumed["payload"]["process"]["decision"] is None
    reconcile_training_goal(restored, task["task_id"], observation(0), NOW, dry_run=False)
    assert restored["tasks"][0]["status"] == "queued"
    assert restored["tasks"][0]["payload"]["process"]["decision"]["training_count"] == 700


def test_active_queue_task_cannot_be_completed_from_stock_reading():
    queue = create_task_queue(GOAL.profile_id)
    task = enqueue_training_goal(queue, GOAL, NOW)
    mark_task_started(queue, task["task_id"], 100, now=NOW)
    original = deepcopy(queue)
    with pytest.raises(TrainingProcessError, match="active run"):
        reconcile_training_goal(queue, task["task_id"], observation(2000), NOW, dry_run=False)
    assert queue == original
    resume_training_goal(queue, task["task_id"], NOW)
    assert queue["tasks"][0]["status"] == "waiting_help_delay"


def test_goal_cannot_be_enqueued_into_another_profile():
    with pytest.raises(ValueError):
        enqueue_training_goal(create_task_queue("account-b"), GOAL, NOW)


def test_queue_only_selects_goal_with_unexpired_preflight_decision():
    queue = create_task_queue(GOAL.profile_id)
    task = enqueue_training_goal(queue, GOAL, NOW)
    assert get_next_task(queue, {}, NOW) is None
    reconcile_training_goal(queue, task["task_id"], observation(), NOW, dry_run=False)
    assert get_next_task(queue, {}, NOW)["task_id"] == task["task_id"]
    assert get_next_task(queue, {}, NOW + timedelta(seconds=30)) is None
    resume_training_goal(queue, task["task_id"], NOW)
    assert get_next_task(queue, {}, NOW) is None


def test_queue_does_not_select_blocked_goal():
    queue = create_task_queue(GOAL.profile_id)
    task = enqueue_training_goal(queue, GOAL, NOW)
    reconcile_training_goal(
        queue, task["task_id"], replace(observation(), city_count=NumericReading(None, None)),
        NOW, dry_run=False,
    )
    assert get_next_task(queue, {}, NOW) is None