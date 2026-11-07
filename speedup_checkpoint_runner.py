"""Run the approved checkpoint-based speedup scan and optional item-use loop."""

import time
from dataclasses import dataclass

import cv2
import numpy as np

from speedup import FINISHED, NOT_ENOUGH, PLANNED, UNCERTAIN
from speedup_calibration import CHANGE_THRESHOLD, dialog_anchor_matches, load_speedup_regions
from speedup_inventory_reader import (
    CheckpointInventoryReading,
    combine_checkpoint_readings,
    read_checkpoint_viewport,
)
from speedup_planner import STATUS_NOTHING_TO_DO, STATUS_SHORTFALL, plan_speedups
from speedup_reader import read_remaining_time

BLOCKED = "BLOCKED"
CHECKPOINT_ORDER = (3, 11, 16)
EXPECTED_FRAME_SIZE = (1920, 1080)
SETTLE_SECONDS = 0.35
REPLAN_BELOW_FRACTION = 0.2


@dataclass(frozen=True)
class CheckpointRunResult:
    status: str
    reason: str
    plan: object = None
    inventory: tuple = ()
    used: tuple = ()
    shortfall_seconds: int = 0
    replan: object = None
    checkpoint_steps: tuple = ()
    remaining_seconds: int | None = None
    inventory_evidence: tuple = ()


