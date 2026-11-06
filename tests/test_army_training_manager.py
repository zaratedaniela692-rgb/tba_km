from datetime import datetime, timezone
from types import SimpleNamespace

from army_training_levels import SelectorLevelReading
from army_training_manager import FrameObservation, evaluate_goals, frame_max_level
from army_training_observation import build_slot_observation
from army_training_process import NumericReading, Slot, TrainingGoal, enqueue_training_goal
from army_training_resolver import resolve_goal_slot
from army_training_slot_reader import SlotReadings
from task_controller import create_task_queue

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def level(low, high):
    return SelectorLevelReading(
        "candidate", "ok", (), None, highest_visible_level=high, one_below_visible_level=high - 1,
        confidence=90, lowest_visible_level=low,
    )


# Empty-queue fixture shape: V-VII, VI-VII, VI-VII.
LEVELS = (level(5, 7), level(6, 7), level(6, 7))


def readings(index, limit=1565, city=1861):
    return SlotReadings(index, NumericReading(limit, 90), NumericReading(city, 90), NumericReading(12_600_000, 90))


def frame(levels=LEVELS, status="idle"):
    layout = SimpleNamespace(status="candidate", slot_readings=levels, global_highest_visible_level=7)
    return FrameObservation(NOW, "test", status, "ok", layout, lambda index: readings(index))


def queue_with(*slots):
    queue = create_task_queue("p")
    for level_number, match in slots:
        enqueue_training_goal(queue, TrainingGoal("p", Slot(level_number, match)), NOW)
    return queue


def test_resolver_picks_mth_slot_containing_the_level():
    assert resolve_goal_slot(LEVELS, 5, 1).frame_index == 0
    assert resolve_goal_slot(LEVELS, 6, 1).frame_index == 0
    assert resolve_goal_slot(LEVELS, 6, 3).frame_index == 2
    assert resolve_goal_slot(LEVELS, 7, 2).candidates == (0, 1, 2)


def test_resolver_reports_unsupported_and_blocked_cases():
    assert resolve_goal_slot(LEVELS, 6, 4).reason == "match_not_visible_without_scrolling"
    assert resolve_goal_slot(LEVELS, 3, 1).reason == "level_not_in_visible_slots"
    uncertain = (level(5, 7), SelectorLevelReading("unknown", "x", (), None))
    assert resolve_goal_slot(uncertain, 6, 1).status == "blocked"
    gap = (SelectorLevelReading("candidate", "ok", (), None, 7, 6, 90, None),)
    assert resolve_goal_slot(gap, 7, 1).status == "blocked"


def test_adapter_shares_the_slot_limit_between_levels_and_marks_selection():
    observation = build_slot_observation("p", Slot(6, 1), LEVELS[0], readings(0), "idle", NOW, "test")
    assert observation.selection_verified is False
    assert {observation.queue_limits[key].value for key in (6, 7)} == {1565}

    at_max = build_slot_observation("p", Slot(7, 1), LEVELS[0], readings(0), "idle", NOW, "test")
    assert at_max.selection_verified is True


def test_frame_max_level_requires_a_candidate_layout():
    assert frame_max_level(frame()) == 7
    unknown = frame()
    unknown.levels = SimpleNamespace(status="unknown", global_highest_visible_level=None)
    assert frame_max_level(unknown) is None


def test_goal_at_max_level_needs_preflight_and_lower_level_needs_selection():
    queue = queue_with((7, 1), (6, 1))
    report = evaluate_goals(queue, frame(), NOW)
    by_id = {goal["level"]: goal for goal in report["goals"]}

    assert by_id[7]["state"] == "needs_preflight"
    assert by_id[7]["next_action"] == "train_after_preflight"
    assert by_id[6]["reason"] == "selection_unverified"
    assert by_id[6]["next_action"] == "select_level_then_reobserve"
    assert queue["tasks"][0]["payload"]["process"]["state"] == "needs_observation"


def test_saving_decisions_makes_goal_ready_for_the_manager():
    queue = queue_with((7, 1))
    evaluate_goals(queue, frame(), NOW, dry_run=False)

    from task_controller import get_next_task
    assert get_next_task(queue, {}, now=NOW)["task_id"] == "army_stock:level_7:match_1"


def test_unresolvable_goals_do_not_touch_the_queue_and_are_reported():
    queue = queue_with((6, 4), (3, 1))
    report = evaluate_goals(queue, frame(), NOW, dry_run=False)

    assert [goal["reason"] for goal in report["goals"]] == [
        "match_not_visible_without_scrolling", "level_not_in_visible_slots",
    ]
    assert all(task["payload"]["process"]["state"] == "needs_observation" for task in queue["tasks"])


def test_active_training_and_bad_layout_block_decisions():
    queue = queue_with((7, 1))
    assert evaluate_goals(queue, frame(status="active"), NOW)["goals"][0]["reason"] == "training_active"
    broken = frame()
    broken.layout_status, broken.levels = "ambiguous", None
    assert evaluate_goals(queue, broken, NOW)["goals"][0]["reason"] == "slot_layout_ambiguous"
