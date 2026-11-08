from dataclasses import dataclass
from pathlib import Path
import json

import numpy as np
import pytest

from speedup_checkpoint_runner import BLOCKED, FINISHED, NOT_ENOUGH, PLANNED, UNCERTAIN, run_checkpoint_speedups
from speedup_inventory_reader import CheckpointInventoryReading, InventoryItemReading
from speedup_readings import ParsedReading

ROOT = Path(__file__).resolve().parents[1]
BUTTON_MAP = json.loads((ROOT / "speedup_button_map.json").read_text(encoding="utf-8"))
REGIONS = {
    "speedup_inventory_viewport": {"x": 678, "y": 376, "w": 562, "h": 418},
    "speedup_item_quantity": {"x": 755, "y": 446, "w": 42, "h": 22},
    "speedup_use_button": {"x": 1050, "y": 445, "w": 145, "h": 27},
}
FRAME_SIZE = (1920, 1080)
HOUR = 3600


@dataclass
class Frame:
    step: int
    timer: int


class FakeGame:
    def __init__(self, remaining=HOUR, inventory=None, click_effect=True, fail_checkpoint=None, clan_help=0):
        self.step = 0
        self.remaining = remaining
        self.clan_help = clan_help
        self.inventory = dict(inventory or {HOUR: 11})
        self.click_effect = click_effect
        self.fail_checkpoint = fail_checkpoint
        self.scrolls = []
        self.moves = []
        self.clicks = []
        self.quantity_read_requests = []
        self.timer_read_requests = []
        self.last_frame = None

    def capture(self):
        self.last_frame = Frame(self.step, self.remaining)
        return self.last_frame, (0, 0)

    def move(self, x, y):
        self.moves.append((x, y))

    def scroll(self, direction):
        self.scrolls.append(direction)
        self.step += 1 if direction < 0 else -1

    def click(self, point):
        self.clicks.append(point)
        if not self.click_effect:
            return
        checkpoint = next(item for item in BUTTON_MAP["checkpoints"] if item["scroll_count"] == self.step)
        button = next(
            item for item in checkpoint["buttons"]
            if (REGIONS["speedup_inventory_viewport"]["x"] + item["center"]["x"],
                REGIONS["speedup_inventory_viewport"]["y"] + item["center"]["y"]) == point
        )
        duration = button["duration_seconds"]
        self.inventory[duration] = self.inventory.get(duration, 0) - 1
        self.remaining = max(0, self.remaining - duration)
        if len(self.clicks) == 1:
            self.remaining = max(0, self.remaining - self.clan_help)

    def read_checkpoint(self, _, checkpoint, *_args, **kwargs):
        diagnostics = tuple({
            "duration_label": button["duration_label"],
            "expected_rectangle": button["rectangle"],
            "detected_rectangle": {
                "x": button["rectangle"]["x"], "y": button["rectangle"]["y"],
                "width": button["rectangle"]["width"], "height": button["rectangle"]["height"],
            },
            "offset": {"x": 0, "y": 0}, "confidence": 1.0,
        } for button in checkpoint["buttons"])
        if kwargs.get("verify_only"):
            return CheckpointInventoryReading(
                "complete", (), checkpoint_steps=(checkpoint["scroll_count"],),
                match_diagnostics=diagnostics,
            )
        if checkpoint["scroll_count"] == self.fail_checkpoint:
            return CheckpointInventoryReading(
                "incomplete", (), "fixture_unreadable",
                match_diagnostics=({"detected_rectangle": {"x": 384, "y": 62}},),
            )
        target_duration = kwargs.get("duration_seconds")
        self.quantity_read_requests.append((checkpoint["scroll_count"], target_duration))
        items = []
        for button in checkpoint["buttons"]:
            duration = button["duration_seconds"]
            if target_duration is not None and duration != target_duration:
                continue
            quantity = self.inventory.get(duration, 0)
            items.append(InventoryItemReading(
                button["duration_label"], duration,
                ParsedReading(str(quantity), quantity, 100.0, "ok"),
                checkpoint["scroll_count"], button["rectangle"], button["center"],
            ))
        return CheckpointInventoryReading(
            "complete", tuple(items), checkpoint_steps=(checkpoint["scroll_count"],),
            match_diagnostics=diagnostics,
        )

    def run(self, dry_run=True, stop_fn=lambda: None, timer_reader_fn=None, anchor_fn=None):
        return run_checkpoint_speedups(
            self.capture,
            self.move,
            self.scroll,
            self.click,
            BUTTON_MAP,
            None,
            regions=REGIONS,
            stop_fn=stop_fn,
            sleep_fn=lambda _: None,
            dry_run=dry_run,
            anchor_fn=anchor_fn or (lambda _: True),
            timer_reader_fn=lambda frame: self._read_timer(
                frame, timer_reader_fn or (
                    lambda current: ParsedReading(str(current.timer), current.timer, 100.0, "ok")
                ),
            ),
            inventory_reader_fn=self.read_checkpoint,
            frame_size_fn=lambda _: FRAME_SIZE,
            viewport_crop_fn=lambda frame, _: frame,
            viewport_change_fn=lambda before, after: float(before.step != after.step),
            expected_frame_size=FRAME_SIZE,
        )

    def _read_timer(self, frame, reader):
        self.timer_read_requests.append(frame.step)
        return reader(frame)

