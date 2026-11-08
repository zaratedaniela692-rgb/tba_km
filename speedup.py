"""Finish the active task from an open speedup dialog by using owned items.

Independent of the task queue and task type; the caller decides when to call it and confirms
completion on its own screen. Screen access is injected, so the module never touches the game
by itself. Dry-run scrolls the list (to read the full inventory) but never clicks Use.
"""

import time
from dataclasses import dataclass

from speedup_planner import STATUS_NOTHING_TO_DO, STATUS_SHORTFALL, plan_speedups
from speedup_readings import SECONDS_PER_DAY

FINISHED = "FINISHED"
NOT_ENOUGH = "NOT_ENOUGH"
UNCERTAIN = "UNCERTAIN"
BLOCKED = "BLOCKED"
PLANNED = "PLANNED"

MAX_SCROLLS = 12
SETTLE_SECONDS = 0.3
REPLAN_BELOW_FRACTION = 0.2
REPLAN_MIN_INITIAL_SECONDS = 3 * SECONDS_PER_DAY


@dataclass(frozen=True)
class InventoryRow:
    duration: int  # seconds
    quantity: int
    click_point: tuple  # Use button centre in frame coordinates


@dataclass(frozen=True)
class DialogReading:
    timer: object  # speedup_readings.ParsedReading
    rows: tuple  # InventoryRow, owned items only
    rows_complete: bool
    signature: object  # hashable list position; must not depend on quantities or the timer


@dataclass(frozen=True)
class SpeedupResult:
    status: str
    reason: str
    plan: object = None
    used: tuple = ()  # ((duration, count), ...) confirmed uses
    shortfall_seconds: int = 0
    replan: object = None  # plan rebuilt once when the timer fell below the threshold


