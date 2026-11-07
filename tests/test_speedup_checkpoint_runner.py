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
    def __init__(self, remaining=HOUR, inventory=None, click_effect=True, fail_checkpoint=None):
        self.step = 0
        self.remaining = remaining
        self.inventory = dict(inventory or {HOUR: 11})
        self.click_effect = click_effect
        self.fail_checkpoint = fail_checkpoint
        self.scrolls = []
        self.moves = []
        self.clicks = []
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

    def read_checkpoint(self, _, checkpoint, *_args, **_kwargs):
        if checkpoint["scroll_count"] == self.fail_checkpoint:
            return CheckpointInventoryReading("incomplete", (), "fixture_unreadable")
        items = []
        for button in checkpoint["buttons"]:
            duration = button["duration_seconds"]
            quantity = self.inventory.get(duration, 0)
            items.append(InventoryItemReading(
                button["duration_label"], duration,
                ParsedReading(str(quantity), quantity, 100.0, "ok"),
                checkpoint["scroll_count"], button["rectangle"], button["center"],
            ))
        return CheckpointInventoryReading("complete", tuple(items), checkpoint_steps=(checkpoint["scroll_count"],))

    def run(self, dry_run=True, stop_fn=lambda: None):
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
            anchor_fn=lambda _: True,
            timer_reader_fn=lambda frame: ParsedReading(str(frame.timer), frame.timer, 100.0, "ok"),
            inventory_reader_fn=self.read_checkpoint,
            frame_size_fn=lambda _: FRAME_SIZE,
            viewport_crop_fn=lambda frame, _: frame,
            viewport_change_fn=lambda before, after: float(before.step != after.step),
            expected_frame_size=FRAME_SIZE,
        )


def test_dry_run_scans_exact_checkpoints_and_never_clicks():
    game = FakeGame(inventory={HOUR: 11})

    result = game.run(dry_run=True)

    assert result.status == PLANNED
    assert result.checkpoint_steps == (3, 11, 16)
    assert result.plan.uses == ((HOUR, 1),)
    assert len(game.scrolls) == 16
    assert len(game.moves) == 16
    assert game.clicks == []


def test_live_run_clicks_once_and_requires_the_quantity_to_drop():
    game = FakeGame(inventory={HOUR: 11})

    result = game.run(dry_run=False)

    assert result.status == FINISHED
    assert result.reason == "timer_reached_zero"
    assert result.used == ((HOUR, 1),)
    assert game.clicks == [(1122, 529)]
    assert game.inventory[HOUR] == 10


def test_insufficient_inventory_does_not_click():
    game = FakeGame(remaining=100 * 86400, inventory={HOUR: 11})

    result = game.run(dry_run=False)

    assert result.status == NOT_ENOUGH
    assert result.shortfall_seconds == 100 * 86400 - 11 * HOUR
    assert game.clicks == []


def test_unreadable_checkpoint_blocks_before_any_click():
    game = FakeGame(inventory={HOUR: 11}, fail_checkpoint=11)

    result = game.run(dry_run=False)

    assert result.status == BLOCKED
    assert "inventory_incomplete:11" in result.reason
    assert game.clicks == []


def test_uncertain_click_is_not_retried():
    game = FakeGame(inventory={HOUR: 11}, click_effect=False)

    result = game.run(dry_run=False)

    assert result.status == UNCERTAIN
    assert result.reason == "use_not_confirmed"
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