class _Abort(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _frame_size(frame):
    return int(frame.shape[1]), int(frame.shape[0])


def _viewport_crop(frame, region):
    x, y, width, height = (int(region[key]) for key in ("x", "y", "w", "h"))
    crop = frame[y:y + height, x:x + width]
    if crop.shape[:2] != (height, width):
        raise ValueError("inventory_viewport_outside_frame")
    return crop


def _changed(previous, current):
    difference = np.abs(current.astype(np.int16) - previous.astype(np.int16))
    return float(np.mean(np.max(difference, axis=2) > 12))


def _expanded_uses(plan):
    return [duration for duration, count in plan.uses for _ in range(count)]


class _CheckpointRunner:
    def __init__(
        self,
        capture_fn,
        move_fn,
        scroll_fn,
        click_fn,
        stop_fn,
        sleep_fn,
        button_map,
        button_template,
        regions,
        dry_run,
        anchor_fn,
        timer_reader_fn,
        inventory_reader_fn,
        frame_size_fn,
        viewport_crop_fn,
        viewport_change_fn,
        expected_frame_size,
    ):
        self.capture_fn = capture_fn
        self.move_fn = move_fn
        self.scroll_fn = scroll_fn
        self.click_fn = click_fn
        self.stop_fn = stop_fn
        self.sleep_fn = sleep_fn
        self.button_map = button_map
        self.button_template = button_template
        self.regions = regions
        self.dry_run = dry_run
        self.anchor_fn = anchor_fn
        self.timer_reader_fn = timer_reader_fn
        self.inventory_reader_fn = inventory_reader_fn
        self.frame_size_fn = frame_size_fn
        self.viewport_crop_fn = viewport_crop_fn
        self.viewport_change_fn = viewport_change_fn
        self.expected_frame_size = tuple(expected_frame_size)
        self.frame = None
        self.origin = None
        self.current_step = 0
        self.clicks_issued = 0
        self.used = {}
        self.stock = {}
        self.initial_timer = None
        self.plan = None
        self.replan = None
        self.inventory = None
        self.inventory_items = ()
        self.remaining_seconds = None
        self.checkpoint_steps = ()

    def abort(self, reason, after_click=False):
        status = UNCERTAIN if after_click or self.clicks_issued else BLOCKED
        raise _Abort(status, reason)

    def check_stop(self):
        try:
            self.stop_fn()
        except Exception as error:
            self.abort(f"emergency_stop:{error}")

    def capture(self, require_dialog=True):
        try:
            frame, origin = self.capture_fn()
        except Exception as error:
            self.abort(f"capture_failed:{error}")
        if tuple(self.frame_size_fn(frame)) != self.expected_frame_size:
            self.abort(f"unexpected_frame_size:{self.frame_size_fn(frame)}")
        if self.origin is not None and tuple(origin) != tuple(self.origin):
            self.abort("capture_origin_changed")
        if self.origin is None:
            self.origin = tuple(origin)
        if require_dialog and not self.anchor_fn(frame):
            self.abort("speedup_dialog_not_recognized")
        self.frame = frame
        return frame

    def timer(self, frame):
        try:
            reading = self.timer_reader_fn(frame)
        except Exception as error:
            self.abort(f"timer_read_failed:{error}")
        if reading is None or reading.value is None:
            self.abort(f"timer_unreadable:{getattr(reading, 'status', 'unknown')}")
        return reading

    def _pointer_point(self):
        viewport = self.regions["speedup_inventory_viewport"]
        return (
            self.origin[0] + int(viewport["x"]) + int(viewport["w"]) // 2,
            self.origin[1] + int(viewport["y"]) + int(viewport["h"]) // 2,
        )

    def _scroll_once(self, direction):
        self.check_stop()
        try:
            self.move_fn(*self._pointer_point())
        except Exception as error:
            self.abort(f"pointer_move_failed:{error}")
        self.check_stop()
        try:
            self.scroll_fn(direction)
        except Exception as error:
            self.abort(f"scroll_failed:{error}")
        self.sleep_fn(SETTLE_SECONDS)
        following = self.capture()
        before = self.viewport_crop_fn(self.frame_before_scroll, self.regions["speedup_inventory_viewport"])
        after = self.viewport_crop_fn(following, self.regions["speedup_inventory_viewport"])
        if self.viewport_change_fn(before, after) <= CHANGE_THRESHOLD:
            self.abort("viewport_unchanged")
        self.current_step += 1 if direction < 0 else -1
        return following

    def scroll(self, direction):
        self.frame_before_scroll = self.frame
        return self._scroll_once(direction)

    def read_checkpoint(self, frame, step):
        checkpoint = next((item for item in self.button_map["checkpoints"] if item["scroll_count"] == step), None)
        if checkpoint is None:
            self.abort(f"checkpoint_not_mapped:{step}")
        try:
            viewport = self.viewport_crop_fn(frame, self.regions["speedup_inventory_viewport"])
            reading = self.inventory_reader_fn(
                viewport,
                checkpoint,
                self.button_template,
                self.regions["speedup_item_quantity"],
                self.regions["speedup_use_button"],
                expected_viewport_size=(
                    int(self.button_map["viewport_size"]["width"]),
                    int(self.button_map["viewport_size"]["height"]),
                ),
            )
        except Exception as error:
            self.abort(f"inventory_read_failed:{error}")
        if reading.status != "complete":
            self.abort(f"inventory_incomplete:{step}:{reading.reason}")
        return reading

    def scan(self):
        frame = self.capture()
        initial_timer = self.timer(frame)
        self.initial_timer = initial_timer.value
        previous = self.viewport_crop_fn(frame, self.regions["speedup_inventory_viewport"])
        checkpoint_readings = []
        for step in range(1, CHECKPOINT_ORDER[-1] + 1):
            frame = self.scroll(-1)
            if step in CHECKPOINT_ORDER:
                checkpoint_readings.append(self.read_checkpoint(frame, step))
            previous = self.viewport_crop_fn(frame, self.regions["speedup_inventory_viewport"])

        combined = combine_checkpoint_readings(checkpoint_readings)
        if combined.status != "complete":
            self.abort(f"inventory_incomplete:{combined.reason}")
        latest_timer = self.timer(frame)
        self.inventory = combined.inventory
        self.inventory_items = combined.items
        self.stock = dict(self.inventory)
        self.checkpoint_steps = combined.checkpoint_steps
        self.plan = plan_speedups(latest_timer.value, self.inventory)
        self.remaining_seconds = latest_timer.value
        return latest_timer

    def _mapped_button(self, duration, step):
        labels = self.button_map["preferred_scroll_count_by_duration"]
        duration_label = next((label for label, item in self._duration_by_label().items() if item == duration), None)
        if duration_label is None:
            self.abort(f"duration_not_mapped:{duration}")
        target_step = int(labels.get(duration_label, 0))
        if target_step != step:
            self.abort(f"duration_checkpoint_mismatch:{duration_label}")
        checkpoint = next(item for item in self.button_map["checkpoints"] if item["scroll_count"] == step)
        return next(button for button in checkpoint["buttons"] if button["duration_label"] == duration_label)

    def _duration_by_label(self):
        return {
            button["duration_label"]: int(button["duration_seconds"])
            for checkpoint in self.button_map["checkpoints"]
            for button in checkpoint["buttons"]
        }

    def _navigate_to(self, step):
        while self.current_step != step:
            direction = -1 if step > self.current_step else 1
            self.scroll(direction)
        return self.read_checkpoint(self.frame, step)

    def _click_item(self, duration, step, last_use):
        reading = self._navigate_to(step)
        item = next((item for item in reading.items if item.duration_seconds == duration), None)
        if item is None or item.quantity.value != self.stock[duration]:
            self.abort("inventory_changed_before_use")
        button = self._mapped_button(duration, step)
        center = button["center"]
        viewport = self.regions["speedup_inventory_viewport"]
        point = (
            self.origin[0] + int(viewport["x"]) + int(center["x"]),
            self.origin[1] + int(viewport["y"]) + int(center["y"]),
        )
        self.check_stop()
        self.clicks_issued += 1
        try:
            self.click_fn(point)
        except Exception as error:
            self.abort(f"click_failed:{error}", after_click=True)
        self.sleep_fn(SETTLE_SECONDS)
        after = self.capture(require_dialog=False)
        if not self.anchor_fn(after):
            if last_use:
                self.used[duration] = self.used.get(duration, 0) + 1
                self.stock[duration] -= 1
                return None, None
            self.abort("dialog_closed_before_plan_end", after_click=True)

        after_reading = self.read_checkpoint(after, step)
        after_item = next((item for item in after_reading.items if item.duration_seconds == duration), None)
        expected_quantity = self.stock[duration] - 1
        if after_item is None or after_item.quantity.value != expected_quantity:
            self.abort("use_not_confirmed", after_click=True)
        self.stock[duration] = expected_quantity
        self.used[duration] = self.used.get(duration, 0) + 1
        try:
            timer_reading = self.timer_reader_fn(after)
        except Exception:
            timer_reading = None
        return after, timer_reading

    def execute(self, dry_run):
        latest_timer = self.scan()
        plan = self.plan
        if plan.status == STATUS_NOTHING_TO_DO:
            return self.result(FINISHED, "already_finished", plan)
        if plan.status == STATUS_SHORTFALL:
            return self.result(NOT_ENOUGH, "owned_items_do_not_cover_remaining_time", plan, plan.shortfall_seconds)
        if dry_run:
            return self.result(PLANNED, "dry_run", plan)

        queue = _expanded_uses(plan)
        initial_timer = latest_timer.value
        while queue:
            duration = queue.pop(0)
            label = next((name for name, value in self._duration_by_label().items() if value == duration), None)
            step = int(self.button_map["preferred_scroll_count_by_duration"].get(label, 0))
            if step not in CHECKPOINT_ORDER:
                self.abort(f"duration_checkpoint_missing:{duration}")
            after, timer_reading = self._click_item(duration, step, last_use=not queue)
            if after is None:
                return self.result(FINISHED, "dialog_closed_after_last_use", plan)
            if timer_reading is not None and timer_reading.value == 0:
                return self.result(FINISHED, "timer_reached_zero", plan)
            if (
                self.replan is None
                and timer_reading is not None
                and timer_reading.value is not None
                and timer_reading.value < initial_timer * REPLAN_BELOW_FRACTION
            ):
                self.replan = plan_speedups(timer_reading.value, self.stock)
                if self.replan.status == STATUS_SHORTFALL:
                    return self.result(
                        NOT_ENOUGH,
                        "owned_items_do_not_cover_remaining_time_after_replan",
                        plan,
                        self.replan.shortfall_seconds,
                    )
                queue = _expanded_uses(self.replan)
        return self.result(UNCERTAIN, "timer_not_zero_after_plan", plan)

    def result(self, status, reason, plan=None, shortfall=0):
        return CheckpointRunResult(
            status=status,
            reason=reason,
            plan=plan,
            inventory=tuple(sorted((self.inventory or {}).items())),
            used=tuple(self.used.items()),
            shortfall_seconds=shortfall,
            replan=self.replan,
            checkpoint_steps=self.checkpoint_steps,
            remaining_seconds=self.remaining_seconds,
            inventory_evidence=tuple({
                "duration_label": item.duration_label,
                "duration_seconds": item.duration_seconds,
                "raw_ocr": item.quantity.raw,
                "confidence": item.quantity.confidence,
                "status": item.quantity.status,
                "scroll_count": item.scroll_count,
            } for item in self.inventory_items),
        )


def run_checkpoint_speedups(
    capture_fn,
    move_fn,
    scroll_fn,
    click_fn,
    button_map,
    button_template,
    regions=None,
    stop_fn=lambda: None,
    sleep_fn=time.sleep,
    dry_run=True,
    anchor_fn=None,
    timer_reader_fn=None,
    inventory_reader_fn=None,
    frame_size_fn=None,
    viewport_crop_fn=None,
    viewport_change_fn=None,
    expected_frame_size=EXPECTED_FRAME_SIZE,
):
    """Scan 3/11/16 checkpoints and optionally execute a verified plan."""
    regions = regions or load_speedup_regions()
    runner = _CheckpointRunner(
        capture_fn=capture_fn,
        move_fn=move_fn,
        scroll_fn=scroll_fn,
        click_fn=click_fn,
        stop_fn=stop_fn,
        sleep_fn=sleep_fn,
        button_map=button_map,
        button_template=button_template,
        regions=regions,
        dry_run=dry_run,
        anchor_fn=anchor_fn or dialog_anchor_matches,
        timer_reader_fn=timer_reader_fn or read_remaining_time,
        inventory_reader_fn=inventory_reader_fn or read_checkpoint_viewport,
        frame_size_fn=frame_size_fn or _frame_size,
        viewport_crop_fn=viewport_crop_fn or _viewport_crop,
        viewport_change_fn=viewport_change_fn or _changed,
        expected_frame_size=expected_frame_size,
    )
    try:
        return runner.execute(dry_run)
    except _Abort as error:
        return runner.result(error.status, error.reason, runner.plan)