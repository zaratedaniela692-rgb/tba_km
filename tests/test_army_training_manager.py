from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import army_training_live_e2e as live
import army_training_manager as manager
import army_training_navigation as navigation
import ui_variants
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


def test_resume_save_failure_preserves_persisted_hold_and_budget(monkeypatch, tmp_path):
    from task_controller import record_resource_retry_failure, save_task_queue, task_queue_path

    queue = queue_with((7, 1))
    task_id = queue["tasks"][0]["task_id"]
    for attempt in range(3):
        record_resource_retry_failure(
            queue, task_id, "silver_insufficient", "not_implemented",
            NOW + timedelta(seconds=attempt * queue["settings"]["resource_retry_seconds"]),
        )
    path = task_queue_path("p", tmp_path)
    save_task_queue(queue, path)
    before = path.read_bytes()

    def fail_save(*args):
        raise OSError("test write failure")

    monkeypatch.setattr(manager, "save_task_queue", fail_save)
    with pytest.raises(OSError, match="test write failure"):
        manager._command_resume_army(
            SimpleNamespace(profile="p", confirm="RESUME ARMY TRAINING"), tmp_path, NOW,
        )
    assert path.read_bytes() == before


@pytest.mark.parametrize(("navigate_only", "test_finish"), ((False, False), (True, False), (True, True)))
def test_global_pause_blocks_all_manager_input_before_navigation(monkeypatch, tmp_path, navigate_only, test_finish):
    from task_controller import save_task_queue, task_queue_path

    queue = create_task_queue("test")
    enqueue_training_goal(queue, TrainingGoal("test", Slot("guardsmen", 7, 1)), NOW)
    queue.update(paused=True, pause_reason="operator_pause")
    path = task_queue_path("test", tmp_path)
    save_task_queue(queue, path)
    before = path.read_bytes()
    monkeypatch.setattr(navigation, "open_army_training_screen", lambda **_: pytest.fail("must not navigate"))
    monkeypatch.setattr(live, "capture_primary_monitor", lambda: pytest.fail("must not capture"))
    monkeypatch.setattr(manager, "process_expirations", lambda *_: pytest.fail("must not mutate housekeeping"))
    monkeypatch.setattr(manager, "execute_finish_task", lambda *_args, **_kwargs: pytest.fail("must not finish"))

    result = manager._command_execute(SimpleNamespace(
        profile="test", execute=True, confirm=manager.CONFIRMATION_PHRASE,
        navigate_only=navigate_only, finish_active_for_test=test_finish,
    ), tmp_path, NOW)

    assert result["status"] == "BLOCKED_PAUSED_QUEUE"
    assert result["reason"] == "operator_pause"
    assert result["actions_executed"] is False
    assert result["queue_modified"] is False
    assert path.read_bytes() == before


def test_global_pause_still_allows_manager_preview(monkeypatch, tmp_path):
    queue = queue_with((7, 1))
    queue.update(paused=True, pause_reason="operator_pause")
    before = deepcopy(queue)
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, tmp_path / "tasks.json"))
    calls = []
    monkeypatch.setattr(navigation, "open_army_training_screen", lambda execute: (
        calls.append(execute) or {"status": "PREVIEW_ONLY", "actions_executed": False}
    ))
    result = manager._command_execute(SimpleNamespace(
        profile="p", execute=False, confirm="", navigate_only=False,
    ), tmp_path, NOW)
    assert result["status"] == "PREVIEW_ONLY"
    assert calls == [False]
    assert queue == before


