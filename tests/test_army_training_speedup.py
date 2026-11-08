from types import SimpleNamespace

import numpy as np
import pytest

import army_training_speedup as army_speedup


@pytest.mark.parametrize("runner_status", ["FINISHED", "UNCERTAIN", "BLOCKED", "NOT_ENOUGH"])
@pytest.mark.parametrize("observed_state", ["idle", "active", "unknown"])
def test_army_adapter_reconciles_actual_state_after_every_runner_result(monkeypatch, runner_status, observed_state):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    states = iter((
        {"status": "active", "speedup_button_detected": True},
        {"status": observed_state, "speedup_button_detected": False},
    ))
    clicks = []
    speedup_calls = []
    monkeypatch.setattr(army_speedup, "resolve_variant", lambda: {"regions": "regions.json"})
    monkeypatch.setattr(army_speedup, "_read_current_training_state", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(army_speedup, "locate_finish_training_button", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(army_speedup, "_load_regions", lambda _: {"army_training": {
        "speedup_panel": {"x": 10, "y": 20, "w": 30, "h": 40},
    }})
    monkeypatch.setattr(army_speedup, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(army_speedup, "_enable_live_failsafe", lambda _: None)

    def speedup_runner(**kwargs):
        speedup_calls.append(kwargs)
        return SimpleNamespace(status=runner_status, reason="dialog_closed_before_plan_end")

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=lambda: (image, (100, 200)),
        click_fn=lambda point, origin: clicks.append((point, origin)),
        sleep_fn=lambda _: None,
        speedup_runner=speedup_runner,
    )

    assert result == observed_state
    assert clicks == [((25, 40), (100, 200))]
    assert speedup_calls == [{"execute": True}]


def test_army_adapter_uses_configured_region_when_notification_hides_speedup_button(monkeypatch):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    monkeypatch.setattr(army_speedup, "resolve_variant", lambda: {"regions": "regions.json"})
    monkeypatch.setattr(army_speedup, "_read_current_training_state", lambda *_args, **_kwargs: {
        "status": "active", "speedup_button_detected": False,
    })
    monkeypatch.setattr(army_speedup, "_load_regions", lambda _: {"army_training": {
        "speedup_panel": {"x": 10, "y": 20, "w": 30, "h": 40},
    }})
    monkeypatch.setattr(army_speedup, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(army_speedup, "_enable_live_failsafe", lambda _: None)
    clicks = []
    runner_calls = []

    def speedup_runner(**kwargs):
        runner_calls.append(kwargs)
        return SimpleNamespace(status="BLOCKED", reason="speedup_dialog_not_recognized")

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=lambda: (image, (0, 0)),
        click_fn=lambda point, origin: clicks.append((point, origin)),
        sleep_fn=lambda _: None,
        speedup_runner=speedup_runner,
    )

    assert result == "active"
    assert clicks == [((25, 40), (0, 0))]
    assert runner_calls == [{"execute": True}]


def test_army_adapter_does_not_click_when_help_state_is_explicit(monkeypatch):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    monkeypatch.setattr(army_speedup, "resolve_variant", lambda: {"regions": "regions.json"})
    monkeypatch.setattr(army_speedup, "_read_current_training_state", lambda *_args, **_kwargs: {
        "status": "active", "button_state": "help", "speedup_button_detected": False,
    })
    clicks = []

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=lambda: (image, (0, 0)),
        click_fn=lambda point, origin: clicks.append((point, origin)),
        speedup_runner=lambda **_: pytest.fail("must not run while Help is explicitly visible"),
    )

    assert result == "active"
    assert clicks == []


def test_army_adapter_uses_open_dialog_checkpoint_runner_by_default(monkeypatch):
    import speedup_run

    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    states = iter((
        {"status": "active", "speedup_button_detected": True},
        {"status": "idle", "speedup_button_detected": False},
    ))
    calls = []
    monkeypatch.setattr(army_speedup, "resolve_variant", lambda: {"regions": "regions.json"})
    monkeypatch.setattr(army_speedup, "_read_current_training_state", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(army_speedup, "_load_regions", lambda _: {"army_training": {
        "speedup_panel": {"x": 10, "y": 20, "w": 30, "h": 40},
    }})
    monkeypatch.setattr(army_speedup, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(army_speedup, "_enable_live_failsafe", lambda _: None)
    monkeypatch.setattr(speedup_run, "run_open_dialog", lambda **kwargs: calls.append(kwargs) or SimpleNamespace(status="FINISHED"))

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=lambda: (image, (0, 0)),
        click_fn=lambda *_: None,
        sleep_fn=lambda _: None,
    )

    assert result == "idle"
    assert calls == [{"execute": True}]


def _round_setup(monkeypatch, states):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    iterator = iter(states)
    monkeypatch.setattr(army_speedup, "resolve_variant", lambda: {"regions": "regions.json"})
    monkeypatch.setattr(army_speedup, "_read_current_training_state", lambda *_a, **_k: {
        "status": next(iterator), "speedup_button_detected": True,
    })
    monkeypatch.setattr(army_speedup, "locate_finish_training_button", lambda *_a, **_k: (None, None))
    monkeypatch.setattr(army_speedup, "_load_regions", lambda _: {"army_training": {
        "speedup_panel": {"x": 10, "y": 20, "w": 30, "h": 40},
    }})
    monkeypatch.setattr(army_speedup, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(army_speedup, "_enable_live_failsafe", lambda _: None)
    return lambda: (image, (0, 0))


def test_army_adapter_starts_another_round_only_after_real_speedup_clicks(monkeypatch):
    capture = _round_setup(monkeypatch, ["active", "active", "active", "idle"])
    runs = []

    def runner(**kwargs):
        runs.append(kwargs)
        return SimpleNamespace(status="UNCERTAIN", reason="timer_unreadable", used=((3600, 1),))

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=capture, click_fn=lambda *_: None, sleep_fn=lambda _: None, speedup_runner=runner,
    )

    assert result == "idle"
    assert len(runs) == 2


def test_army_adapter_does_not_repeat_when_no_speedup_was_clicked(monkeypatch):
    capture = _round_setup(monkeypatch, ["active", "active"])
    runs = []

    def runner(**kwargs):
        runs.append(kwargs)
        return SimpleNamespace(status="BLOCKED", reason="speedup_dialog_not_recognized", used=())

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=capture, click_fn=lambda *_: None, sleep_fn=lambda _: None, speedup_runner=runner,
    )

    assert result == "active"
    assert len(runs) == 1


def test_army_adapter_round_count_is_bounded(monkeypatch):
    capture = _round_setup(monkeypatch, ["active"] * 20)
    runs = []

    def runner(**kwargs):
        runs.append(kwargs)
        return SimpleNamespace(status="FINISHED", reason="dialog_closed_after_last_use", used=((3600, 1),))

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=capture, click_fn=lambda *_: None, sleep_fn=lambda _: None, speedup_runner=runner,
        max_rounds=2,
    )

    assert result == "active"
    assert len(runs) == 2


