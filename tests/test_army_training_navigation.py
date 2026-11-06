from pathlib import Path

import cv2
import numpy as np

import army_training_navigation as navigation

ROOT = Path(__file__).resolve().parents[1]


def _live_map_fixture():
    image = cv2.imread(str(ROOT / "tests/data/world_map/account_locked.png"))
    return cv2.copyMakeBorder(image, 39, 52, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))


def test_navigation_dry_run_does_not_press_capture_or_click():
    calls = []

    result = navigation.open_army_training_screen(
        capture_fn=lambda: calls.append("capture"),
        press_key_fn=lambda *args, **kwargs: calls.append("key"),
        click_fn=lambda *args, **kwargs: calls.append("click"),
    )

    assert result["status"] == "PREVIEW_ONLY"
    assert result["steps"] == ["press_escape_three_times", "click_army", "confirm_barracks_slots"]
    assert result["actions_executed"] is False
    assert calls == []


def test_navigation_resets_clicks_army_and_confirms_barracks(monkeypatch, tmp_path):
    events = []
    frames = iter(((_live_map_fixture(), (0, 0)), (cv2.imread(str(ROOT / "screenshots/army_training/pelny.png")), (0, 0))))
    monkeypatch.setattr(navigation, "TRANSITION_WAIT_SECONDS", 0)

    result = navigation.open_army_training_screen(
        execute=True,
        capture_fn=lambda: next(frames),
        press_key_fn=lambda *args, **kwargs: events.append(("key", args, kwargs)),
        click_fn=lambda point, origin: events.append(("click", point, origin)),
        sleep_fn=lambda _: events.append(("wait",)),
        stop_file=tmp_path / ".tba_stop",
    )

    assert result["status"] == "BARRACKS_OPENED"
    assert result["visible_slots"] == 3
    assert events[0] == ("key", ("esc",), {"presses": 3, "interval": 0.1})
    assert events[1][0] == "click"
    assert events[1][1] == (939, 941)
    assert events[2] == ("wait",)


def test_navigation_stops_when_armia_button_is_not_confident(monkeypatch, tmp_path):
    events = []
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)

    result = navigation.open_army_training_screen(
        execute=True,
        capture_fn=lambda: (image, (0, 0)),
        press_key_fn=lambda *args, **kwargs: events.append("key"),
        click_fn=lambda *args, **kwargs: events.append("click"),
        stop_file=tmp_path / ".tba_stop",
    )

    assert result["status"] == "BLOCKED_ARMY_BUTTON_UNCONFIRMED"
    assert events == ["key"]


def test_navigation_stops_if_barracks_layout_is_not_detected(monkeypatch, tmp_path):
    events = []
    frames = iter(((_live_map_fixture(), (0, 0)), (np.zeros((1080, 1920, 3), dtype=np.uint8), (0, 0))))
    monkeypatch.setattr(navigation, "TRANSITION_WAIT_SECONDS", 0)

    result = navigation.open_army_training_screen(
        execute=True,
        capture_fn=lambda: next(frames),
        press_key_fn=lambda *args, **kwargs: events.append("key"),
        click_fn=lambda *args, **kwargs: events.append("click"),
        sleep_fn=lambda _: None,
        stop_file=tmp_path / ".tba_stop",
    )

    assert result["status"] == "BLOCKED_BARRACKS_NOT_CONFIRMED"
    assert events == ["key", "click"]
    assert result["actions_executed"] is True