def test_resume_army_requires_confirmation_and_preserves_history_and_other_profile(tmp_path):
    from task_controller import record_resource_retry_failure, save_task_queue, task_queue_path, load_task_queue

    queue = queue_with((7, 1), (7, 2))
    for attempt in range(3):
        record_resource_retry_failure(queue, queue["tasks"][0]["task_id"], "silver_insufficient", "not_implemented",
                                      NOW + timedelta(seconds=attempt * queue["settings"]["resource_retry_seconds"]))
    queue["tasks"][1]["payload"]["process"].update(decision={"old": True}, decision_valid_until=NOW.isoformat())
    path = task_queue_path("p", tmp_path)
    save_task_queue(queue, path)
    before = path.read_bytes()
    listing = manager._command_list(SimpleNamespace(profile="p"), tmp_path, NOW)
    assert listing["army_training_hold"]["reason"].startswith("silver_insufficient")
    assert all(item["training_start_held"] for item in listing["tasks"])
    assert manager._command_resume_army(SimpleNamespace(profile="p", confirm="yes"), tmp_path, NOW)["status"] == "BLOCKED_CONFIRMATION"
    assert manager._command_resume_army(SimpleNamespace(profile="other", confirm="RESUME ARMY TRAINING"), tmp_path, NOW)["status"] == "NO_ARMY_TRAINING_HOLD"
    assert path.read_bytes() == before
    assert manager._command_resume_army(SimpleNamespace(profile="p", confirm="RESUME ARMY TRAINING"), tmp_path, NOW)["status"] == "ARMY_TRAINING_RESUMED"
    saved = load_task_queue(path)
    assert "army_training_hold" not in saved
    assert saved["tasks"][0]["resource_retry_history"][0]["attempts"] == 3
    assert saved["tasks"][0]["resource_retry"]["attempts"] == 0
    assert all(item["payload"]["process"]["decision"] is None for item in saved["tasks"])
    assert manager.build_parser().parse_args(["resume-army", "--confirm", "RESUME ARMY TRAINING"]).handler == manager._command_resume_army


@pytest.mark.parametrize(("seconds_until_check", "respect_next_check", "deferred"), (
    (1, True, True), (0, True, False), (-1, True, False), (1, False, False),
))
def test_goal_retry_deadline_is_checked_before_slot_read(seconds_until_check, respect_next_check, deferred):
    queue = queue_with((7, 1))
    task = queue["tasks"][0]
    task["status"] = "waiting_resources"
    task["next_check_at"] = (NOW + timedelta(seconds=seconds_until_check)).isoformat()
    before = deepcopy(queue)
    observation = frame()
    reads = []
    observation.read_slot = lambda index: reads.append(index) or readings(index)

    result = evaluate_goals(queue, observation, NOW, dry_run=False, respect_next_check=respect_next_check)

    if deferred:
        assert result["goals"][0]["resolution"] == "deferred"
        assert result["goals"][0]["reason"] == "next_check_not_due"
        assert result["goals"][0]["next_check_at"] == task["next_check_at"]
        assert reads == []
        assert queue == before
    else:
        assert reads == [0]
        assert task["next_check_at"] is None
        assert result["goals"][0]["state"] == "needs_preflight"


@pytest.mark.parametrize("pinned", (False, True))
def test_automatic_execution_preserves_deferred_goal_and_can_select_other_due_goal(monkeypatch, tmp_path, pinned):
    queue = queue_with((7, 1), (7, 2))
    if pinned:
        queue["profile_id"] = "test"
    deferred, due = queue["tasks"]
    deferred["priority"] = 1
    due["priority"] = 3
    deferred["status"] = "waiting_resources"
    deferred["next_check_at"] = (NOW + timedelta(hours=1)).isoformat()
    deferred_before = deepcopy(deferred)
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, tmp_path / "tasks.json"))
    monkeypatch.setattr(manager, "process_expirations", lambda *_: {})
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: None)
    monkeypatch.setattr(navigation, "open_army_training_screen", lambda execute: {"status": "BARRACKS_OPENED"})
    monkeypatch.setattr(live, "capture_primary_monitor", lambda: (object(), (0, 0)))
    monkeypatch.setattr(manager, "select_army_type", lambda _: {"status": "DEFAULT_CATEGORY_ASSUMED"})
    observation = frame()
    reads, executed = [], []
    observation.read_slot = lambda index: reads.append(index) or readings(index)
    monkeypatch.setattr(manager, "observe_image", lambda *_args, **_kwargs: observation)
    monkeypatch.setattr(manager, "execute_training_goal", lambda queue, task_id, *args, **kwargs: (
        executed.append(task_id) or {"status": "START_CONFIRMED"}
    ))

    result = manager._command_execute(SimpleNamespace(
        profile="p" if not pinned else "test", execute=True, confirm=manager.CONFIRMATION_PHRASE,
        navigate_only=False, test_task_id=deferred["task_id"] if pinned else None,
    ), tmp_path, NOW)

    assert deferred == deferred_before
    assert reads == [1]
    assert executed == ([] if pinned else [due["task_id"]])
    assert result["status"] == ("NO_EXECUTABLE_GOAL" if pinned else "START_CONFIRMED")