def test_army_adapter_closes_an_already_completed_training_without_opening_speedups(monkeypatch):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    states = iter(({"status": "completed"}, {"status": "idle"}))
    actions = []
    monkeypatch.setattr(army_speedup, "resolve_variant", lambda: {"regions": "regions.json"})
    monkeypatch.setattr(army_speedup, "_read_current_training_state", lambda *_a, **_k: next(states))
    monkeypatch.setattr(army_speedup, "_load_regions", lambda _: {"army_training": {
        "finish_training_button": {"x": 1014, "y": 290, "w": 147, "h": 26, "type": "button"},
    }})
    monkeypatch.setattr(army_speedup, "locate_finish_training_button", lambda *_: (1.0, (1087, 303)))
    monkeypatch.setattr(army_speedup, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(army_speedup, "_enable_live_failsafe", lambda _: None)

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=lambda: (image, (0, 0)),
        click_fn=lambda point, origin: actions.append(("click", point)),
        move_fn=lambda point, origin: actions.append(("move", point)),
        on_finish_button_click=lambda: actions.append(("record", None)),
        sleep_fn=lambda _: None,
        speedup_runner=lambda **_: pytest.fail("speedups must not open on a completed screen"),
    )

    assert result == "idle"
    assert actions == [("move", (960, 540)), ("record", None), ("click", (1087, 303))]


