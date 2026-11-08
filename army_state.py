"""Per-profile cache of slowly changing Barracks facts (currently the max unit level)."""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from task_controller import PROFILES_DIR, task_queue_path
from army_unit_types import DEFAULT_UNIT_TYPE, validate_unit_type

DEFAULT_MAX_LEVEL_TTL = timedelta(hours=24)
MIN_LEVEL = 1
MAX_LEVEL = 9


class ArmyStateError(ValueError):
    """Raised when the persisted army state is malformed."""


@dataclass(frozen=True)
class MaxLevelResult:
    status: str  # "ok" or "blocked"
    level: int | None
    source: str  # "fresh", "cache" or "none"
    reason: str


def army_state_path(profile_id, profiles_dir=PROFILES_DIR):
    return task_queue_path(profile_id, profiles_dir).with_name("army_state.json")


def _valid_level(value):
    return type(value) is int and MIN_LEVEL <= value <= MAX_LEVEL


def load_army_state(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArmyStateError(f"Cannot read army state: {error}") from error
    if not isinstance(state, dict):
        raise ArmyStateError("Army state must be a JSON object.")
    return state


def _write_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return state


def save_max_level(path, unit_type, level, observed_at, source, confidence=None):
    try:
        validate_unit_type(unit_type)
    except ValueError as error:
        raise ArmyStateError(str(error)) from error
    if not _valid_level(level):
        raise ArmyStateError("Max level must be an integer 1-9.")
    if observed_at.tzinfo is None:
        raise ArmyStateError("observed_at must be timezone-aware.")
    state = load_army_state(path)
    max_levels = state.setdefault("max_levels", {})
    if "max_level" in state:
        max_levels.setdefault(DEFAULT_UNIT_TYPE, state.pop("max_level"))
    max_levels[unit_type] = {
        "level": level,
        "observed_at": observed_at.astimezone(timezone.utc).isoformat(),
        "source": source,
        "confidence": confidence,
    }
    return _write_state(path, state)


def _iso(value):
    if value.tzinfo is None:
        raise ArmyStateError("Timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat()


def open_training(state):
    marker = (state or {}).get("open_training")
    return marker if isinstance(marker, dict) else None


def open_training_marker(path, order_id, task_id, goal, started_at, expires_at):
    """Record that the bot started a training whose end is not yet confirmed."""
    state = load_army_state(path)
    state["open_training"] = {
        "order_id": order_id,
        "task_id": task_id,
        "goal": goal,
        "started_at": _iso(started_at),
        "expires_at": _iso(expires_at),
        "speedup_attempts": 0,
        "last_attempt_at": None,
        "next_attempt_at": None,
    }
    return _write_state(path, state)


def clear_open_training(path):
    state = load_army_state(path)
    if state.pop("open_training", None) is None:
        return False
    _write_state(path, state)
    return True


def record_speedup_attempt(path, now, retry_seconds):
    """Count a failed finish attempt and schedule the next one; the marker stays open."""
    state = load_army_state(path)
    marker = open_training(state)
    if marker is None:
        raise ArmyStateError("No open training to record an attempt for.")
    marker["speedup_attempts"] = int(marker.get("speedup_attempts", 0)) + 1
    marker["last_attempt_at"] = _iso(now)
    marker["next_attempt_at"] = _iso(now + timedelta(seconds=retry_seconds))
    _write_state(path, state)
    return marker


def record_finish_button_attempt(path, now):
    """Persist the one-shot finish-button attempt before sending its click."""
    state = load_army_state(path)
    marker = open_training(state)
    if marker is None:
        raise ArmyStateError("No open training to record a finish-button attempt for.")
    marker.setdefault("finish_button_attempted_at", _iso(now))
    _write_state(path, state)
    return marker


def parse_marker_time(marker, key):
    value = marker.get(key)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ArmyStateError(f"Invalid {key} in open training marker.") from error
    if parsed.tzinfo is None:
        raise ArmyStateError(f"{key} in open training marker must be timezone-aware.")
    return parsed


def resolve_max_level(unit_type, fresh_level, state, now, ttl=DEFAULT_MAX_LEVEL_TTL):
    """A fresh read wins; the cache is used only when the read failed and is within TTL."""
    try:
        validate_unit_type(unit_type)
    except ValueError:
        return MaxLevelResult("blocked", None, "none", "unit_type_unknown")
    if fresh_level is not None:
        if not _valid_level(fresh_level):
            return MaxLevelResult("blocked", None, "none", "fresh_max_level_out_of_range")
        return MaxLevelResult("ok", fresh_level, "fresh", "read_from_barracks")
    cached = (state or {}).get("max_levels", {}).get(unit_type)
    if cached is None and unit_type == DEFAULT_UNIT_TYPE:
        cached = (state or {}).get("max_level")
    if not isinstance(cached, dict) or not _valid_level(cached.get("level")):
        return MaxLevelResult("blocked", None, "none", "max_level_unavailable")
    try:
        observed_at = datetime.fromisoformat(cached["observed_at"])
    except (KeyError, TypeError, ValueError):
        return MaxLevelResult("blocked", None, "none", "cached_max_level_timestamp_invalid")
    if observed_at.tzinfo is None or not timedelta(0) <= now - observed_at <= ttl:
        return MaxLevelResult("blocked", None, "none", "cached_max_level_stale")
    return MaxLevelResult("ok", cached["level"], "cache", "fresh_read_failed_using_cache")