def test_due_category_selection_skips_future_unverified_category():
    queue = create_task_queue("p")
    enqueue_training_goal(queue, TrainingGoal("p", Slot("specialists", 7, 1)), NOW)
    enqueue_training_goal(queue, TrainingGoal("p", Slot("guardsmen", 7, 1)), NOW)
    queue["tasks"][0]["next_check_at"] = (NOW + timedelta(seconds=1)).isoformat()
    before = deepcopy(queue)

    assert manager._next_pending_goal_unit_type(queue, NOW) == "guardsmen"
    assert manager._next_pending_goal_unit_type(queue, NOW + timedelta(seconds=1)) == "specialists"
    assert manager._next_pending_goal_unit_type(queue) == "specialists"
    assert queue == before


@pytest.mark.parametrize("save", (False, True))
def test_manual_image_run_can_observe_future_goal_and_only_persists_when_requested(monkeypatch, tmp_path, save):
    queue = queue_with((7, 1))
    queue["tasks"][0]["next_check_at"] = (NOW + timedelta(hours=1)).isoformat()
    before = deepcopy(queue)
    path = tmp_path / "tasks.json"
    saves = []
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, path))
    monkeypatch.setattr(manager, "_read_image", lambda _: object())
    monkeypatch.setattr(manager, "observe_image", lambda *_args, **_kwargs: frame())
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: saves.append(deepcopy(queue)))

    result = manager._command_run(SimpleNamespace(
        profile="p", image="fixture.png", unit_type="guardsmen", save=save,
    ), tmp_path, NOW)

    assert result["goals"][0]["state"] == "needs_preflight"
    assert len(saves) == int(save)
    if save:
        assert queue["tasks"][0]["next_check_at"] is None
    else:
        assert queue == before


@pytest.mark.parametrize("held", (False, True))
def test_automatic_execution_keeps_due_fallback_precedence(monkeypatch, tmp_path, held):
    from task_controller import enqueue_task

    queue = queue_with((7, 1))
    if held:
        queue["army_training_hold"] = {"at": NOW.isoformat(), "task_id": "old", "reason": "silver_insufficient"}
    queue["tasks"][0]["next_check_at"] = (NOW + timedelta(hours=1)).isoformat()
    fallback = enqueue_task(queue, "army_training", task_id="finish-old", now=NOW,
                            payload={"goal_kind": manager.FALLBACK_GOAL_KIND, "order_id": "old"})
    before = deepcopy(queue)
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, tmp_path / "tasks.json"))
    monkeypatch.setattr(manager, "process_expirations", lambda *_: {})
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: None)
    monkeypatch.setattr(navigation, "open_army_training_screen", lambda execute: {"status": "BARRACKS_OPENED"})
    monkeypatch.setattr(manager, "observe_image", lambda *_args, **_kwargs: pytest.fail("fallback precedes stock reading"))
    calls = []
    monkeypatch.setattr(manager, "execute_finish_task", lambda queue, task_id, *args, **kwargs: (
        calls.append(task_id) or {"status": "FINISHED"}
    ))

    result = manager._command_execute(SimpleNamespace(
        profile="p", execute=True, confirm=manager.CONFIRMATION_PHRASE, navigate_only=False,
    ), tmp_path, NOW)

    assert calls == [fallback["task_id"]]
    assert result["status"] == "FINISHED"
    assert queue == before