def test_dry_run_scans_exact_checkpoints_and_never_clicks():
    game = FakeGame(inventory={HOUR: 11})

    result = game.run(dry_run=True)

    assert result.status == PLANNED
    assert result.checkpoint_steps == (3, 11, 16)
    assert result.plan.uses == ((HOUR, 1),)
    assert len(game.scrolls) == 16
    assert len(game.moves) == 16
    assert game.clicks == []
    events = [entry["event"] for entry in result.event_trace]
    assert events.count("scroll") == 16
    assert events.count("viewport_check") == 16
    assert events.count("checkpoint_read") == 3
    assert "plan_built" in events
    assert "planning_started" in events
    assert [event["data"]["selected_duration_seconds"] for event in result.event_trace if event["event"] == "plan_choice"] == [HOUR]
    assert events[-1] == "run_finished"
    assert result.event_trace[-1]["data"]["reason"] == "dry_run"


def test_failed_anchor_capture_records_match_diagnostics():
    game = FakeGame()
    match = {
        "recognized": False,
        "score": 0.891,
        "threshold": 0.95,
        "location": {"x": 900, "y": 251},
        "partial_score": 0.90,
        "partial_location": {"x": 900, "y": 251},
        "fallback_used": False,
    }

    result = game.run(anchor_fn=lambda _: match)

    assert result.status == BLOCKED
    capture = next(event for event in result.event_trace if event["event"] == "capture")
    assert capture["data"]["dialog_recognized"] is False
    assert capture["data"]["dialog_match"] == match


def test_execution_uses_the_single_initial_plan_after_timer_changes():
    inventory = {duration: 100 for duration in (
        900, HOUR, 3 * HOUR, 8 * HOUR, 15 * HOUR, 86400,
        3 * 86400, 7 * 86400, 30 * 86400,
    )}
    game = FakeGame(remaining=2 * 86400, inventory=inventory, clan_help=35 * HOUR)

    result = game.run(dry_run=False)

    assert result.status == FINISHED
    assert result.replan is None
    assert len(game.clicks) == 6
    assert len([event for event in result.event_trace if event["event"] == "plan_built"]) == 1


def test_live_run_uses_initial_quantity_and_reads_timer_only_after_the_plan():
    game = FakeGame(inventory={HOUR: 11})

    result = game.run(dry_run=False)

    assert result.status == FINISHED
    assert result.reason == "timer_reached_zero"
    assert result.used == ((HOUR, 1),)
    assert game.clicks == [(1122, 529)]
    assert game.inventory[HOUR] == 10
    click_event = next(event for event in result.event_trace if event["event"] == "use_click")
    assert click_event["data"] == {
        "status": "sent", "duration_seconds": HOUR, "screen_point": (1122, 529),
        "use_number": 1, "plan_generation": 1, "plan_step": 1, "plan_total": 1,
    }
    verification = next(event for event in result.event_trace if event["event"] == "use_verification")
    assert verification["data"]["quantity_checked"] is False
    assert verification["data"]["status"] == "deferred_to_final_timer"
    assert [request for request in game.quantity_read_requests if request[1] is not None] == []
    assert len(game.timer_read_requests) == 3  # initial, post-scan, final; never after each click
    timing = result.click_timings[0]
    assert timing["duration_seconds"] == HOUR
    assert timing["checkpoint"] == 3
    assert all(timing[key] >= 0 for key in (
        "navigation_ms", "button_match_ms", "click_settle_capture_ms",
    ))


