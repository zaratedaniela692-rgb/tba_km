from datetime import datetime, timedelta, timezone
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


@pytest.mark.parametrize("phase", ("before_help", "after_help"))
@pytest.mark.parametrize("failure", ("capture", "geometry"))
def test_post_start_help_failure_preserves_started_task_and_marker(monkeypatch, tmp_path, phase, failure):
    from army_state import open_training_marker

    queue, _, clicks, click, _ = _setup(monkeypatch)
    task = queue["tasks"][0]
    executor.mark_task_started(queue, task["task_id"], 3600, now=NOW)
    marker_path = tmp_path / "army_state.json"
    open_training_marker(marker_path, "order", task["task_id"], {}, NOW, NOW + timedelta(hours=1))
    marker_before = marker_path.read_bytes()
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    captures = []
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *_args, **_kwargs: {
        "status": "active", "button_state": "help",
        "training_button_region": {"x": 100, "y": 200, "w": 40, "h": 20},
    })

    def capture():
        captures.append(True)
        fail_now = len(captures) == (1 if phase == "before_help" else 2)
        if fail_now and failure == "capture":
            raise OSError("capture failed")
        return image, (10, 0) if fail_now else (0, 0)

    result = executor._request_help_after_confirmed_start(
        queue, task, {"actions_executed": True}, NOW, NumericReading(3600, 100, "1h"),
        image, (0, 0), {}, capture, click, lambda _: None,
    )

    assert result["status"] == ("START_CONFIRMED_HELP_UNCERTAIN" if phase == "before_help" else "UNKNOWN_AFTER_HELP_CLICK")
    assert len(clicks) == (0 if phase == "before_help" else 1)
    assert len(captures) == (1 if phase == "before_help" else 2)
    assert task["status"] == "waiting_help_delay"
    assert task["started_at"] == NOW.isoformat()
    assert queue["paused"] is True
    assert marker_path.read_bytes() == marker_before


@pytest.mark.parametrize("quick_finish", (False, True))
def test_post_start_help_preserves_lifecycle_times_without_acceleration(monkeypatch, quick_finish):
    queue, _, clicks, click, capture = _setup(monkeypatch)
    task = queue["tasks"][0]
    task["quick_finish"] = quick_finish
    executor.mark_task_started(queue, task["task_id"], 3600, now=NOW)
    states = iter(("help", "speedup"))
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *_args, **_kwargs: {
        "status": "active", "button_state": next(states),
        "training_button_region": {"x": 100, "y": 200, "w": 40, "h": 20},
    })
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    sleeps = []
    result = {"actions_executed": True}

    assert executor._request_help_after_confirmed_start(
        queue, task, result, NOW, NumericReading(3600, 100, "1h"), image, (0, 0), {},
        capture, click, sleeps.append,
    ) is result

    assert result["status"] == "START_CONFIRMED"
    assert sleeps == [2.0, 0.2]
    assert clicks == [((120, 210), (0, 0))]
    assert task["status"] == ("ready_to_accelerate" if quick_finish else "waiting_completion")
    assert task["help_requested_at"] == (NOW + timedelta(seconds=2)).isoformat()
    assert task["speedup_check_at"] == (NOW + timedelta(seconds=2.2)).isoformat()
    assert queue["paused"] is False


def test_execute_requires_exact_confirmation_before_capture(monkeypatch):
    queue, task, _, click, _ = _setup(monkeypatch)
    captured = []

    with pytest.raises(executor.LiveTrainingError, match="confirmation phrase"):
        executor.execute_training_goal(
            queue, task["task_id"], NOW, execute=True, confirmation="yes",
            capture_fn=lambda: captured.append(True), click_fn=click,
        )
    assert captured == []


@pytest.mark.parametrize("seconds_until_check", (1, 0, -1))
def test_direct_executor_checks_retry_deadline_before_capture(monkeypatch, seconds_until_check):
    from copy import deepcopy

    queue, task, clicks, click, _ = _setup(monkeypatch)
    queue["tasks"][0]["next_check_at"] = (NOW + timedelta(seconds=seconds_until_check)).isoformat()
    before = deepcopy(queue)
    captures = []

    def capture():
        captures.append(True)
        raise OSError("test capture reached")

    with pytest.raises((executor.LiveTrainingError, OSError), match="not due yet" if seconds_until_check > 0 else "test capture reached"):
        executor.execute_training_goal(
            queue, task["task_id"], NOW, execute=True, confirmation=executor.CONFIRMATION_PHRASE,
            capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
        )
    assert captures == ([] if seconds_until_check > 0 else [True])
    assert clicks == []
    assert queue == before


