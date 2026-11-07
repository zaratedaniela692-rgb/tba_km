"""Resolve a local task profile from the visible in-game player name."""

import json
import os
import re
import secrets
import string
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import pytesseract

from army_training_scanner import _load_regions
from speedup_reader import configure_tesseract
from ui_variants import resolve_variant

FULL_FRAME_SIZE = (1920, 1080)
FULL_FRAME_Y_OFFSET = 39
NAME_SCALES = (4, 7)
NAME_PSMS = (8, 13)
NAME_CHARACTERS = string.ascii_letters + string.digits + "_-"
PROFILE_SUFFIX_LENGTH = 5
PROFILE_SUFFIX_CHARACTERS = string.ascii_lowercase + string.digits
REGISTRY_SCHEMA_VERSION = 1


class ProfileIdentityError(ValueError):
    """The visible game identity cannot be safely mapped to a local profile."""


@dataclass(frozen=True)
class PlayerNameReading:
    status: str
    player_name: str | None
    candidates: tuple[str, ...]
    reason: str = ""


@dataclass(frozen=True)
class ProfileResolution:
    profile_id: str
    player_name: str
    action: str


def _normalize_name(value):
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip(" _-")
    return normalized


def read_player_name(frame, variant=None, tesseract_cmd=None):
    """Read the HUD name only when four independent OCR passes agree."""
    if frame is None or (frame.shape[1], frame.shape[0]) != FULL_FRAME_SIZE:
        return PlayerNameReading("blocked", None, (), "unsupported_frame_size")
    configure_tesseract(tesseract_cmd)
    variant = variant or resolve_variant()
    regions = _load_regions(variant["regions"])
    region = regions.get("world_map", {}).get("player_name")
    if region is None:
        return PlayerNameReading("blocked", None, (), "player_name_region_missing")

    x, y, width, height = (int(region[key]) for key in ("x", "y", "w", "h"))
    y += FULL_FRAME_Y_OFFSET
    crop = frame[y:y + height, x:x + width]
    if crop.shape[:2] != (height, width):
        return PlayerNameReading("blocked", None, (), "player_name_region_outside_frame")

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    reads = []
    try:
        for scale in NAME_SCALES:
            enlarged = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            for psm in NAME_PSMS:
                raw = pytesseract.image_to_string(
                    enlarged,
                    config=f"--psm {psm} -c tessedit_char_whitelist={NAME_CHARACTERS}",
                )
                candidate = _normalize_name(raw)
                if candidate:
                    reads.append(candidate)
    except pytesseract.TesseractNotFoundError as error:
        raise ProfileIdentityError("Tesseract OCR was not found.") from error

    normalized = {name.casefold() for name in reads}
    if len(reads) != len(NAME_SCALES) * len(NAME_PSMS):
        return PlayerNameReading("ambiguous", None, tuple(reads), "one_or_more_ocr_passes_empty")
    if len(normalized) != 1:
        return PlayerNameReading("ambiguous", None, tuple(reads), "ocr_passes_disagree")
    return PlayerNameReading("ok", reads[0], tuple(reads))


def profile_registry_path(profiles_dir):
    return Path(profiles_dir) / "profile_registry.json"


def load_profile_registry(path):
    path = Path(path)
    if not path.exists():
        return {"schema_version": REGISTRY_SCHEMA_VERSION, "profiles": []}
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileIdentityError(f"Profile registry is unreadable: {error}") from error
    if not isinstance(registry, dict):
        raise ProfileIdentityError("Profile registry has an unsupported format.")
    profiles = registry.get("profiles")
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION or not isinstance(profiles, list):
        raise ProfileIdentityError("Profile registry has an unsupported format.")
    for profile in profiles:
        if (
            not isinstance(profile, dict)
            or not isinstance(profile.get("profile_id"), str)
            or not isinstance(profile.get("player_name"), str)
        ):
            raise ProfileIdentityError("Profile registry contains an invalid entry.")
    return registry


