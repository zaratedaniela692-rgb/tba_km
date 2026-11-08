import pytest

import speedup
from speedup import (
    BLOCKED,
    FINISHED,
    NOT_ENOUGH,
    PLANNED,
    UNCERTAIN,
    DialogReading,
    InventoryRow,
    finish_with_speedups,
)
from speedup_readings import ParsedReading

H, D = 3600, 86400


class FakeGame:
    """A scrollable speedup dialog: ascending item list, three visible rows, timer in seconds."""

    def __init__(self, remaining, inventory, view=3, close_on_finish=True, use_has_effect=True, clan_help=0):
        self.remaining = remaining
        self.clan_help = clan_help  # seconds taken off the timer right after the first use
        self.items = sorted(inventory.items())
        self.view = view
        self.top = 0
        self.closed = False
        self.close_on_finish = close_on_finish
        self.use_has_effect = use_has_effect
        self.timer_status = "ok"
        self.complete = True
        self.clicks = []
        self.scrolls = []

    def capture(self):
        timer = self.remaining if self.timer_status == "ok" else None
        return self.closed, self.top, tuple(self.items), timer, self.timer_status, self.complete

    def read(self, frame):
        closed, top, items, timer, status, complete = frame
        if closed:
            return None
        rows = tuple(InventoryRow(d, q, (d, top)) for d, q in items[top:top + self.view])
        return DialogReading(ParsedReading("", timer, 100.0, status), rows, complete, top)

    def scroll(self, direction):
        self.scrolls.append(direction)
        self.top = max(0, min(self.top + direction, max(0, len(self.items) - self.view)))

    def click(self, point):
        self.clicks.append(point)
        if not self.use_has_effect:
            return
        index = next(i for i, (d, _) in enumerate(self.items) if d == point[0])
        duration, quantity = self.items[index]
        self.items[index] = (duration, quantity - 1)
        if quantity == 1:
            del self.items[index]
        self.remaining = max(0, self.remaining - duration)
        if len(self.clicks) == 1:
            self.remaining = max(0, self.remaining - self.clan_help)
        self.top = max(0, min(self.top, len(self.items) - self.view))
        if self.remaining == 0 and self.close_on_finish:
            self.closed = True


def run(game, dry_run=False, stop_fn=lambda: None, **kwargs):
    return finish_with_speedups(
        game.capture, game.read, game.click, game.scroll,
        stop_fn=stop_fn, sleep_fn=lambda _: None, dry_run=dry_run, **kwargs,
    )


def stock(*durations, count=20):
    return {d: count for d in durations}


def test_dry_run_scans_the_whole_list_and_never_clicks():
    game = FakeGame(11 * H, stock(H, 3 * H, 8 * H, 15 * H, D, 3 * D))

    result = run(game, dry_run=True)

    assert result.status == PLANNED
    assert dict(result.plan.uses) == {8 * H: 1, 3 * H: 1}
    assert game.clicks == []
    assert 1 in game.scrolls


def test_live_run_uses_the_planned_items_and_finishes():
    game = FakeGame(11 * H, stock(H, 3 * H, 8 * H, 15 * H, D, 3 * D))

    result = run(game)

    assert result.status == FINISHED
    assert dict(result.used) == {8 * H: 1, 3 * H: 1}
    assert [point[0] for point in game.clicks] == [8 * H, 3 * H]
    assert game.remaining == 0


def test_item_in_an_earlier_view_is_scrolled_back_to_before_the_click():
    game = FakeGame(3 * H, stock(H, 3 * H, 8 * H, 15 * H, D, 3 * D), view=2)

    result = run(game)

    assert result.status == FINISHED
    assert game.clicks == [(3 * H, 1)]
    assert game.scrolls[-3:] == [-1, -1, -1]


def test_plan_is_rebuilt_once_when_the_timer_falls_below_twenty_percent(monkeypatch):
    game = FakeGame(100 * H, stock(H, 3 * H, 8 * H, 15 * H, D, count=100), clan_help=75 * H)
    plans = []
    real = speedup.plan_speedups
    monkeypatch.setattr(speedup, "plan_speedups", lambda *args: plans.append(args[0]) or real(*args))

    result = run(game)

    assert result.status == FINISHED
    assert plans == [100 * H, 17 * H]
    assert result.replan.uses == ((8 * H, 2), (H, 1))
    assert [point[0] for point in game.clicks] == [8 * H, 8 * H, 8 * H, H]


def test_plan_is_not_rebuilt_while_the_timer_stays_above_twenty_percent():
    game = FakeGame(11 * H, stock(H, 3 * H, 8 * H, 15 * H, D, count=100))

    result = run(game)

    assert result.status == FINISHED
    assert result.replan is None


def test_short_initial_plan_does_not_rebuild_below_twenty_percent(monkeypatch):
    game = FakeGame(
        2 * D, stock(H, 3 * H, 8 * H, 15 * H, D, count=100),
        clan_help=35 * H, close_on_finish=False,
    )
    plans = []
    real = speedup.plan_speedups
    monkeypatch.setattr(speedup, "plan_speedups", lambda *args: plans.append(args[0]) or real(*args))

    result = run(game)

    assert result.status == FINISHED
    assert plans == [2 * D]
    assert result.replan is None
    assert len(game.clicks) == 2


