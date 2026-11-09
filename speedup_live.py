"""Desktop adapter for the checkpoint-based speedup finisher."""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2

from speedup import DialogReading, InventoryRow, finish_with_speedups
from speedup_calibration import (
    CHANGE_THRESHOLD,
    EXPECTED_SIZE,
    _viewport_change,
    dialog_anchor_matches,
    load_speedup_regions,
)
from speedup_inventory_reader import read_checkpoint_viewport
from speedup_readings import ParsedReading
from speedup_reader import configure_tesseract, read_remaining_time

ROOT_DIR = Path(__file__).resolve().parent
BUTTON_MAP_PATH = ROOT_DIR / "speedup_button_map.json"
CHECKPOINT_STEPS = (3, 11, 16)
MAX_SCROLL_STEPS = 20
SETTLE_SECONDS = 0.35


class LiveSpeedupError(ValueError):
    """The desktop speedup dialog could not be operated safely."""


def load_speedup_button_map(path=BUTTON_MAP_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LiveSpeedupError(f"button_map_unreadable:{error}") from error
    steps = tuple(item.get("scroll_count") for item in data.get("checkpoints", ()))
    if steps != CHECKPOINT_STEPS or data.get("coordinate_space") != "speedup_inventory_viewport":
        raise LiveSpeedupError("button_map_checkpoint_contract_mismatch")
    return data


def create_desktop_callbacks(
    capture_screen_fn,
    move_fn,
    wheel_fn,
    click_screen_fn,
    display_size_fn,
    stop_fn,
    sleep_fn=time.sleep,
    regions=None,
    button_map=None,
    button_template=None,
    anchor_fn=dialog_anchor_matches,
    timer_reader=read_remaining_time,
    inventory_reader=read_checkpoint_viewport,
    expected_size=EXPECTED_SIZE,
    capture_observer=None,
):
    """Create injected callbacks compatible with `finish_with_speedups`.

    The list is first moved to its top endpoint, then scanned one wheel notch at a
    time. Inventory rows are accepted only at the reviewed cumulative checkpoints.
    """
    regions = regions or load_speedup_regions()
    button_map = button_map or load_speedup_button_map()
    if button_template is None:
        template_path = ROOT_DIR / button_map["button_template"]
        button_template = cv2.imread(str(template_path))
    if button_template is None:
        raise LiveSpeedupError("use_button_template_unreadable")

    viewport = regions["speedup_inventory_viewport"]
    quantity_region = regions["speedup_item_quantity"]
    use_region = regions["speedup_use_button"]
    checkpoints = {item["scroll_count"]: item for item in button_map["checkpoints"]}
    state = {
        "origin": (0, 0),
        "position": None,
        "previous_viewport": None,
        "pending_direction": None,
        "last_down_unchanged": False,
        "reads": [],
    }

    def capture_fn():
        frame, origin = capture_screen_fn()
        frame_size = (int(frame.shape[1]), int(frame.shape[0]))
        if frame_size != tuple(expected_size):
            raise LiveSpeedupError(f"unexpected_frame_size:{frame_size}")
        display_size = tuple(map(int, display_size_fn()))
        if display_size != frame_size:
            raise LiveSpeedupError(f"display_size_mismatch:{display_size}")
        state["origin"] = tuple(map(int, origin))
        if capture_observer is not None:
            capture_observer(frame, state["origin"])
        return frame

    def read_dialog_fn(frame):
        frame_size = (int(frame.shape[1]), int(frame.shape[0]))
        if frame_size != tuple(expected_size) or not anchor_fn(frame, regions):
            state["reads"].append({"status": "dialog_unrecognized"})
            return None

        viewport_image = frame[
            int(viewport["y"]):int(viewport["y"]) + int(viewport["h"]),
            int(viewport["x"]):int(viewport["x"]) + int(viewport["w"]),
        ]
        if viewport_image.shape[:2] != (int(viewport["h"]), int(viewport["w"])):
            state["reads"].append({"status": "viewport_outside_frame"})
            return None

        previous = state["previous_viewport"]
        direction = state["pending_direction"]
        changed = True if previous is None else _viewport_change(previous, viewport_image) > CHANGE_THRESHOLD
        if direction == -1:
            state["position"] = None if changed else 0
            state["last_down_unchanged"] = False
        elif direction == 1:
            if state["position"] is None:
                state["reads"].append({"status": "list_top_not_established"})
                return None
            if changed:
                state["position"] += 1
            state["last_down_unchanged"] = not changed
        else:
            state["last_down_unchanged"] = False
        state["pending_direction"] = None
        state["previous_viewport"] = viewport_image.copy()

        if state["position"] is None:
            signature = hashlib.sha256(viewport_image.tobytes()).hexdigest()
            rows = ()
            rows_complete = True
            timer = timer_reader(frame)
        else:
            position = state["position"]
            signature = f"list_step:{position}"
            timer = timer_reader(frame)
            rows = ()
            rows_complete = True
            if position in checkpoints:
                checkpoint = checkpoints[position]
                inventory = inventory_reader(
                    viewport_image,
                    checkpoint,
                    button_template,
                    quantity_region,
                    use_region,
                )
                rows_complete = inventory.status == "complete"
                rows = tuple(
                    InventoryRow(
                        item.duration_seconds,
                        item.quantity.value,
                        (
                            int(viewport["x"]) + int(item.button_center["x"]),
                            int(viewport["y"]) + int(item.button_center["y"]),
                        ),
                    )
                    for item in inventory.items
                )
                state["reads"].append({
                    "step": position,
                    "status": inventory.status,
                    "reason": inventory.reason,
                    "items": len(rows),
                })
            elif position > CHECKPOINT_STEPS[-1]:
                rows_complete = False
                state["reads"].append({"step": position, "status": "past_last_checkpoint"})
            elif state["last_down_unchanged"] and position < CHECKPOINT_STEPS[-1]:
                rows_complete = False
                state["reads"].append({"step": position, "status": "list_ended_before_last_checkpoint"})

        if timer.value is None:
            rows_complete = False
        return DialogReading(timer, rows, rows_complete, signature)

    def scroll_fn(direction):
        if direction not in {-1, 1}:
            raise LiveSpeedupError("invalid_scroll_direction")
        stop_fn()
        origin_x, origin_y = state["origin"]
        center = (
            origin_x + int(viewport["x"]) + int(viewport["w"]) // 2,
            origin_y + int(viewport["y"]) + int(viewport["h"]) // 2,
        )
        move_fn(*center)
        stop_fn()
        wheel_fn(-direction)
        sleep_fn(SETTLE_SECONDS)
        state["pending_direction"] = direction

    def click_fn(point):
        stop_fn()
        origin_x, origin_y = state["origin"]
        click_screen_fn(origin_x + int(point[0]), origin_y + int(point[1]))

    return capture_fn, read_dialog_fn, click_fn, scroll_fn, state


def finish_open_dialog(
    capture_screen_fn,
    move_fn,
    wheel_fn,
    click_screen_fn,
    display_size_fn,
    stop_fn,
    execute=False,
    sleep_fn=time.sleep,
    max_scroll_steps=MAX_SCROLL_STEPS,
    capture_observer=None,
    **reader_options,
):
    callbacks = create_desktop_callbacks(
        capture_screen_fn,
        move_fn,
        wheel_fn,
        click_screen_fn,
        display_size_fn,
        stop_fn,
        sleep_fn=sleep_fn,
        capture_observer=capture_observer,
        **reader_options,
    )
    capture_fn, read_dialog_fn, click_fn, scroll_fn, state = callbacks
    result = finish_with_speedups(
        capture_fn,
        read_dialog_fn,
        click_fn,
        scroll_fn,
        stop_fn=stop_fn,
        sleep_fn=sleep_fn,
        dry_run=not execute,
        max_scrolls=max_scroll_steps,
    )
    return result, state


def _capture_primary_monitor():
    import mss
    import numpy as np

    with mss.mss() as capture:
        monitor = capture.monitors[1]
        frame = np.asarray(capture.grab(monitor))
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR), (int(monitor["left"]), int(monitor["top"]))


