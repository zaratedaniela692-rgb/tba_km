from pathlib import Path

import cv2

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
    from army_training_live_e2e import _read_current_training_state

    variant = resolve_variant("legacy")
    completion = cv2.imread(str(ROOT_DIR / "tests/data/army_training/training_complete_finish_button.png"))
    empty_queue = cv2.imread(str(ROOT_DIR / "screenshots/army_training/pelny_army_training_empty_queue.png"))

    completed = _read_current_training_state(completion, variant, include_numeric=False)
    idle = _read_current_training_state(empty_queue, variant, include_numeric=False)

    assert completed["status"] == "completed"
    assert completed["finish_button_detected"] is True
    assert idle["status"] == "idle"