"""Build a typed SlotObservation from one slot's readings; evidence only, no decisions."""

from datetime import datetime

from army_training_process import NumericReading, Slot, SlotObservation


def build_slot_observation(
    profile_id: str,
    slot: Slot,
    level_reading,
    slot_readings,
    training_status: str,
    observed_at: datetime,
    source: str,
) -> SlotObservation:
    """The selected level is the largest badge (default-highest assumption), so the
    selection counts as verified only when that level equals the goal level."""
    highest = level_reading.highest_visible_level if level_reading.status == "candidate" else None
    confidence = level_reading.confidence if highest is not None else None
    limit = slot_readings.queue_limit
    # Both levels of one slot share that slot's own queue limit.
    limit_levels = {slot.global_level}
    if highest is not None:
        limit_levels |= {highest, highest - 1}
    return SlotObservation(
        profile_id=profile_id,
        slot=slot,
        observed_at=observed_at,
        source=source,
        training_status=training_status,
        highest_unlocked_level=NumericReading(highest, confidence),
        city_count=slot_readings.city_count,
        queue_limits={level: limit for level in limit_levels if level >= 1},
        selection_verified=highest is not None and highest == slot.global_level,
    )