def test_repeated_same_item_uses_are_indexed_and_explain_each_choice():
    game = FakeGame(remaining=3 * HOUR, inventory={HOUR: 13})

    result = game.run(dry_run=False)

    assert result.status == FINISHED
    use_steps = [event for event in result.event_trace if event["event"] == "use_step_started"]
    assert [
        (event["data"]["use_number"], event["data"]["plan_step"], event["data"]["duration_label"])
        for event in use_steps
    ] == [(1, 1, "1h"), (2, 2, "1h"), (3, 3, "1h")]
    assert all(event["data"]["decision"]["strategy"] == "preferred_fit" for event in use_steps)
    confirmed = [event for event in result.event_trace if event["event"] == "use_verification"]
    assert len(confirmed) == 3
    assert all(event["data"]["quantity_checked"] is False for event in confirmed)
    assert all(request[1] is None for request in game.quantity_read_requests)
    assert len(game.timer_read_requests) == 3


def test_executor_calls_planner_once_and_never_replans(monkeypatch):
    inventory = {duration: 100 for duration in (900, HOUR, 3 * HOUR, 8 * HOUR, 15 * HOUR,
                                                  86400, 3 * 86400, 7 * 86400, 30 * 86400)}
    game = FakeGame(remaining=2 * 86400, inventory=inventory, clan_help=35 * HOUR)
    plans = []
    real = __import__("speedup_checkpoint_runner").plan_speedups
    monkeypatch.setattr(
        "speedup_checkpoint_runner.plan_speedups",
        lambda *args: plans.append(args[0]) or real(*args),
    )

    result = game.run(dry_run=False)

    assert result.status == FINISHED
    assert result.replan is None
    assert plans == [2 * 86400]


def test_insufficient_inventory_does_not_click():
    game = FakeGame(remaining=100 * 86400, inventory={HOUR: 11})

    result = game.run(dry_run=False)

    assert result.status == NOT_ENOUGH
    assert result.shortfall_seconds == 100 * 86400 - 11 * HOUR
    assert game.clicks == []


def test_residual_minutes_replan_without_rescanning_inventory():
    game = FakeGame(remaining=HOUR + 2488, inventory={HOUR: 12, 900: 12})
    timer_clicks = []

    def read_timer(frame):
        timer_clicks.append(len(game.clicks))
        value = HOUR if not game.clicks else frame.timer
        return ParsedReading(str(value), value, 100.0, "ok")

    result = game.run(dry_run=False, timer_reader_fn=read_timer)

    assert result.status == FINISHED
    assert game.remaining == 0
    assert result.final_remaining_seconds == 0
    assert result.replan is not None
    assert len(game.quantity_read_requests) == 3
    assert all(duration is None for _, duration in game.quantity_read_requests)
    assert timer_clicks == [0, 0, 1, 4]
    assert timer_clicks[-1] == len(game.clicks)
    residual_plan = next(event for event in result.event_trace if event["event"] == "plan_rebuilt")
    assert residual_plan["data"]["remaining_seconds"] == 2488
    assert dict(residual_plan["data"]["inventory"])[HOUR] == 11
    assert residual_plan["data"]["stock_source"] == "initial_inventory_minus_submitted_clicks"
    assert "residual_scan_started" not in [event["event"] for event in result.event_trace]
    assert any(item["plan_generation"] == 2 for item in result.click_timings)


def test_residual_shortfall_does_not_submit_more_clicks():
    game = FakeGame(remaining=HOUR + 600, inventory={HOUR: 1})
    result = game.run(
        dry_run=False,
        timer_reader_fn=lambda frame: ParsedReading(
            "timer", HOUR if not game.clicks else frame.timer, 100.0, "ok",
        ),
    )

    assert result.status == NOT_ENOUGH
    assert result.shortfall_seconds == 600
    assert len(game.clicks) == 1


