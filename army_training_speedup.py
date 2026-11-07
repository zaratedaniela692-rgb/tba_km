"""Bridge the army training panel to the standalone desktop speedup finisher."""

import time

from army_training_live_e2e import (
    EXPECTED_SIZE,
    _check_emergency_stop,
    _click_screen_point,
    _enable_live_failsafe,
    _load_regions,
    _read_current_training_state,
    capture_primary_monitor,
)
from ui_variants import resolve_variant


def finish_active_training_with_speedups(
    capture_fn=None,
    click_fn=None,
    sleep_fn=time.sleep,
    speedup_runner=None,
):
    """Use owned speedups only from a confirmed active army task and button."""
    from speedup_run import run_open_dialog

    capture_fn = capture_fn or capture_primary_monitor
    click_fn = click_fn or _click_screen_point
    speedup_runner = speedup_runner or run_open_dialog
    variant = resolve_variant()
    frame, origin = capture_fn()
    if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
        return "unknown"

    before = _read_current_training_state(frame, variant, include_numeric=False)
    if before["status"] == "idle":
        return "idle"
    if before["status"] != "active" or not before.get("speedup_button_detected"):
        return before["status"]

    regions = _load_regions(variant["regions"]).get("army_training", {})
    button = regions.get("speedup_panel")
    if not button:
        return "unknown"
    _check_emergency_stop()
    _enable_live_failsafe(click_fn)
    point = (
        int(button["x"]) + int(button["w"]) // 2,
        int(button["y"]) + int(button["h"]) // 2,
    )
    click_fn(point, origin)
    sleep_fn(0.35)

    result = speedup_runner(execute=True)
    if result.status != "FINISHED":
        return "active"

    after_frame, after_origin = capture_fn()
    if (
        (after_frame.shape[1], after_frame.shape[0]) != EXPECTED_SIZE
        or tuple(after_origin) != tuple(origin)
    ):
        return "unknown"
    after = _read_current_training_state(after_frame, variant, include_numeric=False)
    return after["status"]