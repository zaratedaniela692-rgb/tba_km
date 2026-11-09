from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

import army_training_executor as executor
from army_training_process import NumericReading, Slot, TrainingGoal, enqueue_training_goal
from army_training_slot_reader import SlotReadings
from task_controller import create_task_queue

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


class FakeVariant(dict):
    pass


def _setup(monkeypatch, level=6, click_error_at=None, post_state="active"):
    queue = create_task_queue("p")
    task = enqueue_training_goal(queue, TrainingGoal("p", Slot("guardsmen", level, 1)), NOW)
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    slot = SimpleNamespace(
        index=0, dx=0, dy=0, regions={
            "unit_troop_level": {"x": 100, "y": 100, "w": 30, "h": 120},
            "unit_troop_count_to_train": {"x": 300, "y": 400, "w": 80, "h": 24},
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
    monkeypatch.setattr(
        executor, "_build_selected_slot_plan",
        lambda *args, **kwargs: {"blockers": [], "planned_quantity": kwargs.get("requested_quantity", 1565)},
    )
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
    button_region = {"x": 1080, "y": 288, "w": 129, "h": 33}
    states = iter((
        {"status": "idle"},
        {"status": "idle"},
        {"status": "active"},
        {"status": "active", "button_state": "help", "training_button_region": button_region},
        {"status": "active", "button_state": "speedup", "training_button_region": button_region},
    ))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))
    sleeps = []

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=sleeps.append,
    )

    assert result["status"] == "START_CONFIRMED"
    assert result["help_action"] == "confirmed"
    assert result["selection_confirmed"] is False
    assert len(clicks) == 3
    assert [delay for delay in sleeps if delay in (2, 0.2)] == [2.0, 0.2]
    assert queue["tasks"][0]["status"] == "waiting_completion"
    assert queue["tasks"][0]["initial_remaining_seconds"] == 3600


def test_requested_quantity_is_typed_and_confirmed_before_train(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch, level=7)
    states = iter((
        {"status": "idle"}, {"status": "idle"}, {"status": "idle"}, {"status": "active"},
        {"status": "active", "button_state": "help", "training_button_region": {"x": 1080, "y": 288, "w": 129, "h": 33}},
        {"status": "active", "button_state": "speedup", "training_button_region": {"x": 1080, "y": 288, "w": 129, "h": 33}},
    ))
    queue_readings = iter((
        NumericReading(1565, 90, "+1,565"), NumericReading(100, 95, "100"),
    ))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))
    monkeypatch.setattr(executor, "read_slot_readings", lambda *args: SlotReadings(
        0, next(queue_readings), NumericReading(0, 90, "0"), NumericReading(500, 90, "500"),
    ))
    events = []

    def press_key(key, presses=1):
        events.append(("press", key, presses))

    def write_text(text):
        events.append(("write", text))

    original_click = click

    def record_click(point, origin):
        events.append(("click", point))
        original_click(point, origin)

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=record_click, sleep_fn=lambda _: None,
        quantity=100, press_key_fn=press_key, write_text_fn=write_text,
    )

    assert result["status"] == "START_CONFIRMED"
    assert result["quantity_confirmed"] == 100
    assert result["preflight"]["planned_quantity"] == 100
    assert events[:4] == [
        ("click", (340, 412)), ("press", "backspace", 6), ("write", "100"), ("click", (425, 510)),
    ]


def test_quantity_ocr_mismatch_blocks_before_train(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch, level=7)
    states = iter(({"status": "idle"}, {"status": "idle"}, {"status": "idle"}))
    readings = iter((NumericReading(1565, 90, "+1,565"), NumericReading(99, 90, "99")))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))
    monkeypatch.setattr(executor, "read_slot_readings", lambda *args: SlotReadings(
        0, next(readings), NumericReading(0, 90, "0"), NumericReading(500, 90, "500"),
    ))

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
        quantity=100, press_key_fn=lambda *args, **kwargs: None, write_text_fn=lambda _: None,
    )

    assert result["status"] == "BLOCKED_QUANTITY_UNCONFIRMED"
    assert "quantity_confirmed" not in result
    assert "train_click_attempted" not in result
    assert clicks == [((340, 412), (0, 0))]


