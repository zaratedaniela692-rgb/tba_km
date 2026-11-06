"""Capture the speedup list after bounded, supervised mouse-wheel steps."""

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent
REGIONS_PATH = ROOT_DIR / "regions.json"
STOP_FILE = Path.home() / ".tba_stop"
EXPECTED_SIZE = (1920, 1080)
MAX_STEPS = 20
DEFAULT_STEPS = 20
CHECKPOINT_STEPS = (3, 11, 16)
CHECKPOINT_LABELS = {
    3: ("15m", "1h", "3h", "8h"),
    11: ("15h", "1d", "3d", "7d"),
    16: ("3d", "7d", "30d"),
}
SETTLE_SECONDS = 0.35
CONFIRMATION_PHRASE = "SCROLL SPEEDUP LIST"
ANCHOR_THRESHOLD = 0.95
ANCHOR_SEARCH_MARGIN = 8
CHANGE_THRESHOLD = 0.003


class CalibrationError(ValueError):
    """The calibration could not safely continue."""


@dataclass(frozen=True)
class CalibrationResult:
    status: str
    reason: str
    output_dir: str
    captures: int
    scrolls: int


def load_speedup_regions(path=REGIONS_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        return data["speedup"]
    except (KeyError, TypeError) as error:
        raise CalibrationError("regions.json does not contain speedup regions") from error


def dialog_anchor_matches(frame, regions=None, root_dir=ROOT_DIR):
    regions = regions or load_speedup_regions()
    region = regions["speedup_dialog_anchor"]
    template_path = root_dir / region["template"]
    template = cv2.imread(str(template_path))
    if template is None:
        raise CalibrationError(f"Could not load dialog anchor template: {template_path}")
    region_left, region_top, width, height = (int(region[key]) for key in ("x", "y", "w", "h"))
    margin = ANCHOR_SEARCH_MARGIN
    search_left = max(0, region_left - margin)
    search_top = max(0, region_top - margin)
    search_right = min(frame.shape[1], region_left + width + margin)
    search_bottom = min(frame.shape[0], region_top + height + margin)
    search = frame[search_top:search_bottom, search_left:search_right]
    if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
        return False
    scores = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, _ = cv2.minMaxLoc(scores)
    return score >= ANCHOR_THRESHOLD


def _viewport_crop(frame, region):
    region_left, region_top, width, height = (int(region[key]) for key in ("x", "y", "w", "h"))
    crop = frame[region_top:region_top + height, region_left:region_left + width]
    if crop.shape[:2] != (height, width):
        raise CalibrationError("The annotated inventory viewport is outside the captured frame")
    return crop


def _viewport_change(previous, current):
    difference = np.abs(current.astype(np.int16) - previous.astype(np.int16))
    changed = np.max(difference, axis=2) > 12
    return float(np.mean(changed))


def _save_frame(path, frame):
    if not cv2.imwrite(str(path), frame):
        raise CalibrationError(f"Could not save screenshot: {path}")


def _write_manifest(path, manifest):
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _check_stop(stop_fn):
    try:
        stop_fn()
    except Exception as error:
        raise CalibrationError(f"emergency_stop:{error}") from error


def run_scroll_calibration(
    capture_fn,
    move_fn,
    scroll_fn,
    display_size_fn,
    output_dir,
    stop_fn=lambda: None,
    sleep_fn=time.sleep,
    save_frame_fn=_save_frame,
    anchor_fn=dialog_anchor_matches,
    regions=None,
    max_steps=DEFAULT_STEPS,
    checkpoints=None,
    expected_size=EXPECTED_SIZE,
):
    if not 1 <= max_steps <= MAX_STEPS:
        raise CalibrationError(f"max_steps must be between 1 and {MAX_STEPS}")
    if checkpoints is not None:
        checkpoints = tuple(checkpoints)
        if not checkpoints or tuple(sorted(set(checkpoints))) != checkpoints:
            raise CalibrationError("checkpoints must be a non-empty, increasing sequence")
        if checkpoints[-1] > max_steps:
            raise CalibrationError("all checkpoints must be within max_steps")

    regions = regions or load_speedup_regions()
    viewport = regions["speedup_inventory_viewport"]
    pointer_x = int(viewport["x"]) + int(viewport["w"]) // 2
    pointer_y = int(viewport["y"]) + int(viewport["h"]) // 2
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = output_dir / "manifest.json"
    manifest = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "region": "speedup_inventory_viewport",
        "viewport": {key: int(viewport[key]) for key in ("x", "y", "w", "h")},
        "pointer_frame_point": {"x": pointer_x, "y": pointer_y},
        "expected_frame_size": list(expected_size),
        "mode": "checkpoint" if checkpoints is not None else "step_by_step",
        "captures": [],
        "checks": [],
        "scrolls": [],
        "reason": None,
    }

    def finish(status, reason):
        manifest["status"] = status
        manifest["reason"] = reason
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_manifest(manifest_path, manifest)
        return CalibrationResult(status, reason, str(output_dir), len(manifest["captures"]), len(manifest["scrolls"]))

    frame, origin = capture_fn()
    frame_size = (int(frame.shape[1]), int(frame.shape[0]))
    manifest["frame_size"] = list(frame_size)
    manifest["monitor_origin"] = [int(origin[0]), int(origin[1])]
    if checkpoints is None:
        initial_path = output_dir / "step_000_initial.png"
        save_frame_fn(initial_path, frame)
        manifest["captures"].append({
            "step": 0,
            "action": "initial",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "file": initial_path.name,
        })

    if frame_size != tuple(expected_size):
        return finish("BLOCKED", f"unexpected_frame_size:{frame_size}")
    display_size = tuple(map(int, display_size_fn()))
    manifest["display_size"] = list(display_size)
    if display_size != frame_size:
        return finish("BLOCKED", f"display_size_mismatch:{display_size}")
    if not anchor_fn(frame, regions):
        return finish("BLOCKED", "speedup_dialog_not_recognized")

    previous_viewport = _viewport_crop(frame, viewport)
    for step in range(1, max_steps + 1):
        move_to = (int(origin[0]) + pointer_x, int(origin[1]) + pointer_y)
        try:
            _check_stop(stop_fn)
            move_fn(*move_to)
            _check_stop(stop_fn)
            scroll_fn(-1)
        except CalibrationError as error:
            return finish("BLOCKED", str(error))
        except Exception as error:
            return finish("BLOCKED", f"input_failed:{error}")
        manifest["scrolls"].append({
            "step": step,
            "direction": "down",
            "wheel_notches": 1,
            "pointer_desktop_point": {"x": move_to[0], "y": move_to[1]},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        sleep_fn(SETTLE_SECONDS)
        frame, next_origin = capture_fn()
        next_size = (int(frame.shape[1]), int(frame.shape[0]))
        if next_size != frame_size or tuple(next_origin) != tuple(origin):
            _write_manifest(manifest_path, manifest)
            return finish("BLOCKED", "capture_geometry_changed")
        if not anchor_fn(frame, regions):
            if checkpoints is None:
                capture_path = output_dir / f"step_{step:03d}_after_scroll.png"
                save_frame_fn(capture_path, frame)
                manifest["captures"].append({"step": step, "action": "after_scroll", "file": capture_path.name})
            _write_manifest(manifest_path, manifest)
            return finish("BLOCKED", "speedup_dialog_not_recognized_after_scroll")
        current_viewport = _viewport_crop(frame, viewport)
        changed_fraction = _viewport_change(previous_viewport, current_viewport)
        check_record = {
            "step": step,
            "dialog_recognized": True,
            "viewport_changed_fraction": changed_fraction,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        manifest["checks"].append(check_record)
        if checkpoints is None:
            capture_path = output_dir / f"step_{step:03d}_after_scroll.png"
            save_frame_fn(capture_path, frame)
            manifest["captures"].append({
                "step": step,
                "action": "after_scroll",
                "timestamp": check_record["timestamp"],
                "file": capture_path.name,
                "dialog_recognized": True,
                "viewport_changed_fraction": changed_fraction,
            })
        elif changed_fraction <= CHANGE_THRESHOLD:
            _write_manifest(manifest_path, manifest)
            return finish("LANDMARK_MISMATCH", f"viewport_unchanged_before_checkpoint:{step}")
        elif step in checkpoints:
            capture_path = output_dir / f"checkpoint_{step:03d}_after_scroll.png"
            save_frame_fn(capture_path, frame)
            checkpoint_record = {
                "step": step,
                "action": "checkpoint",
                "timestamp": check_record["timestamp"],
                "file": capture_path.name,
                "reported_visible_durations": list(CHECKPOINT_LABELS.get(step, ())),
            }
            manifest["captures"].append(checkpoint_record)
            manifest.setdefault("checkpoints", []).append(checkpoint_record)
        _write_manifest(manifest_path, manifest)
        if changed_fraction <= CHANGE_THRESHOLD:
            return finish("COMPLETE", "viewport_unchanged")
        previous_viewport = current_viewport

    if checkpoints is not None:
        captured_steps = tuple(record["step"] for record in manifest.get("checkpoints", []))
        if captured_steps == checkpoints:
            return finish("CHECKPOINTS_CAPTURED", "all_checkpoints_reached")
        return finish("LANDMARK_MISMATCH", f"checkpoint_sequence_incomplete:{captured_steps}")
    return finish("STEP_LIMIT", "maximum_scroll_steps_reached")


def _capture_primary_monitor():
    import mss

    with mss.mss() as capture:
        monitor = capture.monitors[1]
        frame = np.asarray(capture.grab(monitor))
    image = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    return image, (int(monitor["left"]), int(monitor["top"]))


def _desktop_size():
    import pyautogui

    return tuple(map(int, pyautogui.size()))


def _move_pointer(desktop_x, desktop_y):
    import pyautogui

    pyautogui.moveTo(desktop_x, desktop_y)


def _scroll_down(notches):
    import pyautogui

    pyautogui.scroll(notches)


def _emergency_stop():
    if STOP_FILE.exists():
        raise RuntimeError(f"Emergency stop file exists: {STOP_FILE}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Capture the speedup list while safely calibrating wheel scrolling.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--calibrate-scroll", action="store_true", help="capture the open speedup list after each wheel step")
    modes.add_argument("--checkpoint-scan", action="store_true", help="save only the approved 3, 11, and 16 scroll checkpoints")
    parser.add_argument("--steps", type=int, help=f"maximum single wheel steps (1-{MAX_STEPS}, default: {DEFAULT_STEPS})")
    parser.add_argument("--confirm", default="", help=f"type exactly: {CONFIRMATION_PHRASE}")
    args = parser.parse_args(argv)
    if args.confirm != CONFIRMATION_PHRASE:
        parser.error(f"live calibration requires --confirm \"{CONFIRMATION_PHRASE}\"")
    if args.checkpoint_scan and args.steps is not None:
        parser.error("--steps cannot be combined with --checkpoint-scan")
    max_steps = args.steps if args.steps is not None else DEFAULT_STEPS
    if not 1 <= max_steps <= MAX_STEPS:
        parser.error(f"--steps must be between 1 and {MAX_STEPS}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_dir = ROOT_DIR / "debug" / "speedup" / f"calibration_{timestamp}"
    try:
        result = run_scroll_calibration(
            _capture_primary_monitor,
            _move_pointer,
            _scroll_down,
            _desktop_size,
            output_dir,
            stop_fn=_emergency_stop,
            max_steps=16 if args.checkpoint_scan else max_steps,
            checkpoints=CHECKPOINT_STEPS if args.checkpoint_scan else None,
        )
    except (CalibrationError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.status in {"COMPLETE", "STEP_LIMIT", "CHECKPOINTS_CAPTURED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())