@pytest.mark.parametrize("uncertainty", (None, "silver_ocr", "food", "slot_ocr"))
def test_confirmed_silver_shortfall_defers_then_holds_without_train(monkeypatch, uncertainty):
    queue, task, clicks, click, capture = _setup(monkeypatch, level=7)
    plan = {
        "blockers": ["silver_insufficient_or_uncertain"],
        "resources": {"silver": {"value": 100, "confidence_ok": uncertainty != "silver_ocr"}, "food": {"value": 1000, "confidence_ok": True}},
        "readings": {key: {"value": value, "confidence": 90} for key, value in (
            ("queue_limit", 100), ("city_count", 0), ("silver_cost", 200),
        )},
    }
    if uncertainty == "food":
        plan["blockers"].append("food_not_positive_white")
    if uncertainty == "slot_ocr":
        plan["readings"]["silver_cost"]["confidence"] = 20
    monkeypatch.setattr(executor, "_build_selected_slot_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *_args, **_kwargs: {"status": "idle"})
    for attempt in range(1 if uncertainty else 3):
        result = executor.execute_training_goal(
            queue, task["task_id"], NOW + timedelta(seconds=attempt * queue["settings"]["resource_retry_seconds"]),
            execute=True, confirmation=executor.CONFIRMATION_PHRASE,
            capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
        )
        assert not result.get("train_click_attempted", False)
    assert clicks == []
    if uncertainty:
        assert result["status"] == "BLOCKED_BEFORE_TRAIN"
        assert "resource_retry" not in queue["tasks"][0]
    else:
        assert result["status"] == "ARMY_TRAINING_HELD"
        assert queue["tasks"][0]["status"] == "waiting_resources"
        assert queue["tasks"][0]["payload"]["process"]["decision"] is None
        with pytest.raises(executor.LiveTrainingError, match="held"):
            executor.execute_training_goal(
                queue, task["task_id"], NOW, execute=True, confirmation=executor.CONFIRMATION_PHRASE,
                capture_fn=lambda: pytest.fail("must not capture"), click_fn=click,
            )


@pytest.mark.parametrize(("active_type", "status", "remaining"), (
    ("army_training", "waiting_completion", 300),
    ("building_upgrade", "waiting_completion", 60),
    ("building_upgrade", "waiting_completion", None),
    ("building_upgrade", "waiting_help_delay", 300),
))
def test_shared_parallelism_gate_blocks_executor_before_capture(monkeypatch, active_type, status, remaining):
    from copy import deepcopy
    from task_controller import enqueue_task

    queue, task, clicks, click, _ = _setup(monkeypatch)
    active = enqueue_task(queue, active_type, task_id="active", now=NOW)
    active.update(status=status, last_remaining_seconds=remaining)
    before = deepcopy(queue)
    with pytest.raises(executor.LiveTrainingError, match="lifecycle gates"):
        executor.execute_training_goal(
            queue, task["task_id"], NOW, execute=True, confirmation=executor.CONFIRMATION_PHRASE,
            capture_fn=lambda: pytest.fail("must not capture when lifecycle blocks start"), click_fn=click,
        )
    assert clicks == []
    assert queue == before


def test_unverified_unit_type_blocks_before_any_click(monkeypatch):
    queue, task, clicks, click, capture = _setup(monkeypatch)
    queue["tasks"][0]["payload"]["slot"]["unit_type"] = "specialists"

    with pytest.raises(executor.LiveTrainingError, match="not verified for this unit type"):
        executor.execute_training_goal(
            queue, task["task_id"], NOW, execute=True, confirmation=executor.CONFIRMATION_PHRASE,
            capture_fn=capture, click_fn=click, sleep_fn=lambda _: None,
        )

    assert clicks == []


def test_test_finisher_requests_help_then_uses_speedups_and_requires_idle(monkeypatch):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    button_region = {"x": 100, "y": 200, "w": 40, "h": 20}
    states = iter((
        {"status": "active", "button_state": "help", "training_button_region": button_region},
        {"status": "active", "button_state": "speedup", "training_button_region": button_region},
        {"status": "idle", "button_state": "absent", "training_button_region": button_region},
    ))
    monkeypatch.setattr(executor, "resolve_variant", lambda: {"id": "legacy"})
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(executor, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(executor, "_enable_live_failsafe", lambda _click: None)
    clicks = []
    captures = []
    speedup_calls = []

    result = executor.finish_active_training_for_test(
        image, (0, 0), "test",
        lambda: captures.append(True) or (image, (0, 0)),
        click_fn=lambda point, origin: clicks.append((point, origin)),
        speedup_fn=lambda: speedup_calls.append(True) or SimpleNamespace(status="FINISHED", reason="task_finished"),
        sleep_fn=lambda _: None,
    )

    assert result == {"status": "FINISHED", "actions_executed": True}
    assert clicks == [((120, 210), (0, 0)), ((120, 210), (0, 0))]
    assert speedup_calls == [True]
    assert len(captures) == 2


def test_test_finisher_stops_when_owned_speedups_are_insufficient(monkeypatch):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    button_region = {"x": 100, "y": 200, "w": 40, "h": 20}
    monkeypatch.setattr(executor, "resolve_variant", lambda: {"id": "legacy"})
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *_args, **_kwargs: {
        "status": "active", "button_state": "speedup", "training_button_region": button_region,
    })
    monkeypatch.setattr(executor, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(executor, "_enable_live_failsafe", lambda _click: None)
    clicks = []

    with pytest.raises(executor.LiveTrainingError, match="NOT_ENOUGH"):
        executor.finish_active_training_for_test(
            image, (0, 0), "test", lambda: (image, (0, 0)),
            click_fn=lambda point, origin: clicks.append((point, origin)),
            speedup_fn=lambda: SimpleNamespace(status="NOT_ENOUGH", reason="owned_items_do_not_cover_remaining_time"),
            sleep_fn=lambda _: None,
        )

    assert clicks == [((120, 210), (0, 0))]


def test_test_finisher_uses_speedups_when_button_is_already_visible(monkeypatch):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    button_region = {"x": 100, "y": 200, "w": 40, "h": 20}
    states = iter((
        {"status": "active", "button_state": "speedup", "training_button_region": button_region},
        {"status": "idle", "button_state": "absent", "training_button_region": button_region},
    ))
    monkeypatch.setattr(executor, "resolve_variant", lambda: {"id": "legacy"})
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(executor, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(executor, "_enable_live_failsafe", lambda _click: None)
    clicks = []

    result = executor.finish_active_training_for_test(
        image, (0, 0), "test", lambda: (image, (0, 0)),
        click_fn=lambda point, origin: clicks.append((point, origin)),
        speedup_fn=lambda: SimpleNamespace(status="FINISHED", reason="task_finished"),
        sleep_fn=lambda _: None,
    )

    assert result["status"] == "FINISHED"
    assert clicks == [((120, 210), (0, 0))]


def test_test_finisher_rejects_non_test_profile_before_actions():
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    clicks = []

    with pytest.raises(executor.LiveTrainingError, match="test profile"):
        executor.finish_active_training_for_test(
            image, (0, 0), "production", lambda: (image, (0, 0)),
            click_fn=lambda point, origin: clicks.append((point, origin)),
        )

    assert clicks == []


@pytest.mark.parametrize("failure", ("help_unconfirmed", "geometry_changed", "click_exception", "still_active"))
def test_test_finisher_stops_without_retry_on_uncertain_transition(monkeypatch, failure):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    region = {"x": 100, "y": 200, "w": 40, "h": 20}
    initial = "help" if failure in {"help_unconfirmed", "geometry_changed", "click_exception"} else "speedup"
    states = iter((
        {"status": "active", "button_state": initial, "training_button_region": region},
        {"status": "active", "button_state": "help", "training_button_region": region},
    ))
    monkeypatch.setattr(executor, "resolve_variant", lambda: {"id": "legacy"})
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(executor, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(executor, "_enable_live_failsafe", lambda _click: None)
    events, clicks, captures, uses = [], [], [], []
    monkeypatch.setattr(executor, "record_live_checkpoint", lambda step, **kwargs: events.append((step, kwargs)))

    def click(point, origin):
        clicks.append(point)
        if failure == "click_exception":
            raise OSError("acknowledgement lost")

    def capture():
        captures.append(True)
        return image, (10, 0) if failure == "geometry_changed" else (0, 0)

    with pytest.raises(executor.LiveTrainingError, match="without retry"):
        executor.finish_active_training_for_test(
            image, (0, 0), "test", capture, click_fn=click,
            speedup_fn=lambda: uses.append(True) or SimpleNamespace(status="FINISHED", reason="finished"),
            sleep_fn=lambda _: None,
        )

    assert len(clicks) == 1
    assert len(captures) == (0 if failure == "click_exception" else 1)
    assert uses == ([True] if failure == "still_active" else [])
    assert events[-1][1]["decision"] == "uncertain"
    assert events[-1][1]["frame"] is image


@pytest.mark.parametrize("after_finish", ("idle", "completed"))
def test_test_finisher_clicks_completed_finish_only_once(monkeypatch, after_finish):
    import army_training_scanner

    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    states = iter(({"status": "completed", "finish_button_point": (1087, 303)}, {"status": after_finish}))
    monkeypatch.setattr(executor, "resolve_variant", lambda: {"id": "legacy"})
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(executor, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(executor, "_enable_live_failsafe", lambda _click: None)
    monkeypatch.setattr(army_training_scanner, "locate_finish_training_button", lambda *_: pytest.fail("must reuse recognized Finish point"))
    clicks = []

    def run():
        return executor.finish_active_training_for_test(
            image, (0, 0), "test", lambda: (image, (0, 0)),
            click_fn=lambda point, origin: clicks.append(point),
            speedup_fn=lambda: pytest.fail("completed training must not use speedups"), sleep_fn=lambda _: None,
        )

    if after_finish == "idle":
        assert run()["status"] == "FINISHED"
    else:
        with pytest.raises(executor.LiveTrainingError, match="did not return to idle"):
            run()
    assert clicks == [(1087, 303)]


def test_test_finisher_uses_existing_live_adapter_then_handles_finish(monkeypatch):
    import army_training_scanner
    import speedup_live

    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    states = iter((
        {"status": "active", "button_state": "speedup", "training_button_region": {"x": 100, "y": 200, "w": 40, "h": 20}},
        {"status": "completed", "finish_button_point": (1087, 303)}, {"status": "idle"},
    ))
    monkeypatch.setattr(executor, "resolve_variant", lambda: {"id": "legacy"})
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(executor, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(executor, "_enable_live_failsafe", lambda _click: None)
    monkeypatch.setattr(army_training_scanner, "locate_finish_training_button", lambda *_: pytest.fail("must reuse recognized Finish point"))
    uses, clicks = [], []
    monkeypatch.setattr(speedup_live, "run_desktop_speedups", lambda **kwargs: (
        uses.append(kwargs) or SimpleNamespace(status="FINISHED", reason="finished"), {},
    ))

    result = executor.finish_active_training_for_test(
        image, (0, 0), "test", lambda: (image, (0, 0)),
        click_fn=lambda point, origin: clicks.append(point), sleep_fn=lambda _: None,
    )

    assert result["status"] == "FINISHED"
    assert uses == [{"execute": True}]
    assert clicks == [(120, 210), (1087, 303)]


@pytest.mark.parametrize("state", (
    {"status": "completed", "finish_button_point": None},
    {"status": "unknown", "button_state": "ambiguous"},
))
def test_test_finisher_blocks_without_unambiguous_control_point(monkeypatch, state):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    monkeypatch.setattr(executor, "resolve_variant", lambda: {"id": "legacy"})
    monkeypatch.setattr(executor, "_read_current_training_state", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(executor, "_check_emergency_stop", lambda: None)
    with pytest.raises(executor.LiveTrainingError, match="without retry"):
        executor.finish_active_training_for_test(
            image, (0, 0), "test", lambda: pytest.fail("must not capture"),
            click_fn=lambda *_: pytest.fail("must not click"),
            speedup_fn=lambda: pytest.fail("must not use speedups"),
        )
