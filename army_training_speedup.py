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
from army_training_scanner import locate_finish_training_button
from ui_variants import resolve_variant

LOGGER = logging.getLogger(__name__)
MAX_FINISH_ROUNDS = 3


def finish_active_training_with_speedups(
    capture_fn=None,
    click_fn=None,
    sleep_fn=time.sleep,
    speedup_runner=None,
    move_fn=None,
    on_finish_button_click=None,
    max_rounds=MAX_FINISH_ROUNDS,
    trace=None,
):
    """Repeat the finish round while real speedup clicks were made and training is still active."""
    state = "unknown"
    for round_number in range(1, max_rounds + 1):
        progress = []
        state = _finish_round(
            capture_fn, click_fn, sleep_fn, speedup_runner, move_fn, on_finish_button_click, progress, trace,
        )
        if trace is not None:
            trace.record("speedup_round_result", observation={"round": round_number, "state": state,
                         "speedups_used": bool(progress)}, decision="continue" if state == "active" and progress else "stop")
        if state != "active" or not progress:
            return state
        LOGGER.info("Training still active after speedup round %d/%d; starting another", round_number, max_rounds)
    return state


def _finish_round(
    capture_fn=None,
    click_fn=None,
    sleep_fn=time.sleep,
    speedup_runner=None,
    move_fn=None,
    on_finish_button_click=None,
    progress=None,
    trace=None,
):
    """Use owned speedups only for an active, bot-managed training task."""
    from speedup_run import run_open_dialog

    capture_fn = capture_fn or capture_primary_monitor
    click_fn = click_fn or _click_screen_point
    speedup_runner = speedup_runner or run_open_dialog
    variant = resolve_variant()
    frame, origin = capture_fn()
    if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
        if trace is not None:
            trace.record("capture_army_state", observation={"frame_size": (frame.shape[1], frame.shape[0])},
                         decision="block", reason="unsupported_frame_size")
        return "unknown"

    before = _read_current_training_state(frame, variant, include_numeric=False)
    if trace is not None:
        trace.record("observe_army_state", observation=before, decision="continue" if before["status"] in {"active", "completed"} else "stop")
    if before["status"] == "idle":
        return "idle"
    regions = _load_regions(variant["regions"]).get("army_training", {})
    if before["status"] == "completed":
        return _click_finish_button(
            frame, origin, variant, regions, capture_fn, click_fn, sleep_fn, move_fn, on_finish_button_click,
            trace,
        )
    if before["status"] != "active":
        return before["status"]
    observed_button_state = before.get("button_state")
    if observed_button_state in {"help", "absent"}:
        LOGGER.info("Speedup skipped because the observed panel state is %s", observed_button_state)
        if trace is not None:
            trace.record("speedup_decision", observation={"button_state": observed_button_state},
                         decision="skip", reason="speedup_button_not_available")
        return "active"

    button = regions.get("speedup_panel")
    if not button:
        return "unknown"
    if not before.get("speedup_button_detected"):
        LOGGER.info(
            "Speedup button template not visible; clicking its configured region in the active-training finish flow"
        )
    if trace is not None:
        trace.record("speedup_panel_click", target="speedup_panel", decision="click",
                     observation={"button_detected": before.get("speedup_button_detected")})
    _check_emergency_stop()
    _enable_live_failsafe(click_fn)
    point = (
        int(button["x"]) + int(button["w"]) // 2,
        int(button["y"]) + int(button["h"]) // 2,
    )
    click_fn(point, origin)
    sleep_fn(0.35)

    result = speedup_runner(execute=True)
    if trace is not None:
        trace.record("speedup_runner_result", observation={"status": result.status,
                     "reason": getattr(result, "reason", None), "used": getattr(result, "used", ())},
                     decision="reconcile")
    if progress is not None and getattr(result, "used", ()):
        progress.append(True)
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
        if trace is not None:
            trace.record("verify_post_speedup_capture", observation={"frame_size": (after_frame.shape[1], after_frame.shape[0]),
                         "origin": after_origin}, decision="block", verification="failed", reason="capture_geometry_changed")
        return "unknown"
    after = _read_current_training_state(after_frame, variant, include_numeric=False)
    if trace is not None:
        trace.record("verify_post_speedup_state", observation=after, decision="reconcile",
                     verification=after["status"])
    LOGGER.info("Speedup result=%s; observed army state=%s", result.status, after["status"])
    if after["status"] in {"unknown", "completed"}:
        return _click_finish_button(
            after_frame, after_origin, variant, regions, capture_fn, click_fn, sleep_fn, move_fn,
            on_finish_button_click, trace,
        )
    return after["status"]


def _click_finish_button(
    frame, origin, variant, regions, capture_fn, click_fn, sleep_fn, move_fn, on_finish_button_click, trace=None,
):
    """Click the matched finish button once and report `idle` only from a fresh frame."""
    score, finish_point = locate_finish_training_button(frame, variant)
    if finish_point is None:
        if trace is not None:
            trace.record("locate_finish_button", decision="block", verification="not_found")
        return "unknown"
    if on_finish_button_click is None:
        LOGGER.warning("Finish button is visible without an open-training attempt recorder; click blocked")
        if trace is not None:
            trace.record("finish_button_decision", decision="block", reason="attempt_recorder_missing")
        return "unknown"
    finish_button = regions.get("finish_training_button")
    _check_emergency_stop()
    _enable_live_failsafe(click_fn)
    move_fn = move_fn or _move_cursor_screen_point
    move_fn(_cursor_away_point(frame, finish_button), origin)
    _check_emergency_stop()
    on_finish_button_click()
    if trace is not None:
        trace.record("finish_button_click", target="finish_training_button",
                     observation={"match_score": score}, action={"point": finish_point}, decision="click")
    click_fn(finish_point, origin)
    sleep_fn(0.35)
    final_frame, final_origin = capture_fn()
    if (
        (final_frame.shape[1], final_frame.shape[0]) != EXPECTED_SIZE
        or tuple(final_origin) != tuple(origin)
    ):
        LOGGER.warning("Finish button was clicked but the follow-up capture geometry changed")
        if trace is not None:
            trace.record("verify_finish_button_result", observation={"frame_size": (final_frame.shape[1], final_frame.shape[0]),
                         "origin": final_origin}, decision="stop", verification="unknown", reason="capture_geometry_changed")
        return "unknown"
    final = _read_current_training_state(final_frame, variant, include_numeric=False)
    LOGGER.info("Finish button match=%.3f; post-click army state=%s", score, final["status"])
    if trace is not None:
        trace.record("verify_finish_button_result", observation=final, decision="complete" if final["status"] == "idle" else "stop",
                     verification="confirmed" if final["status"] == "idle" else "not_confirmed")
    return "idle" if final["status"] == "idle" else "unknown"


def _move_cursor_screen_point(point, origin):
    try:
        import pyautogui
    except ImportError as error:
        raise RuntimeError("Live execution requires the 'pyautogui' package.") from error
    pyautogui.moveTo(origin[0] + point[0], origin[1] + point[1])


def _cursor_away_point(frame, region):
    frame_height, frame_width = frame.shape[:2]
    left, top = int(region["x"]), int(region["y"])
    right, bottom = left + int(region["w"]), top + int(region["h"])
    candidates = (
        (frame_width // 2, frame_height // 2),
        (frame_width // 2, frame_height * 9 // 10),
        (frame_width // 10, frame_height // 2),
    )
    for point in candidates:
        if not (left <= point[0] < right and top <= point[1] < bottom):
            return point
    raise ValueError("Could not find a cursor position outside the finish button region.")