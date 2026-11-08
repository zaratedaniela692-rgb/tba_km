import pytest

from game_screen import GameScreenError, clear_game_screen
from workflow_trace import WorkflowTrace


def test_clear_game_screen_dry_run_does_not_send_keys(tmp_path):
    calls = []

    result = clear_game_screen(press_key=lambda *args, **kwargs: calls.append((args, kwargs)))

    assert result == {
        "key": "esc",
        "presses": 3,
        "interval_seconds": 0.1,
        "actions_executed": False,
        "status": "DRY_RUN",
    }
    assert calls == []


def test_clear_game_screen_records_reset_events(tmp_path):
    trace = WorkflowTrace("test")

    result = clear_game_screen(
        execute=True,
        press_key=lambda *_args, **_kwargs: None,
        stop_file=tmp_path / ".tba_stop",
        trace=trace,
    )

    assert result["status"] == "RESET_SENT"
    assert trace.events[0]["step"] == "reset_screen"
    assert trace.events[0]["verification"] == "completed"


def test_clear_game_screen_sends_three_rapid_escape_presses(tmp_path):
    calls = []

    result = clear_game_screen(
        execute=True,
        press_key=lambda *args, **kwargs: calls.append((args, kwargs)),
        stop_file=tmp_path / ".tba_stop",
    )

    assert calls == [(('esc',), {"presses": 3, "interval": 0.1})]
    assert result["status"] == "RESET_SENT"
    assert result["actions_executed"] is True


def test_clear_game_screen_obeys_emergency_stop(tmp_path):
    stop_file = tmp_path / ".tba_stop"
    stop_file.touch()
    calls = []

    with pytest.raises(GameScreenError, match="Emergency stop"):
        clear_game_screen(
            execute=True,
            press_key=lambda *args, **kwargs: calls.append((args, kwargs)),
            stop_file=stop_file,
        )

    assert calls == []


def test_clear_game_screen_does_not_retry_failed_key_sequence(tmp_path):
    calls = []

    def fail_press(*args, **kwargs):
        calls.append((args, kwargs))
        raise OSError("input failed")

    with pytest.raises(GameScreenError, match="state is uncertain"):
        clear_game_screen(execute=True, press_key=fail_press, stop_file=tmp_path / ".tba_stop")

    assert len(calls) == 1