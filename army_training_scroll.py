"""Injectable primitives for traversing the desktop Barracks unit list."""

from dataclasses import dataclass

import numpy as np

SCROLL_STEPS_PER_BATCH = 8
SCROLL_UP = 1
SCROLL_DOWN = -1

STATUS_FOUND = "found"
STATUS_ENDPOINT = "endpoint"
STATUS_BLOCKED = "blocked"
STATUS_LIMIT = "batch_limit_reached"
STATUS_NO_SCROLL = "no_scroll_needed"


@dataclass(frozen=True)
class ScrollSearchResult:
    status: str
    reason: str
    frame: object
    batches: int
    observations: tuple


def frame_center(frame):
    """Return the center point in frame-relative coordinates."""
    if frame is None or len(frame.shape) < 2 or frame.shape[0] <= 0 or frame.shape[1] <= 0:
        raise ValueError("A non-empty image frame is required.")
    return frame.shape[1] // 2, frame.shape[0] // 2


def choose_scroll_direction(level_readings, target_level, match_number=1):
    """Choose a direction when the requested level/match is not visible."""
    if match_number < 1:
        return STATUS_BLOCKED
    candidates = [
        reading for reading in level_readings
        if reading.status == "candidate"
        and reading.lowest_visible_level is not None
        and reading.highest_visible_level is not None
    ]
    if not candidates or any(reading.status != "candidate" for reading in level_readings):
        return STATUS_BLOCKED
    visible_matches = sum(
        reading.lowest_visible_level <= target_level <= reading.highest_visible_level
        for reading in candidates
    )
    if visible_matches >= match_number:
        return STATUS_NO_SCROLL
    highest_visible_level = max(reading.highest_visible_level for reading in candidates)
    return SCROLL_UP if target_level < highest_visible_level else SCROLL_DOWN


def scroll_one_batch(frame, origin, direction, move_fn, scroll_fn, stop_check=lambda: None):
    """Move to the frame center, then issue eight individual wheel steps."""
    if direction not in {SCROLL_UP, SCROLL_DOWN}:
        raise ValueError("Scroll direction must be SCROLL_UP or SCROLL_DOWN.")
    center_x, center_y = frame_center(frame)
    stop_check()
    move_fn((origin[0] + center_x, origin[1] + center_y))
    for _ in range(SCROLL_STEPS_PER_BATCH):
        stop_check()
        scroll_fn(direction)


def search_in_direction(
    initial_frame,
    initial_origin,
    direction,
    capture_fn,
    move_fn,
    scroll_fn,
    inspect_fn,
    stop_check=lambda: None,
    max_batches=50,
):
    """Inspect after each eight-step batch; distinguish endpoints from uncertainty."""
    if max_batches < 1:
        raise ValueError("max_batches must be positive.")

    frame, origin = initial_frame, initial_origin
    observations = []
    for batch_count in range(max_batches + 1):
        observation = inspect_fn(frame)
        observations.append(observation)
        status = observation.get("status")
        if status == STATUS_FOUND:
            return ScrollSearchResult(STATUS_FOUND, "target_observed", frame, batch_count, tuple(observations))
        if status != "continue":
            return ScrollSearchResult(STATUS_BLOCKED, "observation_uncertain", frame, batch_count, tuple(observations))
        if batch_count == max_batches:
            return ScrollSearchResult(STATUS_LIMIT, "scroll_batch_safety_limit_reached", frame, batch_count, tuple(observations))

        scroll_one_batch(frame, origin, direction, move_fn, scroll_fn, stop_check)
        next_frame, next_origin = capture_fn()
        if next_origin != origin or next_frame.shape != frame.shape:
            return ScrollSearchResult(STATUS_BLOCKED, "capture_geometry_changed", next_frame, batch_count + 1, tuple(observations))
        if np.array_equal(frame, next_frame):
            return ScrollSearchResult(STATUS_ENDPOINT, "image_unchanged_after_scroll", next_frame, batch_count + 1, tuple(observations))
        frame = next_frame

    raise AssertionError("Unreachable scroll-search state.")