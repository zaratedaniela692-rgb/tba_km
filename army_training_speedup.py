"""Bridge the army training panel to the standalone desktop speedup finisher."""

import time
import logging

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

LOGGER = logging.getLogger(__name__)


def finish_active_training_with_speedups(
    capture_fn=None,
    click_fn=None,
    sleep_fn=time.sleep,
    speedup_runner=None,
):
    """Use owned speedups only for an active, bot-managed training task."""
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
    if before["status"] != "active":
        return before["status"]
    observed_button_state = before.get("button_state")
    if observed_button_state in {"help", "absent"}:
        LOGGER.info("Speedup skipped because the observed panel state is %s", observed_button_state)
        return "active"

    regions = _load_regions(variant["regions"]).get("army_training", {})
    button = regions.get("speedup_panel")
    if not button:
        return "unknown"
    if not before.get("speedup_button_detected"):
        LOGGER.info(
            "Speedup button template not visible; clicking its configured region in the active-training finish flow"
        )
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
        LOGGER.warning(
            "Speedup stopped: status=%s reason=%s; checking fresh army state before deciding completion",
            result.status, getattr(result, "reason", "not_reported"),
        )

    after_frame, after_origin = capture_fn()
    if (
        (after_frame.shape[1], after_frame.shape[0]) != EXPECTED_SIZE
        or tuple(after_origin) != tuple(origin)
    ):
        return "unknown"
    after = _read_current_training_state(after_frame, variant, include_numeric=False)
    LOGGER.info("Speedup result=%s; observed army state=%s", result.status, after["status"])
    return after["status"]