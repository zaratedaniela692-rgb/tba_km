from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

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
        enqueue_training_goal(queue, TrainingGoal("p", Slot("guardsmen", level_number, match)), NOW)
    return queue


def test_resolver_picks_mth_slot_containing_the_level():
    assert resolve_goal_slot(LEVELS, "guardsmen", 5, 1).frame_index == 0
    assert resolve_goal_slot(LEVELS, "guardsmen", 6, 1).frame_index == 0
    assert resolve_goal_slot(LEVELS, "guardsmen", 6, 3).frame_index == 2
    assert resolve_goal_slot(LEVELS, "guardsmen", 7, 2).candidates == (0, 1, 2)


def test_resolver_reports_unsupported_and_blocked_cases():
    assert resolve_goal_slot(LEVELS, "guardsmen", 6, 4).reason == "match_not_visible_without_scrolling"
    assert resolve_goal_slot(LEVELS, "guardsmen", 3, 1).reason == "level_not_in_visible_slots"
    assert resolve_goal_slot(LEVELS, "dragons", 6, 1).reason == "unit_type_slot_map_unverified"
    uncertain = (level(5, 7), SelectorLevelReading("unknown", "x", (), None))
    assert resolve_goal_slot(uncertain, "guardsmen", 6, 1).status == "blocked"
    gap = (SelectorLevelReading("candidate", "ok", (), None, 7, 6, 90, None),)
    assert resolve_goal_slot(gap, "guardsmen", 7, 1).status == "blocked"


def test_adapter_shares_the_slot_limit_between_levels_and_marks_selection():
    observation = build_slot_observation("p", Slot("guardsmen", 6, 1), LEVELS[0], readings(0), "idle", NOW, "test")
    assert observation.selection_verified is False
    assert {observation.queue_limits[key].value for key in (6, 7)} == {1565}

    at_max = build_slot_observation("p", Slot("guardsmen", 7, 1), LEVELS[0], readings(0), "idle", NOW, "test")
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
    assert get_next_task(queue, {}, now=NOW)["task_id"] == "army_stock:unit_guardsmen:level_7:match_1"


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


def test_remove_command_removes_only_the_requested_inactive_task(monkeypatch, tmp_path):
    queue = queue_with((7, 1), (7, 2))
    queue_path = tmp_path / "tasks.json"
    saves = []
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, queue_path))
    monkeypatch.setattr(manager, "save_task_queue", lambda saved_queue, path: saves.append((saved_queue, path)))
    args = SimpleNamespace(profile="p", unit_type="guardsmen", level=7, match=1)

    result = manager._command_remove(args, tmp_path, NOW)

    assert result["status"] == "TASK_REMOVED"
    assert result["queue_modified"] is True
    assert [task["task_id"] for task in queue["tasks"]] == ["army_stock:unit_guardsmen:level_7:match_2"]
    assert saves == [(queue, queue_path)]


def test_remove_command_refuses_active_or_missing_task_without_saving(monkeypatch, tmp_path):
    queue = queue_with((7, 1))
    queue["tasks"][0]["status"] = "waiting_completion"
    queue_path = tmp_path / "tasks.json"
    saves = []
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, queue_path))
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: saves.append(True))

    active_result = manager._command_remove(
        SimpleNamespace(profile="p", unit_type="guardsmen", level=7, match=1), tmp_path, NOW,
    )
    missing_result = manager._command_remove(
        SimpleNamespace(profile="p", unit_type="guardsmen", level=7, match=2), tmp_path, NOW,
    )

    assert active_result["status"] == "BLOCKED_ACTIVE_TASK"
    assert missing_result["status"] == "TASK_NOT_FOUND"
    assert saves == []


def test_clear_command_requires_confirmation_and_preserves_queue_settings(monkeypatch, tmp_path):
    queue = queue_with((7, 1), (7, 2))
    queue["tasks"][1]["status"] = "completed"
    original_settings = dict(queue["settings"])
    queue_path = tmp_path / "tasks.json"
    saves = []
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, queue_path))
    monkeypatch.setattr(manager, "save_task_queue", lambda saved_queue, path: saves.append((saved_queue, path)))

    blocked = manager._command_clear(SimpleNamespace(profile="p", confirm=""), tmp_path, NOW)
    cleared = manager._command_clear(
        SimpleNamespace(profile="p", confirm=manager.CLEAR_QUEUE_CONFIRMATION), tmp_path, NOW,
    )

    assert blocked["status"] == "BLOCKED_CONFIRMATION"
    assert blocked["queue_modified"] is False
    assert cleared["status"] == "QUEUE_CLEARED"
    assert cleared["removed_tasks"] == 2
    assert queue["tasks"] == []
    assert queue["profile_id"] == "p"
    assert queue["settings"] == original_settings
    assert saves == [(queue, queue_path)]


