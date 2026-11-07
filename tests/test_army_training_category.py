from pathlib import Path

import cv2
import numpy as np
import pytest

import army_training_category as category
from army_training_scanner import _load_regions
from ui_variants import resolve_variant

SHOTS = Path(__file__).resolve().parents[1] / "screenshots" / "army_training"
VARIANT = resolve_variant()
REGIONS = _load_regions(VARIANT["regions"])["army_training"]
SPECIALISTS_CLICK = (
    REGIONS["troops_type_specialists_selected"]["x"] + REGIONS["troops_type_specialists_selected"]["w"] // 2,
    REGIONS["troops_type_specialists_selected"]["y"] + REGIONS["troops_type_specialists_selected"]["h"] // 2,
)


def shot(name):
    return cv2.imread(str(SHOTS / f"{name}.png"))


class Game:
    def __init__(self, *frames, origins=None):
        self.frames = list(frames)
        self.origins = list(origins or [(0, 0)] * len(frames))
        self.clicks = []
        self.captures = 0

    def capture(self):
        self.captures += 1
        return self.frames.pop(0).copy(), self.origins.pop(0)

    def click(self, point, origin):
        self.clicks.append((point, origin))


def select(game, unit_type="specialists", execute=True, **kwargs):
    kwargs.setdefault("click_fn", game.click)
    kwargs.setdefault("stop_fn", lambda: None)
    return category.select_army_type(
        unit_type, execute=execute, capture_fn=game.capture, sleep_fn=lambda _: None,
        variant=VARIANT, **kwargs,
    )


@pytest.mark.parametrize("name, expected", [
    ("pelny", "guardsmen"),
    ("pelny_army_training_empty_queue", "guardsmen"),
    ("after_click_help_button", "guardsmen"),
    ("specialist_view", "specialists"),
    ("partially_unlocked_army", None),
])
def test_highlighted_category_is_read_from_the_fixtures(name, expected):
    result = category.read_selected_category(shot(name), REGIONS, VARIANT)

    assert result["unit_type"] == expected


def test_blank_frame_has_no_highlighted_category():
    blank = np.zeros((1080, 1920, 3), dtype=np.uint8)

    assert category.read_selected_category(blank, REGIONS, VARIANT)["unit_type"] is None


def test_already_selected_category_is_confirmed_without_a_click():
    game = Game(shot("specialist_view"))

    result = select(game)

    assert result["status"] == "CATEGORY_CONFIRMED" and result["selection_confirmed"] is True
    assert game.clicks == [] and result["actions_executed"] is False


def test_other_category_is_clicked_once_and_confirmed_by_the_highlight():
    game = Game(shot("pelny"), shot("specialist_view"))

    result = select(game)

    assert result["status"] == "CATEGORY_SELECTED" and result["current_category"] == "guardsmen"
    assert game.clicks == [(SPECIALISTS_CLICK, (0, 0))]
    assert result["actions_executed"] is True


def test_guardsmen_can_be_selected_back():
    game = Game(shot("specialist_view"), shot("pelny"))

    assert select(game, "guardsmen")["status"] == "CATEGORY_SELECTED"
    assert len(game.clicks) == 1


def test_preview_reports_the_needed_click_without_sending_input():
    game = Game(shot("pelny"))

    result = select(game, execute=False)

    assert result["status"] == "CATEGORY_WOULD_SELECT"
    assert game.clicks == [] and result["actions_executed"] is False


def test_click_without_the_highlight_moving_is_not_confirmed_and_not_retried():
    game = Game(shot("pelny"), shot("pelny"))

    result = select(game)

    assert result["status"] == "BLOCKED_CATEGORY_NOT_CONFIRMED"
    assert len(game.clicks) == 1 and result["actions_executed"] is True


def test_capture_geometry_change_after_the_click_is_not_confirmed():
    game = Game(shot("pelny"), shot("specialist_view"), origins=[(0, 0), (5, 5)])

    assert select(game)["status"] == "BLOCKED_CATEGORY_NOT_CONFIRMED"


def test_click_error_is_reported_and_not_retried():
    game = Game(shot("pelny"))
    attempts = []

    def failing_click(point, origin):
        attempts.append(point)
        raise OSError("lost")

    result = select(game, click_fn=failing_click)

    assert result["status"] == "BLOCKED_CATEGORY_CLICK_FAILED" and len(attempts) == 1


def test_screen_without_barracks_slots_is_never_clicked():
    game = Game(np.zeros((1080, 1920, 3), dtype=np.uint8))

    assert select(game)["status"] == "BLOCKED_BARRACKS_NOT_CONFIRMED"
    assert game.clicks == []


def test_unexpected_frame_size_is_never_clicked():
    game = Game(np.zeros((720, 1280, 3), dtype=np.uint8))

    assert select(game)["status"] == "BLOCKED_UNSUPPORTED_FRAME_SIZE"
    assert game.clicks == []


def test_emergency_stop_blocks_the_click():
    game = Game(shot("pelny"))

    def stop():
        raise RuntimeError("stop file")

    result = select(game, stop_fn=stop)

    assert result["status"] == "BLOCKED_EMERGENCY_STOP" and game.clicks == []


def test_unsupported_and_unknown_categories_do_not_touch_the_screen():
    game = Game()

    assert select(game, "dragons")["status"] == "BLOCKED_CATEGORY_SELECTION_UNIMPLEMENTED"
    assert select(game, "nonsense")["status"] == "BLOCKED_UNKNOWN_UNIT_TYPE"
    assert game.captures == 0


def test_missing_category_region_blocks_before_capture(monkeypatch):
    game = Game(shot("pelny"))
    monkeypatch.setattr(category, "resolve_variant", lambda: VARIANT)
    broken = dict(REGIONS)
    broken.pop("troops_type_specialists_selected")
    monkeypatch.setattr("army_training_scanner._load_regions", lambda _: {"army_training": broken})

    assert select(game)["status"] == "BLOCKED_CATEGORY_REGION_MISSING"
    assert game.captures == 0


@pytest.mark.parametrize("name, expected", [
    ("specialist_view", "idle"),
    ("pelny_army_training_empty_queue", "idle"),
    ("pelny", "active"),
])
def test_training_state_tolerates_the_one_pixel_frame_shift(name, expected):
    from army_training_scanner import read_army_training_snapshot_from_image

    snapshot = read_army_training_snapshot_from_image(shot(name), variant=VARIANT, include_numeric=False)

    assert snapshot["status"] == expected
    assert snapshot["trained_unit_count_error"] == "numeric_not_requested"


def test_cli_requires_the_confirmation_phrase_before_any_click(monkeypatch):
    monkeypatch.setattr(category, "select_army_type", lambda *a, **k: pytest.fail("must not select"))

    with pytest.raises(SystemExit) as error:
        category.main(["--unit-type", "specialists", "--execute"])

    assert error.value.code == 2


def test_cli_preview_succeeds_when_a_click_would_be_needed(monkeypatch, capsys):
    monkeypatch.setattr(
        category, "select_army_type",
        lambda unit_type, execute=False: {"status": "CATEGORY_WOULD_SELECT", "unit_type": unit_type},
    )

    assert category.main(["--unit-type", "specialists"]) == 0
    assert "CATEGORY_WOULD_SELECT" in capsys.readouterr().out
