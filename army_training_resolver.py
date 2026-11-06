"""Resolve a stock goal (level, match_number) to a slot of the current frame; pure, no clicks."""

from dataclasses import dataclass

from army_unit_types import DEFAULT_UNIT_TYPE, validate_unit_type

STATUS_OK = "ok"
STATUS_UNSUPPORTED = "unsupported"
STATUS_BLOCKED = "blocked"


@dataclass(frozen=True)
class SlotResolution:
    status: str
    reason: str
    frame_index: int | None = None
    candidates: tuple = ()  # frame indexes of every visible slot whose selector range contains the level


def resolve_goal_slot(level_readings, unit_type, level, match_number):
    """Resolve a matching slot only for a category with a verified slot map.

    Assumes the frame starts at the top of the list (no scroll tracking yet).
    """
    try:
        validate_unit_type(unit_type)
    except ValueError:
        return SlotResolution(STATUS_BLOCKED, "unit_type_unknown")
    if unit_type != DEFAULT_UNIT_TYPE:
        return SlotResolution(STATUS_BLOCKED, "unit_type_slot_map_unverified")
    candidates = []
    for index, reading in enumerate(level_readings):
        if reading.status != "candidate" or reading.lowest_visible_level is None:
            return SlotResolution(STATUS_BLOCKED, "slot_selector_range_uncertain")
        if reading.lowest_visible_level <= level <= reading.highest_visible_level:
            candidates.append(index)
    if not candidates:
        return SlotResolution(STATUS_UNSUPPORTED, "level_not_in_visible_slots")
    if match_number > len(candidates):
        return SlotResolution(STATUS_UNSUPPORTED, "match_not_visible_without_scrolling", None, tuple(candidates))
    return SlotResolution(STATUS_OK, "slot_resolved", candidates[match_number - 1], tuple(candidates))
