"""Run the approved checkpoint-based speedup scan and optional item-use loop."""

import time
from dataclasses import dataclass

import cv2
import numpy as np

from speedup import FINISHED, NOT_ENOUGH, PLANNED, UNCERTAIN
from speedup_calibration import CHANGE_THRESHOLD, dialog_anchor_match_details, load_speedup_regions
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
    final_remaining_seconds: int | None = None
    inventory_evidence: tuple = ()
    click_timings: tuple = ()
    checkpoint_diagnostics: tuple = ()
    event_trace: tuple = ()
    final_timer_read_ms: float | None = None


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


def _expanded_plan(plan):
    decisions = iter(getattr(plan, "decisions", ()))
    return [
        (duration, next(decisions, {}))
        for duration, count in plan.uses
        for _ in range(count)
    ]


def _timed_call(function, *args, **kwargs):
    started = time.perf_counter()
    result = function(*args, **kwargs)
    return result, round((time.perf_counter() - started) * 1000, 1)


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
        self.last_observed_timer = None
        self.checkpoint_steps = ()
        self.click_timings = []
        self.checkpoint_diagnostics = []
        self.final_timer_read_ms = None
        self.started_at = time.perf_counter()
        self.event_trace = []

    def dialog_match(self, frame):
        match = (
            self.anchor_fn(frame)
            if self.anchor_fn is not None
            else dialog_anchor_match_details(frame, self.regions)
        )
        if isinstance(match, dict):
            return match
        return {
            "recognized": bool(match),
            "score": None,
            "threshold": None,
            "location": None,
            "partial_score": None,
            "partial_location": None,
            "fallback_used": False,
        }

    def record(self, event, **data):
        self.event_trace.append({
            "elapsed_ms": round((time.perf_counter() - self.started_at) * 1000, 1),
            "event": event,
            "step": self.current_step,
            "data": data,
        })

    def abort(self, reason, after_click=False):
        status = UNCERTAIN if after_click or self.clicks_issued else BLOCKED
        self.record("run_aborted", status=status, reason=reason, clicks_issued=self.clicks_issued)
        raise _Abort(status, reason)

    def check_stop(self):
        try:
            self.stop_fn()
        except Exception as error:
            self.record("emergency_stop_check", status="stopped", reason=str(error))
            self.abort(f"emergency_stop:{error}")
        self.record("emergency_stop_check", status="clear")

    def capture(self, require_dialog=True):
        try:
            frame, origin = self.capture_fn()
        except Exception as error:
            self.record("capture", status="failed", reason=str(error))
            self.abort(f"capture_failed:{error}")
        if tuple(self.frame_size_fn(frame)) != self.expected_frame_size:
            self.record("capture", status="rejected", frame_size=self.frame_size_fn(frame))
            self.abort(f"unexpected_frame_size:{self.frame_size_fn(frame)}")
        if self.origin is not None and tuple(origin) != tuple(self.origin):
            self.record("capture", status="rejected", reason="capture_origin_changed", origin=origin)
            self.abort("capture_origin_changed")
        if self.origin is None:
            self.origin = tuple(origin)
        dialog_match = self.dialog_match(frame) if require_dialog else None
        dialog_recognized = dialog_match["recognized"] if dialog_match is not None else None
        self.record(
            "capture", status="ok", frame_size=self.frame_size_fn(frame), origin=tuple(origin),
            dialog_required=require_dialog, dialog_recognized=bool(dialog_recognized),
            dialog_match=dialog_match,
        )
        if require_dialog and not dialog_recognized:
            self.abort("speedup_dialog_not_recognized")
        self.frame = frame
        return frame

    def timer(self, frame, phase):
        try:
            reading = self.timer_reader_fn(frame)
        except Exception as error:
            self.record("timer_read", phase=phase, status="error", reason=str(error))
            self.abort(f"timer_read_failed:{error}")
        if reading is None or reading.value is None:
            self.record(
                "timer_read", phase=phase, status=getattr(reading, "status", "unreadable"),
                raw=getattr(reading, "raw", ""), value=None,
                confidence=getattr(reading, "confidence", None),
            )
            self.abort(f"timer_unreadable:{getattr(reading, 'status', 'unknown')}")
        self.record(
            "timer_read", phase=phase, status=reading.status, raw=reading.raw,
            value_seconds=reading.value, confidence=reading.confidence,
        )
        return reading

    def _pointer_point(self):
        viewport = self.regions["speedup_inventory_viewport"]
        return (
            self.origin[0] + int(viewport["x"]) + int(viewport["w"]) // 2,
            self.origin[1] + int(viewport["y"]) + int(viewport["h"]) // 2,
        )

    def _scroll_once(self, direction):
        step_before = self.current_step
        self.check_stop()
        try:
            pointer = self._pointer_point()
            self.move_fn(*pointer)
        except Exception as error:
            self.record("pointer_move", status="failed", reason=str(error))
            self.abort(f"pointer_move_failed:{error}")
        self.record("pointer_move", status="ok", point=pointer)
        self.check_stop()
        try:
            self.scroll_fn(direction)
        except Exception as error:
            self.record("scroll", status="failed", direction=direction, reason=str(error))
            self.abort(f"scroll_failed:{error}")
        self.record("scroll", status="sent", direction=direction, from_step=step_before)
        self.sleep_fn(SETTLE_SECONDS)
        following = self.capture()
        before = self.viewport_crop_fn(self.frame_before_scroll, self.regions["speedup_inventory_viewport"])
        after = self.viewport_crop_fn(following, self.regions["speedup_inventory_viewport"])
        change_score = float(self.viewport_change_fn(before, after))
        if change_score <= CHANGE_THRESHOLD:
            self.record(
                "viewport_check", status="unchanged", direction=direction,
                change_score=change_score, threshold=CHANGE_THRESHOLD,
            )
            self.abort("viewport_unchanged")
        self.current_step += 1 if direction < 0 else -1
        self.record(
            "viewport_check", status="changed", direction=direction,
            change_score=change_score, threshold=CHANGE_THRESHOLD, from_step=step_before,
        )
        return following

    def scroll(self, direction):
        self.frame_before_scroll = self.frame
        return self._scroll_once(direction)

    def read_checkpoint(self, frame, step, duration_seconds=None, verify_only=False):
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
                duration_seconds=duration_seconds,
                verify_only=verify_only,
            )
        except Exception as error:
            self.record("checkpoint_read", status="error", reason=str(error), requested_duration=duration_seconds)
            self.abort(f"inventory_read_failed:{error}")
        row_evidence = tuple({
            "duration_label": item.duration_label,
            "duration_seconds": item.duration_seconds,
            "raw_quantity": item.quantity.raw,
            "quantity": item.quantity.value,
            "confidence": item.quantity.confidence,
            "status": item.quantity.status,
            "button_rectangle": item.button_rectangle,
            "button_center": item.button_center,
        } for item in reading.items)
        self.record(
            "checkpoint_read", status=reading.status, reason=reading.reason,
            requested_duration=duration_seconds, rows=row_evidence,
            matches=reading.match_diagnostics, quantities=reading.quantity_diagnostics,
        )
        if reading.match_diagnostics:
            self.checkpoint_diagnostics.append({
                "scroll_count": step,
                "status": reading.status,
                "reason": reading.reason,
                "matches": reading.match_diagnostics,
                "quantities": reading.quantity_diagnostics,
            })
        if reading.status != "complete":
            self.abort(f"inventory_incomplete:{step}:{reading.reason}")
        return reading

    def scan(self):
        self.record("scan_started", checkpoints=CHECKPOINT_ORDER, mode="execute" if not self.dry_run else "dry_run")
        frame = self.capture()
        initial_timer = self.timer(frame, "initial")
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
            self.record("inventory_combined", status=combined.status, reason=combined.reason)
            self.abort(f"inventory_incomplete:{combined.reason}")
        latest_timer = self.timer(frame, "post_scan")
        self.inventory = combined.inventory
        self.inventory_items = combined.items
        self.stock = dict(self.inventory)
        self.checkpoint_steps = combined.checkpoint_steps
        self.remaining_seconds = latest_timer.value
        self.last_observed_timer = latest_timer.value
        owned_seconds = sum(duration * quantity for duration, quantity in self.inventory.items())
        self.record(
            "planning_started", remaining_seconds=latest_timer.value,
            inventory=tuple(sorted(self.inventory.items())),
            owned_seconds=owned_seconds,
            coverage_surplus_seconds=owned_seconds - latest_timer.value,
        )
        self.plan = plan_speedups(latest_timer.value, self.inventory)
        for decision in self.plan.decisions:
            duration_label = next((
                button["duration_label"]
                for checkpoint in self.button_map["checkpoints"]
                for button in checkpoint["buttons"]
                if int(button["duration_seconds"]) == decision["selected_duration_seconds"]
            ), None)
            self.record("plan_choice", duration_label=duration_label, **decision)
        self.record(
            "plan_built", status=self.plan.status,
            remaining_seconds=latest_timer.value,
            inventory=tuple(sorted(self.inventory.items())),
            owned_seconds=owned_seconds,
            coverage_surplus_seconds=owned_seconds - latest_timer.value,
            uses=tuple({
                "duration_seconds": duration,
                "duration_label": next((
                    button["duration_label"]
                    for checkpoint in self.button_map["checkpoints"]
                    for button in checkpoint["buttons"]
                    if int(button["duration_seconds"]) == duration
                ), None),
                "quantity": quantity,
                "total_seconds": duration * quantity,
            } for duration, quantity in self.plan.uses),
            breached_floors=self.plan.breached_floors,
            shortfall_seconds=self.plan.shortfall_seconds,
        )
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
        return self.frame

    def _click_item(self, duration, step, last_use, use_number, plan_generation, plan_step, plan_total):
        timing = {
            "duration_seconds": duration,
            "checkpoint": step,
            "use_number": use_number,
            "plan_generation": plan_generation,
            "plan_step": plan_step,
            "plan_total": plan_total,
        }
        use_context = {
            "use_number": use_number,
            "plan_generation": plan_generation,
            "plan_step": plan_step,
            "plan_total": plan_total,
        }
        started = time.perf_counter()
        frame = self._navigate_to(step)
        timing["navigation_ms"] = round((time.perf_counter() - started) * 1000, 1)

        started = time.perf_counter()
        reading, button_match_ms = _timed_call(
            self.read_checkpoint, frame, step, duration_seconds=duration, verify_only=True,
        )
        if reading.status != "complete":
            self.record(
                "use_button_check", status="failed", duration_seconds=duration,
                reason=reading.reason, matches=reading.match_diagnostics,
                **use_context,
            )
            self.abort(f"use_button_layout_unconfirmed:{reading.reason}")
        duration_label = next((
            button["duration_label"]
            for checkpoint in self.button_map["checkpoints"]
            for button in checkpoint["buttons"]
            if int(button["duration_seconds"]) == duration
        ), None)
        matched_button = next((
            match for match in reading.match_diagnostics
            if match.get("duration_label") == duration_label
        ), None)
        if matched_button is None:
            self.record(
                "use_button_check", status="failed", duration_seconds=duration,
                duration_label=duration_label, matches=reading.match_diagnostics, **use_context,
            )
            self.abort("target_use_button_not_matched")
        timing["button_match_ms"] = button_match_ms
        rectangle = matched_button["detected_rectangle"]
        center = {"x": rectangle["x"] + rectangle["width"] // 2,
                  "y": rectangle["y"] + rectangle["height"] // 2}
        viewport = self.regions["speedup_inventory_viewport"]
        point = (
            self.origin[0] + int(viewport["x"]) + int(center["x"]),
            self.origin[1] + int(viewport["y"]) + int(center["y"]),
        )
        self.record(
            "use_button_check", status="matched", duration_seconds=duration,
            duration_label=duration_label, button_rectangle=rectangle, button_center=center,
            screen_point=point, initial_quantity=self.stock[duration],
            matches=reading.match_diagnostics, **use_context,
        )
        self.check_stop()
        self.clicks_issued += 1
        started = time.perf_counter()
        try:
            self.click_fn(point)
        except Exception as error:
            self.record(
                "use_click", status="failed", duration_seconds=duration,
                screen_point=point, reason=str(error), **use_context,
            )
            self.abort(f"click_failed:{error}", after_click=True)
        self.record("use_click", status="sent", duration_seconds=duration, screen_point=point, **use_context)
        self.sleep_fn(SETTLE_SECONDS)
        after = self.capture(require_dialog=False)
        timing["click_settle_capture_ms"] = round((time.perf_counter() - started) * 1000, 1)
        dialog_match = self.dialog_match(after)
        dialog_recognized = dialog_match["recognized"]
        self.record(
            "dialog_check", status="recognized" if dialog_recognized else "not_recognized",
            phase="post_use", duration_seconds=duration, dialog_match=dialog_match, **use_context,
        )
        if not dialog_recognized:
            self.stock[duration] -= 1
            self.used[duration] = self.used.get(duration, 0) + 1
            self.record(
                "use_verification", status="dialog_closed", quantity_checked=False,
                duration_seconds=duration, **use_context,
            )
            if last_use:
                self.click_timings.append(timing)
                return None, None
            self.abort("dialog_closed_before_plan_end", after_click=True)

        expected_quantity = self.stock[duration] - 1
        self.stock[duration] = expected_quantity
        self.used[duration] = self.used.get(duration, 0) + 1
        self.record(
            "use_verification", status="deferred_to_final_timer", quantity_checked=False,
            expected_quantity=expected_quantity, observed_quantity=None,
            reason="post_click_ocr_disabled", duration_seconds=duration, **use_context,
        )
        self.click_timings.append(timing)
        return after, None

    def execute(self, dry_run):
        latest_timer = self.scan()
        plan = self.plan
        if plan.status == STATUS_NOTHING_TO_DO:
            self.record("execution_decision", action="no_clicks_needed", reason="already_finished")
            return self.result(FINISHED, "already_finished", plan)
        if plan.status == STATUS_SHORTFALL:
            self.record(
                "execution_decision", action="stop_shortfall",
                reason="owned_items_do_not_cover_remaining_time",
                shortfall_seconds=plan.shortfall_seconds,
            )
            return self.result(NOT_ENOUGH, "owned_items_do_not_cover_remaining_time", plan, plan.shortfall_seconds)
        if dry_run:
            self.record("execution_decision", action="plan_only", reason="dry_run_no_clicks")
            return self.result(PLANNED, "dry_run", plan)

        queue = _expanded_plan(plan)
        plan_generation = 1
        plan_total = len(queue)
        plan_step = 0
        self.record(
            "execution_started", plan_generation=plan_generation,
            planned_uses=plan_total,
            planned_seconds=sum(duration for duration, _ in queue),
            initial_timer_seconds=latest_timer.value,
        )
        batch_timer = latest_timer.value
        while True:
            if not queue:
                final_timer, self.final_timer_read_ms = _timed_call(self.timer, self.frame, "final")
                self.last_observed_timer = final_timer.value
                if final_timer.value == 0:
                    self.record("execution_decision", action="finish_timer_zero", reason="final_timer_is_zero")
                    return self.result(FINISHED, "timer_reached_zero", plan)
                if final_timer.value >= batch_timer:
                    self.abort("timer_not_decreased_after_batch", after_click=True)
                self.record(
                    "residual_scan_started", remaining_seconds=final_timer.value,
                    previous_remaining_seconds=batch_timer, estimated_stock=tuple(sorted(self.stock.items())),
                )
                checkpoint_readings = []
                for checkpoint_step in CHECKPOINT_ORDER:
                    self.check_stop()
                    frame = self._navigate_to(checkpoint_step)
                    frame = self.capture()
                    checkpoint_readings.append(self.read_checkpoint(frame, checkpoint_step))
                combined = combine_checkpoint_readings(checkpoint_readings)
                if combined.status != "complete":
                    self.abort(f"residual_inventory_incomplete:{combined.reason}")
                refreshed_stock = combined.inventory
                inventory_confirmed = all(
                    refreshed_stock.get(duration, 0) <= quantity for duration, quantity in self.stock.items()
                )
                self.record(
                    "residual_inventory_verification", status="confirmed" if inventory_confirmed else "failed",
                    expected_maximum_stock=tuple(sorted(self.stock.items())),
                    observed_stock=tuple(sorted(refreshed_stock.items())),
                    reason=None if inventory_confirmed else "submitted_uses_not_confirmed_by_inventory",
                )
                if not inventory_confirmed:
                    self.abort("submitted_uses_not_confirmed_by_inventory", after_click=True)
                self.stock = dict(refreshed_stock)
                residual_timer = self.timer(self.frame, "post_residual_scan")
                self.last_observed_timer = residual_timer.value
                if residual_timer.value == 0:
                    return self.result(FINISHED, "timer_reached_zero", plan)
                if residual_timer.value > final_timer.value:
                    self.abort("timer_increased_during_residual_scan", after_click=True)
                self.replan = plan_speedups(residual_timer.value, self.stock)
                plan_generation += 1
                self.record(
                    "plan_rebuilt", plan_generation=plan_generation, status=self.replan.status,
                    remaining_seconds=residual_timer.value, inventory=tuple(sorted(self.stock.items())),
                    uses=self.replan.uses, shortfall_seconds=self.replan.shortfall_seconds,
                    breached_floors=self.replan.breached_floors,
                    reason="positive_remaining_time_after_batch",
                )
                for residual_decision in self.replan.decisions:
                    self.record("plan_choice", plan_generation=plan_generation, **residual_decision)
                if self.replan.status == STATUS_SHORTFALL:
                    return self.result(
                        NOT_ENOUGH, "owned_items_do_not_cover_remaining_time_after_replan",
                        plan, self.replan.shortfall_seconds,
                    )
                batch_timer = residual_timer.value
                queue = _expanded_plan(self.replan)
                plan_total = len(queue)
                plan_step = 0
                continue
            duration, decision = queue.pop(0)
            plan_step += 1
            label = next((name for name, value in self._duration_by_label().items() if value == duration), None)
            step = int(self.button_map["preferred_scroll_count_by_duration"].get(label, 0))
            if step not in CHECKPOINT_ORDER:
                self.abort(f"duration_checkpoint_missing:{duration}")
            self.record(
                "use_step_started", use_number=self.clicks_issued + 1,
                plan_generation=plan_generation, plan_step=plan_step,
                plan_total=plan_total, duration_seconds=duration,
                duration_label=label, checkpoint=step,
                remaining_queue=len(queue), decision=decision,
            )
            after, _ = self._click_item(
                duration, step, last_use=not queue,
                use_number=self.clicks_issued + 1, plan_generation=plan_generation,
                plan_step=plan_step, plan_total=plan_total,
            )
            if after is None:
                self.record("execution_decision", action="finish_dialog_closed", reason="last_planned_use_closed_dialog")
                return self.result(FINISHED, "dialog_closed_after_last_use", plan)

    def result(self, status, reason, plan=None, shortfall=0):
        self.record(
            "run_finished", status=status, reason=reason,
            clicks_issued=self.clicks_issued, shortfall_seconds=shortfall,
            initial_timer_seconds=self.remaining_seconds,
            final_observed_timer_seconds=self.last_observed_timer,
            submitted_uses=tuple(sorted(self.used.items())),
        )
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
            final_remaining_seconds=self.last_observed_timer,
            inventory_evidence=tuple({
                "duration_label": item.duration_label,
                "duration_seconds": item.duration_seconds,
                "raw_ocr": item.quantity.raw,
                "confidence": item.quantity.confidence,
                "status": item.quantity.status,
                "scroll_count": item.scroll_count,
            } for item in self.inventory_items),
            click_timings=tuple(self.click_timings),
            checkpoint_diagnostics=tuple(self.checkpoint_diagnostics),
            event_trace=tuple(self.event_trace),
            final_timer_read_ms=self.final_timer_read_ms,
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
        anchor_fn=anchor_fn,
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