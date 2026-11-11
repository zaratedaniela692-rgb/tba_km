from pathlib import Path

import cv2
import numpy as np
import pytest

import army_training_scanner as scanner
from army_training_scanner import locate_finish_training_button
from ui_variants import resolve_variant

ROOT_DIR = Path(__file__).resolve().parents[1]


def test_finish_button_template_matches_completion_fixture_only():
    variant = resolve_variant("legacy")
    completion = cv2.imread(str(ROOT_DIR / "tests/data/army_training/training_complete_finish_button.png"))
    empty_queue = cv2.imread(str(ROOT_DIR / "screenshots/army_training/pelny_army_training_empty_queue.png"))

    completion_score, completion_center = locate_finish_training_button(completion, variant)
    empty_score, empty_center = locate_finish_training_button(empty_queue, variant)

    assert completion_score > 0.999
    assert completion_center == (1087, 303)
    assert empty_score is not None and empty_score < 0.95
    assert empty_center is None


def test_completion_fixture_is_reported_as_completed_and_empty_queue_stays_idle():
    variant = resolve_variant("legacy")
    completion = cv2.imread(str(ROOT_DIR / "tests/data/army_training/training_complete_finish_button.png"))
    empty_queue = cv2.imread(str(ROOT_DIR / "screenshots/army_training/pelny_army_training_empty_queue.png"))

    completed = scanner.read_army_training_snapshot_from_image(completion, variant=variant, include_numeric=False)
    idle = scanner.read_army_training_snapshot_from_image(empty_queue, variant=variant, include_numeric=False)

    assert completed["status"] == "completed"
    assert completed["finish_button_detected"] is True
    assert completed["button_state"] == "finish"
    assert completed["finish_button_point"] == (1087, 303)
    assert idle["status"] == "idle"
    assert idle["training_button_region"] is None


@pytest.mark.parametrize(
    ("help_score", "speedup_score", "finish_point", "expected"),
    ((0.95, 0.1, None, "help"), (0.1, 0.95, None, "speedup"),
     (0.1, 0.1, (1087, 303), "finish"), (0.1, 0.1, None, "absent"),
     (0.95, 0.95, None, "ambiguous"), (0.95, 0.1, (1087, 303), "ambiguous"),
     (0.1, 0.95, (1087, 303), "ambiguous")),
)
def test_shared_control_reads_each_state_once_and_blocks_conflicts(monkeypatch, help_score, speedup_score, finish_point, expected):
    variant = resolve_variant("legacy")
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    region = {"x": 1080, "y": 288, "w": 129, "h": 33}
    monkeypatch.setattr(scanner, "_locate_template", lambda *_: (0.0, (0, 0)))
    matches = iter(((help_score, region), (speedup_score, region), (speedup_score, region)))
    monkeypatch.setattr(scanner, "_match_template_near_region", lambda *_: next(matches))
    finish_calls = []

    def finish(*args):
        finish_calls.append(True)
        return (1.0 if finish_point else 0.1), finish_point

    monkeypatch.setattr(scanner, "locate_finish_training_button", finish)
    result = scanner.read_army_training_snapshot_from_image(image, variant=variant, include_numeric=False)

    assert finish_calls == [True]
    assert result["button_state"] == expected
    assert result["status"] == {
        "help": "active", "speedup": "active", "finish": "completed",
        "absent": "idle", "ambiguous": "unknown",
    }[expected]
    assert result["training_button_region"] == (region if expected in {"help", "speedup"} else None)
    assert result["finish_button_point"] == (finish_point if expected == "finish" else None)


@pytest.mark.parametrize(
    ("help_score", "speedup_score", "expected"),
    ((0.95, 0.1, "active"), (0.1, 0.95, "active"), (0.95, 0.95, "active"), (0.1, 0.1, "idle")),
)
def test_training_state_comes_from_help_or_speedup_button_presence(monkeypatch, help_score, speedup_score, expected):
    monkeypatch.setattr(scanner, "_load_regions", lambda _path: {"army_training": {
        "current_trainin_army": {"template": "panel.png"},
        "speedup_panel": {},
        "current_unit_troop_count": {"x": 0, "y": 0, "w": 1, "h": 1},
    }})
    monkeypatch.setattr(scanner, "read_training_button_state_from_image", lambda *_args, **_kwargs: {
        "button_state": "help" if help_score >= scanner.BUTTON_MATCH_THRESHOLD else (
            "speedup" if speedup_score >= scanner.BUTTON_MATCH_THRESHOLD else "absent"
        ),
        "help_score": help_score,
        "speedup_score": speedup_score,
        "button_region": {"x": 0, "y": 0, "w": 1, "h": 1},
        "panel_score": 0.0,
    })
    variant = {"id": "legacy", "regions": "regions.json"}
    monkeypatch.setattr(scanner, "_classify_training_unit_image", lambda *_: pytest.fail("portrait must not decide desktop activity"))

    result = scanner.read_army_training_snapshot_from_image(
        np.zeros((1080, 1920, 3), dtype=np.uint8), variant=variant, include_numeric=False,
    )

    assert result["status"] == expected
    assert result["has_active_training"] is (expected == "active")


def test_finish_recognition_error_is_not_reported_as_idle(monkeypatch):
    variant = resolve_variant("legacy")
    image = cv2.imread(str(ROOT_DIR / "screenshots/army_training/pelny_army_training_empty_queue.png"))

    def fail_finish(*args):
        raise scanner.ArmyTrainingScannerError("Finish template unreadable")

    monkeypatch.setattr(scanner, "locate_finish_training_button", fail_finish)
    with pytest.raises(scanner.ArmyTrainingScannerError, match="Finish template unreadable"):
        scanner.read_army_training_snapshot_from_image(image, variant=variant, include_numeric=False)