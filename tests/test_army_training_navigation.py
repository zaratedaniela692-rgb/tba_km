from pathlib import Path

import cv2
import numpy as np

import army_training_navigation as navigation

ROOT = Path(__file__).resolve().parents[1]


def _live_map_fixture():
    image = cv2.imread(str(ROOT / "tests/data/world_map/account_locked.png"))
    return cv2.copyMakeBorder(image, 39, 52, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))


def test_armia_match_finds_template_shifted_one_pixel_within_search_margin():
    variant = navigation.resolve_variant("legacy")
    regions = navigation._read_regions(variant["regions"])
    region = regions["world_map"]["armia"]
    template = cv2.imread(str(navigation.resolve_asset_path(variant, region["template"])))
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    shifted_x = region["x"] - 1
    shifted_y = region["y"] + navigation.WORLD_MAP_FRAME_OFFSET_Y + 1
    frame[shifted_y:shifted_y + template.shape[0], shifted_x:shifted_x + template.shape[1]] = template

    match = navigation._match_army_button(frame, region, template, 94.6)

    assert match is not None
    assert match[:2] == (shifted_x + template.shape[1] // 2, shifted_y + template.shape[0] // 2)
    assert match[2] >= 94.6
    assert match[4] == {"x": 911, "y": 916, "w": 57, "h": 50}


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
    assert result["armia_match_confidence"] < result["armia_match_threshold"]
    assert result["armia_match_threshold"] == 94.6
    candidate_x, candidate_y = result["armia_match_candidate_point"]
    assert 937 <= candidate_x <= 941
    assert 939 <= candidate_y <= 943
    assert result["search_region"] == {"x": 911, "y": 916, "w": 57, "h": 50}
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


def test_ensure_screen_skips_navigation_when_barracks_is_already_open():
    barracks = cv2.imread(str(ROOT / "screenshots/army_training/pelny.png"))
    captures = []

    result = navigation.ensure_army_training_screen(
        execute=True,
        capture_fn=lambda: (captures.append(True) or barracks.copy(), (0, 0)),
        navigate_fn=lambda **kwargs: (_ for _ in ()).throw(AssertionError("navigation must be skipped")),
    )

    assert result["status"] == "BARRACKS_READY"
    assert result["navigation"]["status"] == "SKIPPED_ALREADY_OPEN"
    assert result["actions_executed"] is False
    assert len(result["layout"].slots) == 3
    assert len(captures) == 1


def test_ensure_screen_preview_reports_navigation_required_without_input():
    world_map = _live_map_fixture()
    captures = []
    navigations = []

    result = navigation.ensure_army_training_screen(
        execute=False,
        capture_fn=lambda: (captures.append(True) or world_map, (0, 0)),
        navigate_fn=lambda **kwargs: navigations.append(kwargs),
    )

    assert result["status"] == "NAVIGATION_REQUIRED"
    assert result["actions_executed"] is False
    assert len(captures) == 1
    assert navigations == []


def test_ensure_screen_navigates_once_and_uses_a_fresh_verified_frame():
    world_map = _live_map_fixture()
    barracks = cv2.imread(str(ROOT / "screenshots/army_training/pelny.png"))
    frames = iter(((world_map, (0, 0)), (barracks, (0, 0))))
    navigations = []

    def navigate(**kwargs):
        navigations.append(kwargs)
        return {"status": "BARRACKS_OPENED", "actions_executed": True, "visible_slots": 3}

    result = navigation.ensure_army_training_screen(
        execute=True,
        capture_fn=lambda: next(frames),
        navigate_fn=navigate,
    )

    assert result["status"] == "BARRACKS_READY"
    assert result["actions_executed"] is True
    assert result["navigation"]["status"] == "BARRACKS_OPENED"
    assert len(result["layout"].slots) == 3
    assert len(navigations) == 1
    assert navigations[0]["execute"] is True


def test_ensure_screen_stops_after_navigation_failure_without_retry():
    world_map = _live_map_fixture()
    captures = []
    navigations = []

    def navigate(**kwargs):
        navigations.append(kwargs)
        return {"status": "BLOCKED_ARMY_BUTTON_UNCONFIRMED", "actions_executed": True}

    result = navigation.ensure_army_training_screen(
        execute=True,
        capture_fn=lambda: (captures.append(True) or world_map, (0, 0)),
        navigate_fn=navigate,
    )

    assert result["status"] == "NAVIGATION_FAILED"
    assert result["actions_executed"] is True
    assert len(captures) == 1
    assert len(navigations) == 1


def test_ensure_screen_requires_slots_on_fresh_post_navigation_frame():
    world_map = _live_map_fixture()
    blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frames = iter(((world_map, (0, 0)), (blank, (0, 0))))

    result = navigation.ensure_army_training_screen(
        execute=True,
        capture_fn=lambda: next(frames),
        navigate_fn=lambda **kwargs: {"status": "BARRACKS_OPENED", "actions_executed": True},
    )

    assert result["status"] == "BLOCKED_POST_NAVIGATION_VERIFICATION"
    assert result["actions_executed"] is True