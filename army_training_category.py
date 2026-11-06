"""Barracks category selection boundary; real UI selection is not implemented yet."""

from army_unit_types import DEFAULT_UNIT_TYPE, validate_unit_type


def select_army_type(unit_type):
    """Mock the category selection step without sending any game input."""
    try:
        validate_unit_type(unit_type)
    except ValueError:
        return {"status": "BLOCKED_UNKNOWN_UNIT_TYPE", "unit_type": unit_type, "actions_executed": False}
    if unit_type != DEFAULT_UNIT_TYPE:
        return {
            "status": "BLOCKED_CATEGORY_SELECTION_UNIMPLEMENTED",
            "unit_type": unit_type,
            "actions_executed": False,
        }
    return {
        "status": "DEFAULT_CATEGORY_ASSUMED",
        "unit_type": DEFAULT_UNIT_TYPE,
        "selection_confirmed": False,
        "actions_executed": False,
    }