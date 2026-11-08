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