def test_resolver_picks_mth_slot_containing_the_level():
    assert resolve_goal_slot(LEVELS, "guardsmen", 5, 1).frame_index == 0
    assert resolve_goal_slot(LEVELS, "guardsmen", 6, 1).frame_index == 0
    assert resolve_goal_slot(LEVELS, "guardsmen", 6, 3).frame_index == 2
    assert resolve_goal_slot(LEVELS, "guardsmen", 7, 2).candidates == (0, 1, 2)


def test_resolver_reports_unsupported_and_blocked_cases():
    assert resolve_goal_slot(LEVELS, "guardsmen", 6, 4).reason == "match_not_visible_without_scrolling"
    assert resolve_goal_slot(LEVELS, "guardsmen", 3, 1).reason == "level_not_in_visible_slots"
    assert resolve_goal_slot(LEVELS, "specialists", 6, 1).reason == "unit_type_slot_map_unverified"
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


def test_test_only_navigation_stage_finishes_active_training_before_returning(monkeypatch, tmp_path):
    queue = create_task_queue("test")
    queue_path = tmp_path / "tasks.json"
    state_path = tmp_path / "army_state.json"
    saves = []
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, queue_path))
    monkeypatch.setattr(manager, "task_queue_path", lambda *_: queue_path)
    monkeypatch.setattr(manager, "create_task_queue", lambda *_: queue)
    monkeypatch.setattr(manager, "army_state_path", lambda *_: state_path)
    monkeypatch.setattr(manager, "save_task_queue", lambda saved_queue, path: saves.append((saved_queue, path)))
    monkeypatch.setattr(
        navigation, "open_army_training_screen",
        lambda execute: {"status": "BARRACKS_OPENED", "actions_executed": True},
    )
    monkeypatch.setattr(live, "capture_primary_monitor", lambda: (object(), (0, 0)))
    states = iter(({"status": "active"},))
    monkeypatch.setattr(live, "_read_current_training_state", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(ui_variants, "resolve_variant", lambda: {"id": "legacy"})
    finish_calls = []
    monkeypatch.setattr(manager, "finish_active_training_for_test", lambda *args: finish_calls.append(args) or {
        "status": "FINISHED", "actions_executed": True,
    })

    result = manager._command_execute(SimpleNamespace(
        profile="test", execute=True, confirm=manager.CONFIRMATION_PHRASE,
        navigate_only=True, finish_active_for_test=True,
    ), tmp_path, NOW)

    assert result["status"] == "TRAINING_FINISHED_FOR_TEST"
    assert result["actions_executed"] is True
    assert len(finish_calls) == 1
    assert saves == [(queue, queue_path)]


def test_test_only_navigation_stage_rejects_other_profiles(monkeypatch, tmp_path):
    queue = create_task_queue("other")
    queue_path = tmp_path / "tasks.json"
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, queue_path))
    monkeypatch.setattr(manager, "army_state_path", lambda *_: tmp_path / "army_state.json")
    monkeypatch.setattr(
        navigation, "open_army_training_screen",
        lambda execute: pytest.fail("profile gate must run before navigation"),
    )

    result = manager._command_execute(SimpleNamespace(
        profile="other", execute=True, confirm=manager.CONFIRMATION_PHRASE,
        navigate_only=True, finish_active_for_test=True,
    ), tmp_path, NOW)

    assert result["status"] == "BLOCKED_TEST_PROFILE_REQUIRED"


