from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

import army_training_executor as executor
from army_training_process import NumericReading, Slot, TrainingGoal, enqueue_training_goal
from task_controller import create_task_queue

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


class FakeVariant(dict):
    pass


def _setup(monkeypatch, level=6, click_error_at=None, post_state="active"):
    queue = create_task_queue("p")
    task = enqueue_training_goal(queue, TrainingGoal("p", Slot(level, 1)), NOW)
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    slot = SimpleNamespace(
        index=0, dx=0, dy=0, regions={
            "unit_troop_level": {"x": 100, "y": 100, "w": 30, "h": 120},
            "unit_troop_train_button": {"x": 400, "y": 500, "w": 50, "h": 20},
        },
    )
    layout = SimpleNamespace(status="ok", slots=(slot,))
    variant = FakeVariant(regions="regions.json")
    selector_reading = SimpleNamespace(
        status="candidate", lowest_visible_level=5, highest_visible_level=7,
        badge_centers=((10, 10, 10), (10, 35, 10), (10, 60, 12)),
    )
    monkeypatch.setattr(executor, "resolve_variant", lambda: variant)
    monkeypatch.setattr(executor, "_load_regions", lambda _: {"army_training": {}})
    monkeypatch.setattr(executor, "locate_slots", lambda *args: layout)
    monkeypatch.setattr(executor, "read_slot_selector_levels", lambda *args: selector_reading)
    monkeypatch.setattr(executor, "_build_selected_slot_plan", lambda *args: {"blockers": [], "planned_quantity": 100})
    monkeypatch.setattr(executor, "read_slot_training_time", lambda *args: NumericReading(3600, 100, "1d.0g."))
    monkeypatch.setattr(executor, "_find_same_slot", lambda *args: slot)
    monkeypatch.setattr(executor, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(executor, "_enable_live_failsafe", lambda _: None)
    clicks = []

    def click(point, origin):
        clicks.append((point, origin))
        if click_error_at is not None and len(clicks) == click_error_at:
            raise OSError("click acknowledgement lost")

    def capture():
        return image.copy(), (0, 0)

    return queue, task, clicks, click, capture


def test_execute_selects_target_level_then_train_once_and_marks_started(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch)
    states = iter(({"status": "idle"}, {"status": "idle"}, {"status": "active"}))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args: next(states))

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
    )

    assert result["status"] == "START_CONFIRMED"
    assert result["selection_confirmed"] is False
    assert len(clicks) == 2
    assert queue["tasks"][0]["status"] == "waiting_help_delay"
    assert queue["tasks"][0]["initial_remaining_seconds"] == 3600


def test_train_click_failure_pauses_queue_and_is_not_retried(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch, click_error_at=2)
    states = iter(({"status": "idle"}, {"status": "idle"}))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args: next(states))

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
    )

    assert result["status"] == "UNKNOWN_AFTER_TRAIN_CLICK_ATTEMPT"
    assert queue["paused"] is True
    assert queue["pause_reason"].startswith("uncertain_training_start:")
    assert queue["tasks"][0]["payload"]["process"]["state"] == "blocked"
    assert len(clicks) == 2


def test_unconfirmed_post_click_state_pauses_queue(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch)
    states = iter(({"status": "idle"}, {"status": "idle"}, {"status": "unknown"}))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args: next(states))

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
    )

    assert result["status"] == "UNKNOWN_AFTER_CLICK"
    assert queue["paused"] is True
    assert len(clicks) == 2


def test_missing_or_unreliable_time_blocks_before_train(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch)
    states = iter(({"status": "idle"}, {"status": "idle"}))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args: next(states))
    monkeypatch.setattr(executor, "read_slot_training_time", lambda *args: NumericReading(None, None, "?d.?g."))

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
    )

    assert result["status"] == "BLOCKED_BEFORE_TRAIN"
    assert result["actions_executed"] is True
    assert len(clicks) == 1
    assert queue["tasks"][0]["status"] == "queued"


def test_execute_requires_exact_confirmation_before_capture(monkeypatch):
    queue, task, _, click, _ = _setup(monkeypatch)
    captured = []

    with pytest.raises(executor.LiveTrainingError, match="confirmation phrase"):
        executor.execute_training_goal(
            queue, task["task_id"], NOW, execute=True, confirmation="yes",
            capture_fn=lambda: captured.append(True), click_fn=click,
        )
    assert captured == []