def test_clear_command_refuses_paused_or_active_queue_without_saving(monkeypatch, tmp_path):
    queue = queue_with((7, 1))
    queue_path = tmp_path / "tasks.json"
    saves = []
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, queue_path))
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: saves.append(True))
    args = SimpleNamespace(profile="p", confirm=manager.CLEAR_QUEUE_CONFIRMATION)

    queue["paused"] = True
    queue["pause_reason"] = "uncertain_training"
    paused_result = manager._command_clear(args, tmp_path, NOW)

    queue["paused"] = False
    queue["pause_reason"] = None
    queue["tasks"][0]["status"] = "waiting_completion"
    active_result = manager._command_clear(args, tmp_path, NOW)

    assert paused_result["status"] == "BLOCKED_QUEUE_PAUSED"
    assert active_result["status"] == "BLOCKED_ACTIVE_TASKS"
    assert active_result["active_task_ids"] == ["army_stock:unit_guardsmen:level_7:match_1"]
    assert saves == []


def test_list_command_shows_typed_and_legacy_goals_without_migrating_or_saving(monkeypatch, tmp_path):
    queue = queue_with((7, 1))
    typed_task = queue["tasks"][0]
    legacy_task = dict(typed_task)
    legacy_task["task_id"] = "army_stock:level_6:match_1"
    legacy_task["payload"] = {
        **typed_task["payload"],
        "slot": {"global_level": 6, "match_number": 1},
    }
    queue["tasks"].append(legacy_task)
    queue_path = tmp_path / "tasks.json"
    queue_path.touch()
    saves = []
    monkeypatch.setattr(manager, "task_queue_path", lambda *_: queue_path)
    monkeypatch.setattr(manager, "load_task_queue", lambda *_, **__: queue)
    monkeypatch.setattr(manager, "save_task_queue", lambda *args: saves.append(args))
    args = SimpleNamespace(profile="p")

    report = manager._command_list(args, tmp_path, NOW)

    assert report["status"] == "QUEUE_LISTED"
    assert report["task_count"] == 2
    assert report["queue_modified"] is False
    assert report["tasks"][0]["unit_type"] == "guardsmen"
    assert (report["tasks"][1]["unit_type"], report["tasks"][1]["level"]) == ("guardsmen", 6)
    assert "unit_type" not in legacy_task["payload"]["slot"]
    assert saves == []


def test_list_command_reports_missing_queue_without_creating_file(monkeypatch, tmp_path):
    queue_path = tmp_path / "missing" / "tasks.json"
    monkeypatch.setattr(manager, "task_queue_path", lambda *_: queue_path)
    monkeypatch.setattr(
        manager, "load_task_queue",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("missing queue must not be loaded")),
    )

    report = manager._command_list(SimpleNamespace(profile="p"), tmp_path, NOW)

    assert report["status"] == "QUEUE_EMPTY"
    assert report["queue_exists"] is False
    assert report["tasks"] == []
    assert report["queue_modified"] is False
    assert queue_path.exists() is False


def test_category_hook_runs_after_barracks_and_before_capture(monkeypatch, tmp_path):
    queue = queue_with((7, 1))
    events = []
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, tmp_path / "tasks.json"))
    monkeypatch.setattr(manager, "process_expirations", lambda *_: {})
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: None)
    monkeypatch.setattr(manager, "army_state_path", lambda *_: tmp_path / "army_state.json")
    monkeypatch.setattr(navigation, "open_army_training_screen", lambda **_: {"status": "BARRACKS_OPENED"})
    monkeypatch.setattr(
        manager, "select_army_type",
        lambda unit_type, execute=False: events.append(("select", unit_type)) or {
            "status": "CATEGORY_CONFIRMED", "unit_type": unit_type,
        },
    )
    monkeypatch.setattr(live, "capture_primary_monitor", lambda: events.append(("capture",)) or (object(), (0, 0)))
    monkeypatch.setattr(
        manager, "observe_image",
        lambda image, now, unit_type: events.append(("observe", unit_type)) or frame(),
    )
    monkeypatch.setattr(manager, "evaluate_goals", lambda *args, **kwargs: {"goals": []})
    args = SimpleNamespace(profile="p", execute=True, confirm=manager.CONFIRMATION_PHRASE, navigate_only=False)

    result = manager._command_execute(args, tmp_path, NOW)

    assert result["status"] == "NO_EXECUTABLE_GOAL"
    assert events == [("select", "guardsmen"), ("capture",), ("observe", "guardsmen")]
    assert result["category_selection"]["unit_type"] == "guardsmen"