def test_requested_quantity_above_queue_maximum_blocks_before_field_click(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch, level=7)
    states = iter(({"status": "idle"}, {"status": "idle"}))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))
    monkeypatch.setattr(executor, "read_slot_readings", lambda *args: SlotReadings(
        0, NumericReading(99, 90, "99"), NumericReading(0, 90, "0"), NumericReading(500, 90, "500"),
    ))

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
        quantity=100, press_key_fn=lambda *args, **kwargs: None, write_text_fn=lambda _: None,
    )

    assert result["status"] == "BLOCKED_BEFORE_TRAIN"
    assert result["blockers"] == ["Requested quantity 100 exceeds the visible queue maximum 99."]
    assert clicks == []


def test_unconfirmed_help_button_pauses_without_clicking_help(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch)
    states = iter((
        {"status": "idle"}, {"status": "idle"}, {"status": "active"},
        {"status": "active", "button_state": "absent", "training_button_region": None},
    ))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
    )

    assert result["status"] == "START_CONFIRMED_HELP_UNCERTAIN"
    assert queue["paused"] is True
    assert queue["pause_reason"].startswith("uncertain_help_action:")
    assert len(clicks) == 2


def test_train_click_failure_pauses_queue_and_is_not_retried(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch, click_error_at=2)
    states = iter(({"status": "idle"}, {"status": "idle"}))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))

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
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
    )

    assert result["status"] == "UNKNOWN_AFTER_CLICK"
    assert queue["paused"] is True
    assert len(clicks) == 2


def test_uncertain_help_click_is_not_retried(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch, click_error_at=3)
    button_region = {"x": 1080, "y": 288, "w": 129, "h": 33}
    states = iter((
        {"status": "idle"}, {"status": "idle"}, {"status": "active"},
        {"status": "active", "button_state": "help", "training_button_region": button_region},
    ))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
    )

    assert result["status"] == "UNKNOWN_AFTER_HELP_CLICK_ATTEMPT"
    assert queue["paused"] is True
    assert queue["pause_reason"].startswith("uncertain_help_action:")
    assert len(clicks) == 3


def test_emergency_stop_after_train_blocks_help_and_returns_queue_state(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch)
    button_region = {"x": 1080, "y": 288, "w": 129, "h": 33}
    states = iter((
        {"status": "idle"}, {"status": "idle"}, {"status": "active"},
        {"status": "active", "button_state": "help", "training_button_region": button_region},
    ))
    checks = []

    def check_stop():
        checks.append(True)
        if len(checks) == 4:
            raise RuntimeError("stop requested")

    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))
    monkeypatch.setattr(executor, "_check_emergency_stop", check_stop)

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
    )

    assert result["status"] == "START_CONFIRMED_HELP_BLOCKED"
    assert queue["tasks"][0]["status"] == "waiting_help_delay"
    assert queue["paused"] is False
    assert len(clicks) == 2


def test_help_click_without_speedup_confirmation_pauses_without_retry(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch)
    button_region = {"x": 1080, "y": 288, "w": 129, "h": 33}
    states = iter((
        {"status": "idle"}, {"status": "idle"}, {"status": "active"},
        {"status": "active", "button_state": "help", "training_button_region": button_region},
        {"status": "active", "button_state": "help", "training_button_region": button_region},
    ))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))

    result = executor.execute_training_goal(
        queue, task["task_id"], NOW, execute=True,
        confirmation=executor.CONFIRMATION_PHRASE,
        capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
    )

    assert result["status"] == "UNKNOWN_AFTER_HELP_CLICK"
    assert queue["paused"] is True
    assert queue["pause_reason"].startswith("uncertain_help_action:")
    assert len(clicks) == 3


def test_missing_or_unreliable_time_blocks_before_train(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch)
    states = iter(({"status": "idle"}, {"status": "idle"}))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *args, **kwargs: next(states))
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


def test_highlighted_category_mismatch_blocks_before_any_click(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch)
    monkeypatch.setattr(executor, "read_selected_category", lambda *args: {"unit_type": "specialists"})

    with pytest.raises(executor.LiveTrainingError, match="Highlighted category"):
        executor.execute_training_goal(
            queue, task["task_id"], NOW, execute=True, confirmation=executor.CONFIRMATION_PHRASE,
            capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
        )

    assert clicks == []