def test_further_residual_batches_require_new_progress_without_inventory_rescans():
    game = FakeGame(remaining=HOUR + 2488, inventory={HOUR: 11, 900: 20})

    def read_timer(frame):
        if not game.clicks:
            value = HOUR
        elif len(game.clicks) == 1:
            value = 1000
        else:
            value = frame.timer
        return ParsedReading(str(value), value, 100.0, "ok")

    result = game.run(dry_run=False, timer_reader_fn=read_timer)

    assert result.status == FINISHED
    assert game.remaining == 0
    assert len(game.quantity_read_requests) == 3
    generations = [event["data"]["plan_generation"] for event in result.event_trace if event["event"] == "plan_rebuilt"]
    assert generations == [2, 3]


def test_residual_replan_does_not_depend_on_another_inventory_read():
    game = FakeGame(remaining=HOUR + 600, inventory={HOUR: 12})
    original_click = game.click

    def click_then_break_checkpoint(point):
        original_click(point)
        game.fail_checkpoint = 3

    game.click = click_then_break_checkpoint
    result = game.run(
        dry_run=False,
        timer_reader_fn=lambda frame: ParsedReading(
            "timer", HOUR if not game.clicks else frame.timer, 100.0, "ok",
        ),
    )

    assert result.status == FINISHED
    assert len(game.clicks) > 1
    assert len(game.quantity_read_requests) == 3


def test_timer_progress_replans_from_conservative_submitted_use_estimate():
    game = FakeGame(remaining=HOUR, inventory={HOUR: 12})

    def click_without_spending(point):
        game.clicks.append(point)
        game.remaining = 600

    game.click = click_without_spending
    result = game.run(dry_run=False)

    assert result.status == UNCERTAIN
    assert result.reason == "timer_not_decreased_after_batch"
    assert len(game.clicks) == 2
    assert len(game.quantity_read_requests) == 3


def test_unreadable_final_timer_without_known_hidden_remainder_stops_after_retries():
    game = FakeGame(inventory={HOUR: 12})
    result = game.run(
        dry_run=False,
        timer_reader_fn=lambda frame: ParsedReading(
            "?" if game.clicks else "3600", None if game.clicks else HOUR,
            None if game.clicks else 100.0, "unreadable" if game.clicks else "ok",
        ),
    )

    assert result.status == UNCERTAIN
    assert result.reason.startswith("timer_unreadable")
    assert len(game.clicks) == 1
    assert result.replan is None
    final_reads = [e for e in result.event_trace if e["event"] == "timer_read" and e["data"].get("phase") == "final"]
    assert len(final_reads) == 6


def test_transiently_unreadable_final_timer_is_retried_with_fresh_captures():
    game = FakeGame(inventory={HOUR: 12})
    reads_after_click = []

    def read_timer(frame):
        if not game.clicks:
            return ParsedReading("3600", HOUR, 100.0, "ok")
        reads_after_click.append(frame.timer)
        if len(reads_after_click) == 1:
            return ParsedReading("?", None, None, "minute_ocr_disagreement")
        return ParsedReading("0", frame.timer, 100.0, "ok")

    result = game.run(dry_run=False, timer_reader_fn=read_timer)

    assert result.status == FINISHED
    assert result.reason == "timer_reached_zero"
    assert len(game.clicks) == 1
    assert len(reads_after_click) == 2


def test_stale_final_timer_is_reread_instead_of_aborting():
    game = FakeGame(inventory={HOUR: 12})
    reads_after_click = []

    def read_timer(frame):
        if not game.clicks:
            return ParsedReading("3600", HOUR, 100.0, "ok")
        reads_after_click.append(frame.timer)
        value = HOUR if len(reads_after_click) == 1 else frame.timer
        return ParsedReading(str(value), value, 100.0, "ok")

    result = game.run(dry_run=False, timer_reader_fn=read_timer)

    assert result.status == FINISHED
    assert len(game.clicks) == 1
    assert len(reads_after_click) == 2


