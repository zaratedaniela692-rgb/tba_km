"""Canonical Barracks category identifiers used by army-training goals."""

UNIT_TYPES = (
    "guardsmen",
    "specialists",
    "engineer_corps",
    "dragons",
    "elementals",
    "giants",
    "beasts",
)
DEFAULT_UNIT_TYPE = "guardsmen"
SUPPORTED_TRAINING_UNIT_TYPES = frozenset({DEFAULT_UNIT_TYPE})


def validate_unit_type(unit_type):
    if not isinstance(unit_type, str) or unit_type not in UNIT_TYPES:
        raise ValueError(f"Unsupported army unit type: {unit_type!r}.")
    return unit_type