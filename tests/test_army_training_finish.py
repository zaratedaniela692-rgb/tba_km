from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

import army_training_executor as executor
import army_training_finish as finish
from army_state import (
    army_state_path,
    load_army_state,
    open_training,
    open_training_marker,
    record_finish_button_attempt,
)
from army_training_process import NumericReading, Slot, TrainingGoal, enqueue_training_goal
from task_controller import (
    create_task_queue,
    enqueue_task,
    expire_tasks,
    get_next_task,
    mark_task_started,
    validate_task_queue,
)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
WINDOW = 30 * 60


def started_task(queue, window=None):
    task = enqueue_task(queue, "army_training", now=NOW, help_window_seconds=window)
    mark_task_started(queue, task["task_id"], 3600, now=NOW)
    return queue["tasks"][-1]


def marker(tmp_path, task=None, expires_in=WINDOW):
    path = army_state_path("p", tmp_path)
    open_training_marker(path, "order-1", "t", {"global_level": 7, "match_number": 1}, NOW, NOW + timedelta(seconds=expires_in))
    return path


def test_task_expires_at_help_window_after_post_order_delay():
    queue = create_task_queue("p", post_order_delay_seconds=2)
    task = started_task(queue)

    assert task["expires_at"] == (NOW + timedelta(seconds=2 + WINDOW)).isoformat()
    assert expire_tasks(queue, NOW + timedelta(seconds=WINDOW)) == []
    expired = expire_tasks(queue, NOW + timedelta(seconds=2 + WINDOW))

    assert [item["task_id"] for item in expired] == [task["task_id"]]
    assert task["status"] == "completed"
    assert task["completed_reason"] == "window_expired"


def test_per_task_window_overrides_default_and_expiry_frees_the_same_type_gate():
    queue = create_task_queue("p")
    first = started_task(queue, window=60)
    second = enqueue_task(queue, "army_training", now=NOW)

    assert get_next_task(queue, {}, now=NOW + timedelta(seconds=30)) is None
    expire_tasks(queue, NOW + timedelta(seconds=120))
    assert get_next_task(queue, {}, now=NOW + timedelta(seconds=120))["task_id"] == second["task_id"]
    assert first["completed_reason"] == "window_expired"


def test_legacy_task_without_expiry_fields_still_validates():
    queue = create_task_queue("p")
    task = enqueue_task(queue, "army_training", now=NOW)
    for key in ("expires_at", "help_window_seconds", "completed_reason"):
        del task[key]

    assert validate_task_queue(queue) is True
    assert expire_tasks(queue, NOW + timedelta(days=30)) == []


def test_finish_clears_marker_when_idle_and_blocks_foreign_training(tmp_path):
    path = marker(tmp_path)
    foreign = army_state_path("other", tmp_path)

    assert finish.finish_open_training(foreign, "active", None, NOW)["reason"] == "foreign_training_active"
    assert finish.finish_open_training(path, "idle", None, NOW)["marker_cleared"] is True
    assert open_training(load_army_state(path)) is None