def test_army_adapter_never_clicks_finish_on_a_completed_screen_without_a_recorder(monkeypatch):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    clicks = []
    monkeypatch.setattr(army_speedup, "resolve_variant", lambda: {"regions": "regions.json"})
    monkeypatch.setattr(army_speedup, "_read_current_training_state", lambda *_a, **_k: {"status": "completed"})
    monkeypatch.setattr(army_speedup, "_load_regions", lambda _: {"army_training": {}})
    monkeypatch.setattr(army_speedup, "locate_finish_training_button", lambda *_: (1.0, (1087, 303)))

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=lambda: (image, (0, 0)),
        click_fn=lambda point, origin: clicks.append(point),
        sleep_fn=lambda _: None,
        speedup_runner=lambda **_: pytest.fail("no speedups on a completed screen"),
    )

    assert result == "unknown"
    assert clicks == []


def test_army_adapter_clicks_only_matched_finish_button_and_requires_idle(monkeypatch):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    states = iter((
        {"status": "active", "speedup_button_detected": True},
        {"status": "unknown", "speedup_button_detected": False},
        {"status": "idle", "speedup_button_detected": False},
    ))
    actions = []
    monkeypatch.setattr(army_speedup, "resolve_variant", lambda: {"regions": "regions.json"})
    monkeypatch.setattr(army_speedup, "_read_current_training_state", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(army_speedup, "_load_regions", lambda _: {"army_training": {
        "speedup_panel": {"x": 10, "y": 20, "w": 30, "h": 40},
        "finish_training_button": {"x": 1014, "y": 290, "w": 147, "h": 26, "type": "button"},
    }})
    monkeypatch.setattr(army_speedup, "locate_finish_training_button", lambda *_: (1.0, (1087, 303)))
    monkeypatch.setattr(army_speedup, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(army_speedup, "_enable_live_failsafe", lambda _: None)

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=lambda: (image, (100, 200)),
        click_fn=lambda point, origin: actions.append(("click", point, origin)),
        move_fn=lambda point, origin: actions.append(("move", point, origin)),
        on_finish_button_click=lambda: actions.append(("record", None, None)),
        sleep_fn=lambda _: None,
        speedup_runner=lambda **_: SimpleNamespace(status="FINISHED", reason="dialog_closed_after_last_use"),
    )

    assert result == "idle"
    assert actions == [
        ("click", (25, 40), (100, 200)),
        ("move", (960, 540), (100, 200)),
        ("record", None, None),
        ("click", (1087, 303), (100, 200)),
    ]


def test_army_adapter_blocks_matched_finish_button_without_attempt_recorder(monkeypatch):
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    states = iter((
        {"status": "active", "speedup_button_detected": True},
        {"status": "unknown", "speedup_button_detected": False},
    ))
    clicks = []
    moves = []
    monkeypatch.setattr(army_speedup, "resolve_variant", lambda: {"regions": "regions.json"})
    monkeypatch.setattr(army_speedup, "_read_current_training_state", lambda *_args, **_kwargs: next(states))
    monkeypatch.setattr(army_speedup, "_load_regions", lambda _: {"army_training": {
        "speedup_panel": {"x": 10, "y": 20, "w": 30, "h": 40},
        "finish_training_button": {"x": 1014, "y": 290, "w": 147, "h": 26, "type": "button"},
    }})
    monkeypatch.setattr(army_speedup, "locate_finish_training_button", lambda *_: (1.0, (1087, 303)))
    monkeypatch.setattr(army_speedup, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(army_speedup, "_enable_live_failsafe", lambda _: None)

    result = army_speedup.finish_active_training_with_speedups(
        capture_fn=lambda: (image, (0, 0)),
        click_fn=lambda point, origin: clicks.append((point, origin)),
        move_fn=lambda point, origin: moves.append((point, origin)),
        sleep_fn=lambda _: None,
        speedup_runner=lambda **_: SimpleNamespace(status="FINISHED", reason="dialog_closed_after_last_use"),
    )

    assert result == "unknown"
    assert clicks == [((25, 40), (0, 0))]
    assert moves == []