def _display_size():
    import pyautogui

    return pyautogui.size()


def _move_pointer(x, y):
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.moveTo(x, y)


def _wheel(notches):
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.scroll(notches)


def _click_screen(x, y):
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.click(x, y)


def _stop_file():
    stop_file = Path.home() / ".tba_stop"
    if stop_file.exists():
        raise LiveSpeedupError(f"emergency_stop:{stop_file}")


def run_desktop_speedups(
    execute=False,
    sleep_fn=time.sleep,
    max_scroll_steps=MAX_SCROLL_STEPS,
    evidence_dir=None,
):
    configure_tesseract()
    if evidence_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        evidence_dir = ROOT_DIR / "debug" / "speedup" / f"run_{timestamp}"
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    captures = []

    def observe_capture(frame, origin):
        file_name = f"frame_{len(captures):03d}.png"
        path = evidence_dir / file_name
        if not cv2.imwrite(str(path), frame):
            raise LiveSpeedupError(f"capture_save_failed:{path}")
        captures.append({
            "file": file_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "frame_size": [int(frame.shape[1]), int(frame.shape[0])],
            "monitor_origin": list(origin),
        })

    manifest_path = evidence_dir / "manifest.json"
    result = None
    error = None
    state = {"reads": []}
    try:
        result, state = finish_open_dialog(
            _capture_primary_monitor,
            _move_pointer,
            _wheel,
            _click_screen,
            _display_size,
            _stop_file,
            execute=execute,
            sleep_fn=sleep_fn,
            max_scroll_steps=max_scroll_steps,
            capture_observer=observe_capture,
        )
        state["evidence_dir"] = str(evidence_dir)
        return result, state
    except Exception as caught:
        error = str(caught)
        raise
    finally:
        manifest = {
            "mode": "execute" if execute else "dry_run",
            "captures": captures,
            "reads": state.get("reads", []),
            "result": result.__dict__ if result is not None else None,
            "error": error,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")