def test_failed_speedup_keeps_marker_and_schedules_hourly_retry(tmp_path):
    path = marker(tmp_path)

    first = finish.finish_open_training(path, "active", None, NOW)
    waiting = finish.finish_open_training(path, "active", lambda: "idle", NOW + timedelta(minutes=30))

    assert first["reason"] == "speedup_module_unavailable"
    assert first["next_attempt_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert first["actions_attempted"] is False
    assert waiting["status"] == "waiting"
    assert open_training(load_army_state(path)) is not None


def test_speedup_confirmed_idle_clears_marker_and_unconfirmed_counts_attempt(tmp_path):
    path = marker(tmp_path)
    unconfirmed = finish.finish_open_training(path, "active", lambda: "active", NOW, attention_after=1)
    done = finish.finish_open_training(path, "active", lambda: "idle", NOW + timedelta(hours=1))

    assert unconfirmed["needs_attention"] is True and unconfirmed["attempts"] == 1
    assert done["status"] == "finished"
    assert open_training(load_army_state(path)) is None


def test_unconfirmed_finish_button_click_is_persisted_and_never_retried(tmp_path):
    path = marker(tmp_path)

    def click_finish(on_finish_button_click):
        on_finish_button_click()
        return "unknown"

    first = finish.finish_open_training(
        path, "active", click_finish, NOW,
        before_finish_button_click=lambda: record_finish_button_attempt(path, NOW),
    )
    second = finish.finish_open_training(
        path, "active", lambda: pytest.fail("must not retry after an uncertain finish click"),
        NOW + timedelta(hours=2),
    )

    assert first["status"] == "failed"
    assert second["reason"] == "finish_button_already_attempted"
    assert second["actions_attempted"] is False
    assert second["needs_attention"] is True
    assert open_training(load_army_state(path))["finish_button_attempted_at"] == NOW.isoformat()


def test_execute_finish_task_passes_one_shot_recorder_to_speedup_adapter(tmp_path, monkeypatch):
    queue = create_task_queue("p")
    task = enqueue_task(
        queue, "army_training", task_id="army_finish:order-1", now=NOW,
        payload={"goal_kind": finish.FALLBACK_GOAL_KIND, "order_id": "order-1"},
    )
    path = marker(tmp_path)
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    adapter_calls = []
    states = iter(("active", "unknown"))
    monkeypatch.setattr(finish, "resolve_variant", lambda: {"regions": "regions.json"})
    monkeypatch.setattr(finish, "_read_current_training_state", lambda *_: {"status": next(states)})
    monkeypatch.setattr(finish, "_check_emergency_stop", lambda: None)

    def speedup_adapter(**kwargs):
        adapter_calls.append(kwargs)
        kwargs["on_finish_button_click"]()
        return "unknown"

    first = finish.execute_finish_task(
        queue, task["task_id"], path, NOW, execute=True,
        confirmation=finish.CONFIRMATION_PHRASE,
        capture_fn=lambda: (image, (0, 0)), speedup_fn=speedup_adapter, sleep_fn=lambda _: None,
    )
    second = finish.execute_finish_task(
        queue, task["task_id"], path, NOW + timedelta(hours=2), execute=True,
        confirmation=finish.CONFIRMATION_PHRASE,
        capture_fn=lambda: (image, (0, 0)),
        speedup_fn=lambda **_: pytest.fail("must not invoke the adapter after an uncertain finish click"),
        sleep_fn=lambda _: None,
    )

    assert first["status"] == "FAILED"
    assert first["actions_executed"] is True
    assert len(adapter_calls) == 1
    assert set(adapter_calls[0]) == {"on_finish_button_click"}
    assert callable(adapter_calls[0]["on_finish_button_click"])
    assert second["finish"]["reason"] == "finish_button_already_attempted"


def test_speedup_exception_is_a_failed_attempt_not_a_crash(tmp_path):
    path = marker(tmp_path)

    def boom():
        raise OSError("dialog missing")

    result = finish.finish_open_training(path, "active", boom, NOW)
    assert result["status"] == "failed" and result["reason"].startswith("speedup_error")


def test_fallback_task_is_created_once_after_grace_and_does_not_pause_the_queue(tmp_path):
    queue = create_task_queue("p", post_order_delay_seconds=2)
    task = started_task(queue)
    path = marker(tmp_path, expires_in=2 + WINDOW)
    before_grace = NOW + timedelta(seconds=2 + WINDOW + 599)
    after_grace = NOW + timedelta(seconds=2 + WINDOW + 600)

    assert finish.process_expirations(queue, path, before_grace)["fallback_created"] is None
    assert task["status"] == "completed"
    created = finish.process_expirations(queue, path, after_grace)["fallback_created"]
    again = finish.process_expirations(queue, path, after_grace)["fallback_created"]

    assert created == "army_finish:order-1" and again is None
    assert queue["paused"] is False
    assert sum(item["task_id"] == created for item in queue["tasks"]) == 1


def test_fallback_is_noop_when_marker_was_already_cleared(tmp_path):
    queue = create_task_queue("p")
    path = marker(tmp_path)
    task = enqueue_task(
        queue, "army_training", task_id="army_finish:order-1", now=NOW,
        payload={"goal_kind": finish.FALLBACK_GOAL_KIND, "order_id": "order-1"},
    )
    finish.finish_open_training(path, "idle", None, NOW)

    result = finish.execute_finish_task(queue, task["task_id"], path, NOW, execute=True)

    assert result["status"] == "NOOP_MARKER_CLEARED" and result["actions_executed"] is False
    assert queue["tasks"][0]["completed_reason"] == "marker_already_cleared"


def test_fallback_schedules_retry_without_speedup_adapter(tmp_path, monkeypatch):
    queue = create_task_queue("p")
    path = marker(tmp_path)
    task = enqueue_task(
        queue, "army_training", task_id="army_finish:order-1", now=NOW,
        payload={"goal_kind": finish.FALLBACK_GOAL_KIND, "order_id": "order-1"},
    )
    monkeypatch.setattr(finish, "resolve_variant", lambda: {})
    monkeypatch.setattr(finish, "_read_current_training_state", lambda frame, variant: {"status": "active"})

    result = finish.execute_finish_task(
        queue, task["task_id"], path, NOW, execute=True, confirmation=finish.CONFIRMATION_PHRASE,
        capture_fn=lambda: (np.zeros((1080, 1920, 3), dtype=np.uint8), (0, 0)),
    )

    assert result["status"] == "FAILED" and result["actions_executed"] is False
    assert queue["tasks"][0]["next_check_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert get_next_task(queue, {}, now=NOW + timedelta(minutes=30)) is None
    assert get_next_task(queue, {}, now=NOW + timedelta(hours=1))["task_id"] == task["task_id"]


def _executor_setup(monkeypatch, states):
    queue = create_task_queue("p")
    enqueue_training_goal(queue, TrainingGoal("p", Slot("guardsmen", 7, 1)), NOW)
    slot = SimpleNamespace(index=0, dx=0, dy=0, regions={
        "unit_troop_level": {"x": 100, "y": 100, "w": 30, "h": 120},
        "unit_troop_train_button": {"x": 400, "y": 500, "w": 50, "h": 20},
    })
    reading = SimpleNamespace(
        status="candidate", lowest_visible_level=5, highest_visible_level=7,
        badge_centers=((10, 10, 10), (10, 35, 10), (10, 60, 12)),
    )
    iterator = iter(states)
    monkeypatch.setattr(executor, "resolve_variant", lambda: {"regions": "x"})
    monkeypatch.setattr(executor, "_load_regions", lambda _: {"army_training": {}})
    monkeypatch.setattr(executor, "locate_slots", lambda *args: SimpleNamespace(status="ok", slots=(slot,)))
    monkeypatch.setattr(executor, "read_selected_category", lambda *args: {"unit_type": "guardsmen"})
    monkeypatch.setattr(executor, "read_slot_selector_levels", lambda *args: reading)
    def read_state(*args, **kwargs):
        value = next(iterator)
        if isinstance(value, dict):
            return value
        if value == "help":
            return {
                "status": "active", "button_state": "help",
                "training_button_region": {"x": 1080, "y": 288, "w": 129, "h": 33},
            }
        if value == "speedup":
            return {
                "status": "active", "button_state": "speedup",
                "training_button_region": {"x": 1080, "y": 288, "w": 129, "h": 33},
            }
        return {"status": value}

    monkeypatch.setattr(executor, "_read_current_training_state", read_state)
    monkeypatch.setattr(executor, "_build_selected_slot_plan", lambda *args: {"blockers": []})
    monkeypatch.setattr(executor, "read_slot_training_time", lambda *args: NumericReading(3600, 100, "1d.0g."))
    monkeypatch.setattr(executor, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(executor, "_enable_live_failsafe", lambda _: None)
    clicks = []
    capture = lambda: (np.zeros((1080, 1920, 3), dtype=np.uint8), (0, 0))
    return queue, clicks, capture, lambda point, origin: clicks.append(point)


def test_executor_records_marker_after_confirmed_start(tmp_path, monkeypatch):
    queue, clicks, capture, click = _executor_setup(
        monkeypatch, ["idle", "idle", "active", "help", "speedup"],
    )
    path = army_state_path("p", tmp_path)

    result = executor.execute_training_goal(
        queue, "army_stock:unit_guardsmen:level_7:match_1", NOW, execute=True, confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None, state_path=path,
    )

    stored = open_training(load_army_state(path))
    assert result["status"] == "START_CONFIRMED"
    assert stored["task_id"] == "army_stock:unit_guardsmen:level_7:match_1"
    assert stored["expires_at"] == queue["tasks"][0]["expires_at"]


def test_executor_blocks_on_foreign_training_without_clicking(tmp_path, monkeypatch):
    queue, clicks, capture, click = _executor_setup(monkeypatch, ["active"])
    path = army_state_path("p", tmp_path)

    result = executor.execute_training_goal(
        queue, "army_stock:unit_guardsmen:level_7:match_1", NOW, execute=True, confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None, state_path=path,
    )

    assert result["status"] == "BLOCKED_PENDING_FINISH"
    assert result["blockers"] == ["foreign_training_active"]
    assert clicks == []


def test_executor_finishes_previous_training_then_starts_next(tmp_path, monkeypatch):
    queue, clicks, capture, click = _executor_setup(
        monkeypatch, ["active", "idle", "idle", "active", "help", "speedup"],
    )
    path = army_state_path("p", tmp_path)
    open_training_marker(path, "old", "old-task", {}, NOW - timedelta(hours=1), NOW - timedelta(minutes=30))

    result = executor.execute_training_goal(
        queue, "army_stock:unit_guardsmen:level_7:match_1", NOW, execute=True, confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None, state_path=path,
        speedup_fn=lambda: "idle",
    )

    assert result["status"] == "START_CONFIRMED"
    assert result["finish"]["status"] == "finished"
    assert open_training(load_army_state(path))["order_id"].startswith("army_stock:unit_guardsmen:level_7:match_1@")
    assert len(clicks) == 2


def test_executor_unavailable_speedup_blocks_goal_until_next_attempt(tmp_path, monkeypatch):
    queue, clicks, capture, click = _executor_setup(monkeypatch, ["active"])
    path = army_state_path("p", tmp_path)
    open_training_marker(path, "old", "old-task", {}, NOW - timedelta(hours=1), NOW - timedelta(minutes=30))

    result = executor.execute_training_goal(
        queue, "army_stock:unit_guardsmen:level_7:match_1", NOW, execute=True, confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None, state_path=path,
    )

    assert result["status"] == "BLOCKED_PENDING_FINISH"
    assert result["blockers"] == ["speedup_module_unavailable"]
    assert queue["paused"] is False
    assert queue["tasks"][0]["next_check_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert clicks == []