def _hidden_remainder_game():
    # The dialog shows "3g." while 30 more minutes are hidden below the displayed unit.
    game = FakeGame(remaining=3 * HOUR + 1800, inventory={HOUR: 12, 3 * HOUR: 12})

    def read_timer(frame):
        if not game.clicks:
            return ParsedReading("3g.", 3 * HOUR, 100.0, "ok")
        return ParsedReading("?", None, None, "minute_ocr_disagreement")

    return game, read_timer


def test_unreadable_final_timer_covers_the_hidden_remainder_once():
    game, read_timer = _hidden_remainder_game()

    result = game.run(dry_run=False, timer_reader_fn=read_timer, anchor_fn=lambda _: len(game.clicks) < 2)

    assert result.status == FINISHED
    assert result.reason == "dialog_closed_after_last_use"
    assert len(game.clicks) == 2
    assert game.remaining == 0
    rebuilt = next(e for e in result.event_trace if e["event"] == "plan_rebuilt")
    assert rebuilt["data"]["reason"] == "unreadable_final_timer_cover_hidden_remainder"
    assert rebuilt["data"]["remaining_seconds"] == HOUR


def test_hidden_remainder_cover_is_not_repeated_when_still_unreadable():
    game, read_timer = _hidden_remainder_game()

    result = game.run(dry_run=False, timer_reader_fn=read_timer)

    assert result.status == UNCERTAIN
    assert result.reason.startswith("timer_unreadable")
    assert len(game.clicks) == 2


def test_dialog_closing_during_final_timer_retries_finishes_the_run():
    game = FakeGame(inventory={HOUR: 12})

    def read_timer(frame):
        if not game.clicks:
            return ParsedReading("3600", HOUR, 100.0, "ok")
        return ParsedReading("?", None, None, "minute_ocr_disagreement")

    calls = []

    def anchor(_frame):
        if not game.clicks:
            return True
        calls.append(1)
        return len(calls) < 3

    result = game.run(dry_run=False, timer_reader_fn=read_timer, anchor_fn=anchor)

    assert result.status == FINISHED
    assert result.reason == "dialog_closed_before_final_timer"
    assert len(game.clicks) == 1


def test_unreadable_checkpoint_blocks_before_any_click():
    game = FakeGame(inventory={HOUR: 11}, fail_checkpoint=11)

    result = game.run(dry_run=False)

    assert result.status == BLOCKED
    assert "inventory_incomplete:11" in result.reason
    failed_diagnostic = next(item for item in result.checkpoint_diagnostics if item["scroll_count"] == 11)
    assert failed_diagnostic["matches"][0]["detected_rectangle"] == {"x": 384, "y": 62}
    assert result.event_trace[-2]["event"] == "run_aborted"
    assert result.event_trace[-2]["data"]["reason"] == result.reason
    checkpoint_event = next(
        event for event in result.event_trace
        if event["event"] == "checkpoint_read" and event["step"] == 11
    )
    assert checkpoint_event["data"]["reason"] == "fixture_unreadable"
    assert game.clicks == []


def test_uncertain_click_is_not_retried():
    game = FakeGame(inventory={HOUR: 11}, click_effect=False)

    result = game.run(dry_run=False)

    assert result.status == UNCERTAIN
    assert result.reason == "timer_not_decreased_after_batch"
    assert len(game.clicks) == 1


def test_emergency_stop_before_first_click_prevents_input():
    game = FakeGame(inventory={HOUR: 11})
    checks = 0

    def stop_after_scan():
        nonlocal checks
        checks += 1
        if checks == 33:
            raise RuntimeError("operator stop")

    result = game.run(dry_run=False, stop_fn=stop_after_scan)

    assert result.status == BLOCKED
    assert result.reason.startswith("emergency_stop")
    assert game.clicks == []


def test_emergency_stop_after_a_use_is_uncertain_and_does_not_continue():
    game = FakeGame(remaining=4 * HOUR, inventory={HOUR: 11, 3 * HOUR: 11})

    def stop_after_first_click():
        if game.clicks:
            raise RuntimeError("operator stop")

    result = game.run(dry_run=False, stop_fn=stop_after_first_click)

    assert result.status == UNCERTAIN
    assert len(game.clicks) == 1
    assert dict(result.used) == {3 * HOUR: 1}