"""Pure planner: which owned speedup items to use to finish a task."""

from dataclasses import dataclass

HOUR = 3600
DAY = 24 * HOUR

# (upper bound of remaining time in seconds, preferred item durations); None = no bound.
PREFERRED_BY_REMAINING = (
    (5 * DAY, (HOUR, 3 * HOUR, 8 * HOUR)),
    (15 * DAY, (8 * HOUR, 15 * HOUR)),
    (100 * DAY, (15 * HOUR, DAY, 3 * DAY)),
    (None, (3 * DAY, 7 * DAY, 30 * DAY)),
)
LARGE_ITEM_DURATIONS = (3 * DAY, 7 * DAY, 30 * DAY)
LARGE_ITEM_FLOOR = 3
DEFAULT_FLOOR = 10

STATUS_OK = "ok"
STATUS_NOTHING_TO_DO = "nothing_to_do"
STATUS_SHORTFALL = "shortfall"


class SpeedupPlanError(ValueError):
    """Invalid remaining time or inventory."""


@dataclass(frozen=True)
class SpeedupPlan:
    status: str
    uses: tuple  # ((duration_seconds, count), ...) in order of first use
    breached_floors: tuple  # durations used that end below their floor
    shortfall_seconds: int


def _is_count(value):
    return type(value) is int and value >= 0


def _floor(duration):
    return LARGE_ITEM_FLOOR if duration in LARGE_ITEM_DURATIONS else DEFAULT_FLOOR


def _preferred(remaining):
    for upper, durations in PREFERRED_BY_REMAINING:
        if upper is None or remaining <= upper:
            return durations


def _pick(stock, remaining):
    preferred = _preferred(remaining)
    above = [d for d, count in stock.items() if count > _floor(d)]
    steps = (
        (max, [d for d in above if d in preferred and d <= remaining]),
        (max, [d for d in above if d <= remaining]),
        (min, [d for d in above if d in preferred and d > remaining]),
        (min, [d for d in above if d > remaining]),
    )
    for choose, candidates in steps:
        if candidates:
            return choose(candidates)
    # Only floor-breaking items are left.
    fitting = [d for d in stock if d <= remaining]
    return max(fitting) if fitting else min(stock)


def plan_speedups(remaining_seconds, inventory):
    """Choose items to cover `remaining_seconds` from `inventory` (duration seconds -> quantity)."""
    if not _is_count(remaining_seconds):
        raise SpeedupPlanError("remaining_seconds must be a non-negative integer.")
    if not isinstance(inventory, dict):
        raise SpeedupPlanError("inventory must be a dict of duration seconds to quantity.")
    for duration, count in inventory.items():
        if type(duration) is not int or duration <= 0 or not _is_count(count):
            raise SpeedupPlanError("inventory needs positive integer durations and non-negative integer quantities.")

    stock = {d: count for d, count in inventory.items() if count > 0}
    if remaining_seconds == 0:
        return SpeedupPlan(STATUS_NOTHING_TO_DO, (), (), 0)
    owned_seconds = sum(d * count for d, count in stock.items())
    if owned_seconds < remaining_seconds:
        return SpeedupPlan(STATUS_SHORTFALL, (), (), remaining_seconds - owned_seconds)

    used = {}
    remaining = remaining_seconds
    while remaining > 0:
        duration = _pick(stock, remaining)
        used[duration] = used.get(duration, 0) + 1
        stock[duration] -= 1
        if stock[duration] == 0:
            del stock[duration]
        remaining -= duration

    breached = tuple(sorted(d for d in used if stock.get(d, 0) < _floor(d)))
    return SpeedupPlan(STATUS_OK, tuple(used.items()), breached, 0)