def test_clan_help_that_zeroes_an_open_timer_skips_the_rest_of_the_plan():
    game = FakeGame(100 * H, stock(H, 3 * H, 8 * H, count=100), clan_help=100 * H, close_on_finish=False)

    result = run(game)

    assert result.status == FINISHED
    assert len(game.clicks) == 1


def test_dialog_closing_in_the_middle_of_the_plan_is_left_to_the_caller_to_confirm():
    game = FakeGame(100 * H, stock(H, 3 * H, 8 * H, count=100), clan_help=100 * H)

    result = run(game)

    assert result.status == UNCERTAIN
    assert result.reason == "dialog_closed_before_plan_end"
    assert len(game.clicks) == 1


def test_unreadable_timer_after_a_use_does_not_trigger_a_rebuild(monkeypatch):
    game = FakeGame(100 * H, stock(H, 3 * H, 8 * H, count=100), clan_help=75 * H)
    original_click = game.click

    def click_then_blur_timer(point):
        original_click(point)
        game.timer_status = "low_confidence"

    game.click = click_then_blur_timer
    plans = []
    real = speedup.plan_speedups
    monkeypatch.setattr(speedup, "plan_speedups", lambda *args: plans.append(args[0]) or real(*args))

    result = finish_with_speedups(
        game.capture, game.read, game.click, game.scroll, sleep_fn=lambda _: None, dry_run=False,
    )

    assert plans == [100 * H]
    assert result.replan is None


def test_finish_is_reported_when_the_dialog_stays_open_at_zero():
    game = FakeGame(3 * H, stock(H, 3 * H, 8 * H), close_on_finish=False)

    assert run(game).status == FINISHED


def test_not_enough_items_returns_the_shortfall_without_clicking():
    game = FakeGame(10 * H, {H: 3, 3 * H: 1})

    result = run(game)

    assert result.status == NOT_ENOUGH
    assert result.shortfall_seconds == 4 * H
    assert game.clicks == []


def test_nothing_remaining_is_already_finished():
    game = FakeGame(0, stock(H))

    result = run(game)

    assert result.status == FINISHED
    assert result.reason == "already_finished"
    assert game.clicks == []


def test_use_without_effect_is_uncertain_and_not_retried():
    game = FakeGame(11 * H, stock(H, 3 * H, 8 * H), use_has_effect=False)

    result = run(game)

    assert result.status == UNCERTAIN
    assert result.reason == "use_not_confirmed"
    assert len(game.clicks) == 1


@pytest.mark.parametrize("attribute, value, reason", (("timer_status", "low_confidence", "timer_unreadable"), ("complete", False, "inventory_row_unreadable")))
def test_unreadable_screen_blocks_before_any_click(attribute, value, reason):
    game = FakeGame(11 * H, stock(H, 3 * H, 8 * H))
    setattr(game, attribute, value)

    result = run(game)

    assert result.status == BLOCKED
    assert result.reason.startswith(reason)
    assert game.clicks == []


def test_unrecognized_dialog_blocks():
    game = FakeGame(11 * H, stock(H, 3 * H, 8 * H))
    game.closed = True

    result = run(game)

    assert result.status == BLOCKED
    assert result.reason == "dialog_not_recognized"


def test_scan_that_cannot_finish_within_the_scroll_limit_blocks():
    game = FakeGame(11 * H, stock(*range(H, 40 * H, H)), view=2)

    result = run(game, max_scrolls=2)

    assert result.status == BLOCKED
    assert result.reason == "scan_incomplete"
    assert game.clicks == []


def test_emergency_stop_before_a_click_blocks_and_stops_everything():
    probe = FakeGame(11 * H, stock(H, 3 * H, 8 * H))
    run(probe, dry_run=True)
    checks_before_first_click = len(probe.scrolls)
    game = FakeGame(11 * H, stock(H, 3 * H, 8 * H))
    calls = []

    def stop():
        calls.append(True)
        if len(calls) == checks_before_first_click + 1:
            raise RuntimeError("stop file present")

    result = run(game, stop_fn=stop)

    assert result.status == BLOCKED
    assert result.reason.startswith("emergency_stop")
    assert game.clicks == []


def test_emergency_stop_between_uses_is_uncertain_and_stops_further_clicks():
    game = FakeGame(11 * H, stock(H, 3 * H, 8 * H))

    def stop():
        if game.clicks:
            raise RuntimeError("stop file present")

    result = run(game, stop_fn=stop)

    assert result.status == UNCERTAIN
    assert len(game.clicks) == 1
    assert dict(result.used) == {8 * H: 1}


def test_scroll_failure_blocks():
    game = FakeGame(11 * H, stock(H, 3 * H, 8 * H, 15 * H, D, 3 * D))

    def broken(direction):
        raise OSError("no input device")

    result = finish_with_speedups(
        game.capture, game.read, game.click, broken, sleep_fn=lambda _: None, dry_run=True,
    )

    assert result.status == BLOCKED
    assert result.reason.startswith("scroll_failed")


def test_module_has_no_queue_or_marker_dependency():
    source = open(speedup.__file__, encoding="utf-8").read()

    assert "task_controller" not in source
    assert "army_state" not in source