def save_profile_registry(path, registry):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(registry, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _name_slug(player_name):
    normalized = unicodedata.normalize("NFKD", player_name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9_-]+", "_", ascii_name).strip("_-")
    return slug[:32] or "player"


def create_profile_id(player_name, existing_ids=(), suffix_factory=None):
    suffix_factory = suffix_factory or (
        lambda: "".join(secrets.choice(PROFILE_SUFFIX_CHARACTERS) for _ in range(PROFILE_SUFFIX_LENGTH))
    )
    existing = set(existing_ids)
    for _ in range(100):
        suffix = suffix_factory()
        if len(suffix) != PROFILE_SUFFIX_LENGTH or any(char not in PROFILE_SUFFIX_CHARACTERS for char in suffix):
            raise ProfileIdentityError("Profile suffix generator returned an invalid value.")
        profile_id = f"{_name_slug(player_name)}_{suffix}"
        if profile_id not in existing:
            return profile_id
    raise ProfileIdentityError("Could not generate a unique profile ID.")


def _new_profile(player_name, registry, now=None, suffix_factory=None):
    profile_id = create_profile_id(
        player_name,
        (profile["profile_id"] for profile in registry["profiles"]),
        suffix_factory,
    )
    created_at = (now or datetime.now(timezone.utc)).isoformat()
    registry["profiles"].append({
        "profile_id": profile_id,
        "player_name": player_name,
        "created_at": created_at,
        "last_seen_at": created_at,
    })
    return ProfileResolution(profile_id, player_name, "created")


def resolve_profile(
    player_name,
    registry_path,
    new_profile=False,
    choose_fn=input,
    now=None,
    suffix_factory=None,
):
    """Reuse a unique match, create once, or ask which identical-name account is open."""
    player_name = _normalize_name(player_name)
    if not player_name:
        raise ProfileIdentityError("Player name is empty.")
    registry = load_profile_registry(registry_path)
    matches = [
        profile for profile in registry["profiles"]
        if _normalize_name(profile["player_name"]).casefold() == player_name.casefold()
    ]

    if new_profile or not matches:
        result = _new_profile(player_name, registry, now, suffix_factory)
    else:
        print(f"Detected player name: {player_name}")
        for index, profile in enumerate(matches, start=1):
            print(f"{index}. Use {profile['profile_id']}")
        print(f"N. Create a new profile for {player_name}")
        try:
            choice = choose_fn("Select profile number or N: ").strip()
        except (EOFError, OSError) as error:
            raise ProfileIdentityError("Multiple profiles match; interactive selection is required.") from error
        if choice.casefold() == "n":
            result = _new_profile(player_name, registry, now, suffix_factory)
        else:
            try:
                index = int(choice) - 1
            except ValueError as error:
                raise ProfileIdentityError("Invalid profile selection.") from error
            if not 0 <= index < len(matches):
                raise ProfileIdentityError("Profile selection is outside the available choices.")
            action = "reused" if len(matches) == 1 else "selected"
            result = ProfileResolution(matches[index]["profile_id"], matches[index]["player_name"], action)

    selected = next(profile for profile in registry["profiles"] if profile["profile_id"] == result.profile_id) if result.action != "created" else registry["profiles"][-1]
    selected["last_seen_at"] = (now or datetime.now(timezone.utc)).isoformat()
    save_profile_registry(registry_path, registry)
    return result


def resolve_registered_profile(player_name, registry_path):
    """Resolve exactly one existing player-name mapping without prompting or creating profiles."""
    normalized_name = _normalize_name(player_name)
    if not normalized_name:
        raise ProfileIdentityError("Player name is empty.")
    registry = load_profile_registry(registry_path)
    matches = [
        profile for profile in registry["profiles"]
        if _normalize_name(profile["player_name"]).casefold() == normalized_name.casefold()
    ]
    if not matches:
        raise ProfileIdentityError("No registered profile matches the visible player name.")
    if len(matches) != 1:
        raise ProfileIdentityError("Multiple profiles match the visible player name; routing is ambiguous.")
    return ProfileResolution(matches[0]["profile_id"], matches[0]["player_name"], "routed")


def resolve_profile_from_game(capture_fn=None, profiles_dir=None, new_profile=False, choose_fn=input, tesseract_cmd=None):
    """Capture the primary monitor, read the HUD name, and resolve its local profile."""
    from army_training_live_e2e import capture_primary_monitor
    from task_controller import PROFILES_DIR

    capture_fn = capture_fn or capture_primary_monitor
    frame, _origin = capture_fn()
    reading = read_player_name(frame, tesseract_cmd=tesseract_cmd)
    if reading.status != "ok" or reading.player_name is None:
        detail = ", ".join(reading.candidates) or reading.reason
        raise ProfileIdentityError(f"Could not confidently read player name ({reading.reason}): {detail}")
    registry_path = profile_registry_path(profiles_dir or PROFILES_DIR)
    return resolve_profile(reading.player_name, registry_path, new_profile, choose_fn), reading
