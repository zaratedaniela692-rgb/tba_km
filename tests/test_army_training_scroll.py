import numpy as np
import pytest

from army_training_scroll import (
    SCROLL_DOWN,
    SCROLL_UP,
    STATUS_BLOCKED,
    STATUS_ENDPOINT,
    STATUS_FOUND,
    STATUS_LIMIT,
    STATUS_NO_SCROLL,
    choose_scroll_direction,
    frame_center,
    scroll_one_batch,
    search_in_direction,
)


def test_frame_center_uses_current_frame_dimensions():
    assert frame_center(np.zeros((1080, 1920, 3), dtype=np.uint8)) == (960, 540)
    assert frame_center(np.zeros((720, 1280, 3), dtype=np.uint8)) == (640, 360)


def test_earlier_missing_level_searches_upward():
    level = type("Level", (), {
        "status": "candidate", "lowest_visible_level": 6, "highest_visible_level": 6,
    })()

    assert choose_scroll_direction((level,), 5) == SCROLL_UP


def test_later_missing_level_searches_downward():
    level = type("Level", (), {
        "status": "candidate", "lowest_visible_level": 5, "highest_visible_level": 6,
    })()

    assert choose_scroll_direction((level,), 7) == SCROLL_DOWN


def test_visible_target_range_needs_no_scroll():
    level = type("Level", (), {
        "status": "candidate", "lowest_visible_level": 5, "highest_visible_level": 6,
    })()

    assert choose_scroll_direction((level,), 5) == STATUS_NO_SCROLL


def test_missing_ordinal_match_searches_toward_earlier_levels():
    level = type("Level", (), {
        "status": "candidate", "lowest_visible_level": 5, "highest_visible_level": 6,
    })()

    assert choose_scroll_direction((level,), 5, match_number=2) == SCROLL_UP


def test_uncertain_level_reading_blocks_direction_choice():
    level = type("Level", (), {
        "status": "unknown", "lowest_visible_level": None, "highest_visible_level": None,
    })()

    assert choose_scroll_direction((level,), 5) == STATUS_BLOCKED


def test_scroll_batch_moves_to_screen_center_and_sends_eight_individual_steps():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    moved = []
    steps = []
    checks = []

    scroll_one_batch(
        frame, (-100, 25), SCROLL_DOWN,
        moved.append, steps.append, lambda: checks.append("checked"),
    )

    assert moved == [(540, 385)]
    assert steps == [SCROLL_DOWN] * 8
    assert len(checks) == 9


@pytest.mark.parametrize("direction", [SCROLL_UP, SCROLL_DOWN])
def test_scroll_search_observes_each_changed_frame_until_target(direction):
    frames = [np.zeros((4, 4), dtype=np.uint8), np.ones((4, 4), dtype=np.uint8)]
    captures = iter([(frames[1], (0, 0))])
    moved = []
    steps = []
    observed = []

    result = search_in_direction(
        frames[0], (0, 0), direction,
        lambda: next(captures), moved.append, steps.append,
        lambda frame: observed.append(int(frame[0, 0])) or {
            "status": STATUS_FOUND if frame[0, 0] == 1 else "continue"
        },
    )

    assert result.status == STATUS_FOUND
    assert result.batches == 1
    assert observed == [0, 1]
    assert len(steps) == 8
    assert set(steps) == {direction}


def test_unchanged_frame_confirms_endpoint():
    frame = np.zeros((4, 4), dtype=np.uint8)
    result = search_in_direction(
        frame, (0, 0), SCROLL_DOWN,
        lambda: (frame.copy(), (0, 0)), lambda _: None, lambda _: None,
        lambda _: {"status": "continue"},
    )

    assert result.status == STATUS_ENDPOINT
    assert result.reason == "image_unchanged_after_scroll"
    assert result.batches == 1


def test_uncertain_observation_blocks_without_scrolling():
    frame = np.zeros((4, 4), dtype=np.uint8)
    steps = []
    result = search_in_direction(
        frame, (0, 0), SCROLL_UP,
        lambda: pytest.fail("capture must not run"), lambda _: None, steps.append,
        lambda _: {"status": "uncertain"},
    )

    assert result.status == STATUS_BLOCKED
    assert steps == []


def test_scroll_search_stops_at_safety_limit_without_claiming_endpoint():
    frames = iter([np.full((4, 4), value, dtype=np.uint8) for value in (1, 2)])
    result = search_in_direction(
        np.zeros((4, 4), dtype=np.uint8), (0, 0), SCROLL_DOWN,
        lambda: (next(frames), (0, 0)), lambda _: None, lambda _: None,
        lambda _: {"status": "continue"}, max_batches=1,
    )

    assert result.status == STATUS_LIMIT
    assert result.batches == 1