@pytest.mark.parametrize("outcome", ("success", "finish_error", "save_error"))
def test_test_finish_preserves_or_reconciles_marker_owned_state(monkeypatch, tmp_path, outcome):
    from army_state import open_training_marker
    from task_controller import enqueue_task, load_task_queue, save_task_queue

    queue = create_task_queue("test")
    task = enqueue_training_goal(queue, TrainingGoal("test", Slot("guardsmen", 7, 1)), NOW)
    queue["tasks"][0]["status"] = "waiting_help_delay"
    enqueue_task(queue, "army_training", task_id="army_finish:order", now=NOW,
                 payload={"goal_kind": manager.FALLBACK_GOAL_KIND, "order_id": "order"})
    unrelated = enqueue_task(queue, "building_upgrade", task_id="keep-building", now=NOW)
    queue_path, state_path = tmp_path / "tasks.json", tmp_path / "army_state.json"
    save_task_queue(queue, queue_path)
    open_training_marker(state_path, "order", task["task_id"], {}, NOW, NOW)
    queue_before, state_before = queue_path.read_bytes(), state_path.read_bytes()
    monkeypatch.setattr(manager, "task_queue_path", lambda *_: queue_path)
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (
        load_task_queue(queue_path, expected_profile_id="test"), queue_path,
    ))
    monkeypatch.setattr(manager, "army_state_path", lambda *_: state_path)
    monkeypatch.setattr(navigation, "open_army_training_screen", lambda execute: {
        "status": "BARRACKS_OPENED", "actions_executed": True,
    })
    monkeypatch.setattr(live, "capture_primary_monitor", lambda: (object(), (0, 0)))

    def finish(*args):
        if outcome == "finish_error":
            raise RuntimeError("uncertain speedup outcome")
        return {"status": "FINISHED", "actions_executed": True}

    monkeypatch.setattr(manager, "finish_active_training_for_test", finish)
    if outcome == "save_error":
        def fail_save(*args):
            raise OSError("queue write failed")
        monkeypatch.setattr(manager, "save_task_queue", fail_save)
    args = SimpleNamespace(profile="test", execute=True, confirm=manager.CONFIRMATION_PHRASE,
                           navigate_only=True, finish_active_for_test=True)
    if outcome == "save_error":
        with pytest.raises(OSError, match="queue write failed"):
            manager._command_execute(args, tmp_path, NOW)
    else:
        result = manager._command_execute(args, tmp_path, NOW)
        assert result["status"] == ("TRAINING_FINISHED_FOR_TEST" if outcome == "success" else "BLOCKED_ACTIVE_TRAINING_FINISH")
    if outcome == "success":
        saved = load_task_queue(queue_path)
        assert [item["status"] for item in saved["tasks"][:2]] == ["completed", "completed"]
        assert saved["tasks"][2] == unrelated
        assert manager.load_army_state(state_path).get("open_training") is None
    else:
        assert queue_path.read_bytes() == queue_before
        assert state_path.read_bytes() == state_before