def test_category_hook_blocks_unverified_type_before_capture(monkeypatch, tmp_path):
    queue = create_task_queue("p")
    enqueue_training_goal(queue, TrainingGoal("p", Slot("dragons", 5, 1)), NOW)
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, tmp_path / "tasks.json"))
    monkeypatch.setattr(manager, "process_expirations", lambda *_: {})
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: None)
    monkeypatch.setattr(manager, "army_state_path", lambda *_: tmp_path / "army_state.json")
    monkeypatch.setattr(navigation, "open_army_training_screen", lambda **_: {"status": "BARRACKS_OPENED"})
    monkeypatch.setattr(
        live, "capture_primary_monitor",
        lambda: (_ for _ in ()).throw(AssertionError("unsupported category must not scan slots")),
    )
    args = SimpleNamespace(profile="p", execute=True, confirm=manager.CONFIRMATION_PHRASE, navigate_only=False)

    result = manager._command_execute(args, tmp_path, NOW)

    assert result["status"] == "BLOCKED_CATEGORY_SELECTION_UNIMPLEMENTED"
    assert result["category_selection"]["unit_type"] == "dragons"
    assert result["actions_executed"] is False
    assert result["queue_modified"] is False


@pytest.mark.parametrize("status", ["CATEGORY_WOULD_SELECT", "BLOCKED_CATEGORY_NOT_CONFIRMED", "BLOCKED_BARRACKS_NOT_CONFIRMED"])
def test_unconfirmed_category_blocks_before_capture(monkeypatch, tmp_path, status):
    queue = create_task_queue("p")
    enqueue_training_goal(queue, TrainingGoal("p", Slot("specialists", 5, 1)), NOW)
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, tmp_path / "tasks.json"))
    monkeypatch.setattr(manager, "process_expirations", lambda *_: {})
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: None)
    monkeypatch.setattr(manager, "army_state_path", lambda *_: tmp_path / "army_state.json")
    monkeypatch.setattr(navigation, "open_army_training_screen", lambda **_: {"status": "BARRACKS_OPENED"})
    monkeypatch.setattr(
        manager, "select_army_type",
        lambda unit_type, execute=False: {"status": status, "unit_type": unit_type, "actions_executed": True},
    )
    monkeypatch.setattr(
        live, "capture_primary_monitor",
        lambda: (_ for _ in ()).throw(AssertionError("unconfirmed category must not scan slots")),
    )
    args = SimpleNamespace(profile="p", execute=True, confirm=manager.CONFIRMATION_PHRASE, navigate_only=False)

    result = manager._command_execute(args, tmp_path, NOW)

    assert result["status"] == status
    assert result["actions_executed"] is True
    assert result["queue_modified"] is False


def test_enqueue_cli_requires_and_persists_unit_type(tmp_path):
    parser = manager.build_parser()
    args = parser.parse_args([
        "--profile", "p", "--profiles-dir", str(tmp_path), "enqueue",
        "--unit-type", "specialists", "--level", "5", "--match", "1",
    ])

    result = args.handler(args, tmp_path, NOW)
    assert result["unit_type"] == "specialists"
    assert result["task_id"] == "army_stock:unit_specialists:level_5:match_1"


def test_remove_cli_requires_unit_type_and_goal_coordinates():
    parser = manager.build_parser()
    args = parser.parse_args([
        "--profile", "p", "remove", "--unit-type", "guardsmen", "--level", "8", "--match", "2",
    ])
    assert (args.unit_type, args.level, args.match) == ("guardsmen", 8, 2)


def test_expand_reads_max_level_for_campaign_unit_type(monkeypatch, tmp_path):
    campaign = manager.Campaign("specialists", "max")
    observed_types = []
    monkeypatch.setattr(manager, "campaign_path", lambda *_: tmp_path / "campaign.json")
    monkeypatch.setattr(manager, "load_campaign", lambda _: campaign)
    monkeypatch.setattr(manager, "army_state_path", lambda *_: tmp_path / "army_state.json")
    monkeypatch.setattr(manager, "_read_image", lambda _: object())
    monkeypatch.setattr(
        manager, "observe_image",
        lambda image, now, unit_type: observed_types.append(unit_type) or frame(),
    )
    monkeypatch.setattr(manager, "frame_max_level", lambda _: 7)
    monkeypatch.setattr(manager, "save_max_level", lambda *args: None)
    monkeypatch.setattr(manager, "load_army_state", lambda _: {})
    monkeypatch.setattr(manager, "resolve_max_level", lambda unit_type, fresh, state, now: SimpleNamespace(
        status="ok", level=fresh, source="fresh",
    ))
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (create_task_queue("p"), tmp_path / "tasks.json"))
    monkeypatch.setattr(manager, "expand_campaign", lambda *args: [])
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: None)
    args = SimpleNamespace(profile="p", image="barracks.png")

    result = manager._command_expand(args, tmp_path, NOW)

    assert result["status"] == "ok"
    assert observed_types == ["specialists"]
