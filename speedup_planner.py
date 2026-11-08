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
    decisions: tuple = ()


def _is_count(value):
    return type(value) is int and value >= 0


def _floor(duration):
    return LARGE_ITEM_FLOOR if duration in LARGE_ITEM_DURATIONS else DEFAULT_FLOOR


def _preferred(remaining):
    for upper, durations in PREFERRED_BY_REMAINING:
        if upper is None or remaining <= upper:
            return durations


def _pick_with_decision(stock, remaining):
    preferred = _preferred(remaining)
    above = [d for d, count in stock.items() if count > _floor(d)]
    steps = (
        ("preferred_fit", max, [d for d in above if d in preferred and d <= remaining]),
        ("any_fit", max, [d for d in above if d <= remaining]),
        ("preferred_overshoot", min, [d for d in above if d in preferred and d > remaining]),
        ("any_overshoot", min, [d for d in above if d > remaining]),
    )
    context = {
        "remaining_before_seconds": remaining,
        "preferred_durations_seconds": tuple(preferred),
        "stock_before": tuple(sorted(stock.items())),
        "available_above_floors_seconds": tuple(sorted(above)),
    }
    for strategy, choose, candidates in steps:
        if candidates:
            duration = choose(candidates)
            return duration, {
                **context,
                "strategy": strategy,
                "candidates_seconds": tuple(sorted(candidates)),
                "selected_duration_seconds": duration,
                "floor_seconds": _floor(duration),
                "breaks_floor": False,
            }
    fitting = [d for d in stock if d <= remaining]
    candidates = fitting or list(stock)
    duration = max(fitting) if fitting else min(stock)
    return duration, {
        **context,
        "strategy": "floor_breaking_fit" if fitting else "floor_breaking_overshoot",
        "candidates_seconds": tuple(sorted(candidates)),
        "selected_duration_seconds": duration,
        "floor_seconds": _floor(duration),
        "breaks_floor": stock[duration] <= _floor(duration),
    }


def _pick(stock, remaining):
    return _pick_with_decision(stock, remaining)[0]


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
    decisions = []
    remaining = remaining_seconds
    while remaining > 0:
        duration, decision = _pick_with_decision(stock, remaining)
        decision["step"] = len(decisions) + 1
        decision["quantity_before"] = stock[duration]
        used[duration] = used.get(duration, 0) + 1
        stock[duration] -= 1
        if stock[duration] == 0:
            del stock[duration]
        remaining -= duration
        decision["quantity_after"] = stock.get(duration, 0)
        decision["remaining_after_seconds"] = remaining
        decision["floor_breached_after_selection"] = stock.get(duration, 0) < _floor(duration)
        decisions.append(decision)

    breached = tuple(sorted(d for d in used if stock.get(d, 0) < _floor(d)))
    return SpeedupPlan(STATUS_OK, tuple(used.items()), breached, 0, tuple(decisions))