@pytest.mark.parametrize("target_eligible", (True, False))
def test_e2e_task_pin_never_executes_other_queued_goal(monkeypatch, tmp_path, target_eligible):
    queue = create_task_queue("test")
    other = enqueue_training_goal(queue, TrainingGoal("test", Slot("guardsmen", 7, 1)), NOW)
    target = enqueue_training_goal(queue, TrainingGoal("test", Slot("guardsmen", 7, 2)), NOW)
    monkeypatch.setattr(manager, "_load_or_create_queue", lambda *_: (queue, tmp_path / "tasks.json"))
    monkeypatch.setattr(manager, "process_expirations", lambda *_: {})
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: None)
    monkeypatch.setattr(navigation, "open_army_training_screen", lambda execute: {"status": "BARRACKS_OPENED"})
    monkeypatch.setattr(live, "capture_primary_monitor", lambda: (object(), (0, 0)))
    monkeypatch.setattr(manager, "select_army_type", lambda _: {"status": "DEFAULT_CATEGORY_ASSUMED"})
    monkeypatch.setattr(manager, "observe_image", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(manager, "evaluate_goals", lambda *_args, **_kwargs: {"goals": [
        {"task_id": other["task_id"], "state": "needs_preflight"},
        {"task_id": target["task_id"], "state": "needs_preflight" if target_eligible else "blocked"},
    ]})
    calls = []
    monkeypatch.setattr(manager, "execute_training_goal", lambda queue, task_id, *args, **kwargs: (
        calls.append(task_id) or {"status": "START_CONFIRMED"}
    ))

    result = manager._command_execute(SimpleNamespace(
        profile="test", execute=True, confirm=manager.CONFIRMATION_PHRASE, navigate_only=False,
        finish_active_for_test=False, test_task_id=target["task_id"],
    ), tmp_path, NOW)

    assert calls == ([target["task_id"]] if target_eligible else [])
    assert result["status"] == ("START_CONFIRMED" if target_eligible else "NO_EXECUTABLE_GOAL")


@pytest.mark.parametrize("barracks_confirmed", (False, True))
def test_finish_stage_blocks_before_persistence_without_confirmed_idle(monkeypatch, tmp_path, barracks_confirmed):
    queue = create_task_queue("test")
    capture_calls, finish_calls = [], []
    monkeypatch.setattr(manager, "save_task_queue", lambda *_: pytest.fail("must not save without confirmed idle"))
    monkeypatch.setattr(manager, "load_army_state", lambda *_: pytest.fail("must not reconcile marker without confirmed idle"))

    def capture():
        capture_calls.append(True)
        return object(), (0, 0)

    def finish(*args):
        finish_calls.append(True)
        return {"status": "UNCERTAIN", "actions_executed": True}

    monkeypatch.setattr(manager, "finish_active_training_for_test", finish)
    navigation_result = {
        "status": "BARRACKS_OPENED" if barracks_confirmed else "BLOCKED_BARRACKS_NOT_CONFIRMED",
        "actions_executed": True,
    }
    result = manager._finish_test_training(
        queue, tmp_path / "tasks.json", tmp_path / "army_state.json", "test", NOW,
        navigation_result, capture,
    )

    assert capture_calls == ([True] if barracks_confirmed else [])
    assert finish_calls == ([True] if barracks_confirmed else [])
    assert result["status"] == ("BLOCKED_ACTIVE_TRAINING_FINISH" if barracks_confirmed else "BLOCKED_TASK_STARTUP")
    assert result["queue_modified"] is False
    assert result["navigation"] == navigation_result
    assert queue["tasks"] == []


@pytest.mark.parametrize("order", ("priority", "created_at", "report_tie"))
def test_goal_selection_preserves_ordering_without_mutation(order):
    queue = queue_with((7, 1), (7, 2))
    first, second = queue["tasks"]
    first["priority"], second["priority"] = (3, 1) if order == "priority" else (1, 1)
    second["created_at"] = (NOW - timedelta(seconds=1)).isoformat() if order == "created_at" else first["created_at"]
    report = {"goals": [
        {"task_id": second["task_id"], "state": "blocked", "reason": "selection_unverified"},
        {"task_id": first["task_id"], "state": "needs_preflight"},
    ]}
    before = deepcopy((queue, report))

    assert manager._select_executable_goal(queue, report) == second["task_id"]
    assert manager._select_executable_goal(queue, report, first["task_id"]) == first["task_id"]
    assert manager._select_executable_goal(queue, report, "missing") is None
    assert (queue, report) == before


def test_due_finish_selection_keeps_list_order_and_future_checks():
    from task_controller import enqueue_task

    queue = create_task_queue("p")
    for task_id in ("future", "first-due", "higher-priority-due"):
        enqueue_task(queue, "army_training", task_id=task_id, now=NOW,
                     payload={"goal_kind": manager.FALLBACK_GOAL_KIND, "order_id": task_id})
    queue["tasks"][0]["next_check_at"] = (NOW + timedelta(seconds=1)).isoformat()
    queue["tasks"][1]["priority"] = 5
    queue["tasks"][2]["priority"] = 1
    queue["tasks"][2]["next_check_at"] = NOW.isoformat()
    before = deepcopy(queue)

    assert manager._next_due_finish_task(queue, NOW) is queue["tasks"][1]
    assert manager._next_due_finish_task(queue, NOW + timedelta(seconds=1)) is queue["tasks"][0]
    assert queue == before


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
        lambda unit_type: events.append(("select", unit_type)) or {
            "status": "DEFAULT_CATEGORY_ASSUMED", "unit_type": unit_type,
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
    enqueue_training_goal(queue, TrainingGoal("p", Slot("specialists", 5, 1)), NOW)
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
    assert result["category_selection"]["unit_type"] == "specialists"
    assert result["actions_executed"] is False
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