class _Abort(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _expand(plan):
    """One entry per click, in plan order."""
    return [duration for duration, count in plan.uses for _ in range(count)]


class _Run:
    def __init__(self, capture_fn, read_dialog_fn, click_fn, scroll_fn, stop_fn, sleep_fn, max_scrolls):
        self.capture_fn = capture_fn
        self.read_dialog_fn = read_dialog_fn
        self.click_fn = click_fn
        self.scroll_fn = scroll_fn
        self.stop_fn = stop_fn
        self.sleep_fn = sleep_fn
        self.max_scrolls = max_scrolls
        self.used = {}
        self.clicks_issued = 0

    def abort(self, reason):
        # After a click the screen is no longer known to be unchanged.
        return _Abort(UNCERTAIN if self.clicks_issued else BLOCKED, reason)

    def check_stop(self):
        try:
            self.stop_fn()
        except Exception as error:
            raise self.abort(f"emergency_stop:{error}") from error

    def read(self):
        dialog = self.read_dialog_fn(self.capture_fn())
        if dialog is None:
            raise self.abort("dialog_not_recognized")
        if dialog.timer.value is None:
            raise self.abort(f"timer_unreadable:{dialog.timer.status}")
        if not dialog.rows_complete:
            raise self.abort("inventory_row_unreadable")
        return dialog

    def scroll(self, direction):
        self.check_stop()
        try:
            self.scroll_fn(direction)
        except Exception as error:
            raise self.abort(f"scroll_failed:{error}") from error
        self.sleep_fn(SETTLE_SECONDS)

    def go_to_top(self):
        dialog = self.read()
        for _ in range(self.max_scrolls):
            self.scroll(-1)
            following = self.read()
            if following.signature == dialog.signature:
                return following
            dialog = following
        raise self.abort("scan_incomplete")

    def scan(self, dialog):
        """Walk down the list once; returns (inventory, first view index per duration, views, last dialog)."""
        views, inventory, seen = [], {}, {}
        for _ in range(self.max_scrolls + 1):
            views.append(dialog.signature)
            for row in dialog.rows:
                if inventory.setdefault(row.duration, row.quantity) != row.quantity:
                    raise self.abort("inventory_conflict_between_views")
                seen.setdefault(row.duration, len(views) - 1)
            self.scroll(1)
            following = self.read()
            if following.signature == dialog.signature:
                return inventory, seen, views, following
            if following.signature in views:
                raise self.abort("list_position_ambiguous")
            dialog = following
        raise self.abort("scan_incomplete")

    def bring_into_view(self, duration, seen, views):
        for _ in range(self.max_scrolls + 1):
            dialog = self.read()
            row = next((item for item in dialog.rows if item.duration == duration), None)
            if row is not None:
                return row
            if dialog.signature not in views:
                raise _Abort(UNCERTAIN, "list_changed")
            current = views.index(dialog.signature)
            if current == seen[duration]:
                raise _Abort(UNCERTAIN, "row_missing")
            self.scroll(1 if seen[duration] > current else -1)
        raise _Abort(UNCERTAIN, "row_not_found")

    def use_once(self, duration, seen, views, last_use):
        """One verified use; returns the dialog after it, or None when the dialog closed on the last use."""
        row = self.bring_into_view(duration, seen, views)
        self.check_stop()
        self.clicks_issued += 1
        try:
            self.click_fn(row.click_point)
        except Exception as error:
            raise _Abort(UNCERTAIN, f"click_failed:{error}") from error
        self.sleep_fn(SETTLE_SECONDS)
        after = self.read_dialog_fn(self.capture_fn())
        if after is None:
            if last_use:
                self.used[duration] = self.used.get(duration, 0) + 1
                return None
            raise _Abort(UNCERTAIN, "dialog_closed_before_plan_end")
        if not after.rows_complete:
            raise _Abort(UNCERTAIN, "inventory_row_unreadable_after_use")
        remaining_row = next((item for item in after.rows if item.duration == duration), None)
        expected = row.quantity - 1
        if remaining_row is None and expected != 0 or remaining_row is not None and remaining_row.quantity != expected:
            raise _Abort(UNCERTAIN, "use_not_confirmed")
        self.used[duration] = self.used.get(duration, 0) + 1
        return after

    def execute(self, dry_run):
        dialog = self.go_to_top()
        inventory, seen, views, dialog = self.scan(dialog)
        initial = dialog.timer.value
        plan = plan_speedups(initial, inventory)
        if plan.status == STATUS_NOTHING_TO_DO:
            return SpeedupResult(FINISHED, "already_finished", plan)
        if plan.status == STATUS_SHORTFALL:
            return SpeedupResult(NOT_ENOUGH, "owned_items_do_not_cover_remaining_time", plan, (), plan.shortfall_seconds)
        if dry_run:
            return SpeedupResult(PLANNED, "dry_run", plan)

        stock = dict(inventory)
        queue = _expand(plan)
        replan = None
        after = dialog
        while queue:
            duration = queue.pop(0)
            after = self.use_once(duration, seen, views, last_use=not queue)
            stock[duration] -= 1
            if after is None or after.timer.value == 0:
                return SpeedupResult(FINISHED, "task_finished", plan, tuple(self.used.items()), replan=replan)
            timer = after.timer.value
            if (
                replan is None
                and initial >= REPLAN_MIN_INITIAL_SECONDS
                and timer is not None
                and timer < initial * REPLAN_BELOW_FRACTION
            ):
                replan = plan_speedups(timer, stock)
                if replan.status == STATUS_SHORTFALL:
                    return SpeedupResult(
                        NOT_ENOUGH, "owned_items_do_not_cover_remaining_time_after_replan", plan,
                        tuple(self.used.items()), replan.shortfall_seconds, replan,
                    )
                queue = _expand(replan)
        raise _Abort(UNCERTAIN, "timer_not_zero_after_plan")


def finish_with_speedups(
    capture_fn, read_dialog_fn, click_fn, scroll_fn, stop_fn=lambda: None,
    sleep_fn=time.sleep, dry_run=True, max_scrolls=MAX_SCROLLS,
):
    """Use owned speedups until the open dialog's task is done; `scroll_fn(+1)` scrolls down, `-1` up."""
    run = _Run(capture_fn, read_dialog_fn, click_fn, scroll_fn, stop_fn, sleep_fn, max_scrolls)
    try:
        return run.execute(dry_run)
    except _Abort as stop:
        return SpeedupResult(stop.status, stop.reason, used=tuple(run.used.items()))


def main(argv=None):
    """Run the supervised desktop checkpoint scanner and optional item-use flow."""
    from speedup_run import main as run_main

    return run_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
