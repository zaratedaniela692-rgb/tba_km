from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import army_training_live_e2e as live
import army_training_manager as manager
import army_training_navigation as navigation
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


def test_execute_blocks_goal_when_task_startup_does_not_open_barracks(monkeypatch, tmp_path):
    queue = create_task_queue("p")
    queue_path = tmp_path / "tasks.json"
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, queue_path))
    monkeypatch.setattr(manager, "process_expirations", lambda *_: {})
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: None)
    monkeypatch.setattr(manager, "army_state_path", lambda *_: tmp_path / "army_state.json")
    monkeypatch.setattr(
        navigation,
        "open_army_training_screen",
        lambda execute: {"status": "BLOCKED_BARRACKS_NOT_CONFIRMED", "actions_executed": True},
    )
    monkeypatch.setattr(
        live,
        "capture_primary_monitor",
        lambda: (_ for _ in ()).throw(AssertionError("goal observation must not run")),
    )
    args = SimpleNamespace(
        profile="p", execute=True, confirm=manager.CONFIRMATION_PHRASE, navigate_only=False,
    )

    result = manager._command_execute(args, tmp_path, NOW)

    assert result["status"] == "BLOCKED_TASK_STARTUP"
    assert result["navigation"]["status"] == "BLOCKED_BARRACKS_NOT_CONFIRMED"
    assert result["actions_executed"] is True
    assert result["queue_modified"] is False


def test_navigate_only_skips_housekeeping_and_task_processing(monkeypatch, tmp_path):
    queue = create_task_queue("p")
    queue_path = tmp_path / "tasks.json"
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, queue_path))
    monkeypatch.setattr(manager, "army_state_path", lambda *_: tmp_path / "army_state.json")
    monkeypatch.setattr(
        manager,
        "process_expirations",
        lambda *_: (_ for _ in ()).throw(AssertionError("navigate-only must not run housekeeping")),
    )
    monkeypatch.setattr(
        navigation,
        "open_army_training_screen",
        lambda execute: {"status": "BARRACKS_OPENED", "actions_executed": execute},
    )
    monkeypatch.setattr(
        live,
        "capture_primary_monitor",
        lambda: (_ for _ in ()).throw(AssertionError("navigate-only must not evaluate goals")),
    )
    args = SimpleNamespace(
        profile="p", execute=True, confirm=manager.CONFIRMATION_PHRASE, navigate_only=True,
    )

    result = manager._command_execute(args, tmp_path, NOW)

    assert result["status"] == "BARRACKS_OPENED"
    assert result["queue_modified"] is False
    assert result["navigation"]["actions_executed"] is True


def test_execute_requires_confirmation_before_any_navigation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        navigation,
        "open_army_training_screen",
        lambda **kwargs: calls.append(kwargs),
    )
    args = SimpleNamespace(profile="p", execute=True, confirm="wrong", navigate_only=True)

    result = manager._command_execute(args, tmp_path, NOW)

    assert result["status"] == "BLOCKED_CONFIRMATION"
    assert result["actions_executed"] is False
    assert calls == []


def test_execute_preview_only_reports_navigation_without_capturing_screen(monkeypatch, tmp_path):
    queue = create_task_queue("p")
    queue_path = tmp_path / "tasks.json"
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, queue_path))
    monkeypatch.setattr(manager, "army_state_path", lambda *_: tmp_path / "army_state.json")
    monkeypatch.setattr(
        navigation,
        "open_army_training_screen",
        lambda execute: {"status": "PREVIEW_ONLY", "actions_executed": False},
    )
    monkeypatch.setattr(
        live,
        "capture_primary_monitor",
        lambda: (_ for _ in ()).throw(AssertionError("preview must not inspect the current screen")),
    )
    args = SimpleNamespace(profile="p", execute=False, confirm="", navigate_only=False)

    result = manager._command_execute(args, tmp_path, NOW)

    assert result["status"] == "PREVIEW_ONLY"
    assert result["navigation"]["status"] == "PREVIEW_ONLY"
    assert result["actions_executed"] is False
    assert result["queue_modified"] is False
