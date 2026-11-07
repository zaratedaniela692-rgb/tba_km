"""Canonical Barracks category registry used by army-training goals."""

from dataclasses import dataclass

# Slots per global level, as verified for Gwardzists; other categories reuse it only while marked "assumed".
MATCH_COUNTS_BY_LEVEL = {**{level: 3 for level in range(1, 5)}, **{level: 4 for level in range(5, 10)}}


@dataclass(frozen=True)
class CategoryProfile:
    label: str
    selected_region: str | None = None  # regions.json entry showing this category highlighted in the list
    slot_map: str = "unverified"  # "verified", "assumed_like_guardsmen" or "unverified"


CATEGORY_PROFILES = {
    "guardsmen": CategoryProfile("Gwardziści", "troops_type_guardsmen_selected", "verified"),
    "specialists": CategoryProfile("Specjaliści", "troops_type_specialists_selected", "assumed_like_guardsmen"),
    "engineer_corps": CategoryProfile("Korpus inżynierów"),
    "dragons": CategoryProfile("Smoki"),
    "elementals": CategoryProfile("Żywiołaki"),
    "giants": CategoryProfile("Olbrzymy"),
    "beasts": CategoryProfile("Bestie"),
}
UNIT_TYPES = tuple(CATEGORY_PROFILES)
DEFAULT_UNIT_TYPE = "guardsmen"
SUPPORTED_TRAINING_UNIT_TYPES = frozenset(
    unit_type for unit_type, profile in CATEGORY_PROFILES.items() if profile.slot_map != "unverified"
)


def validate_unit_type(unit_type):
    if not isinstance(unit_type, str) or unit_type not in UNIT_TYPES:
        raise ValueError(f"Unsupported army unit type: {unit_type!r}.")
    return unit_type