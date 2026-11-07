import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

import army_training_manager as manager
from profile_identity import (
    ProfileIdentityError,
    create_profile_id,
    profile_registry_path,
    read_player_name,
    resolve_profile,
)
from speedup_reader import configure_tesseract

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "screenshots" / "world_map"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def test_reads_player_names_from_both_full_desktop_account_fixtures():
    configure_tesseract()
    expected = {
        "zrzut_pulpitu": "snoweye",
        "zrzut_pulpitu_account_2": "xirrus",
    }

    for fixture, player_name in expected.items():
        frame = cv2.imread(str(SCREENSHOTS / f"{fixture}.png"))
        reading = read_player_name(frame)
        assert reading.status == "ok"
        assert reading.player_name.casefold() == player_name
        assert len(reading.candidates) == 4


def test_player_name_ocr_blocks_wrong_size_and_empty_frame():
    assert read_player_name(np.zeros((720, 1280, 3), dtype=np.uint8)).reason == "unsupported_frame_size"
    assert read_player_name(None).reason == "unsupported_frame_size"


def test_slugged_profile_id_has_five_random_characters_and_handles_unicode():
    profile_id = create_profile_id("Élise Test", suffix_factory=lambda: "12as3")

    assert profile_id == "elise_test_12as3"


def test_suffix_collision_is_retried():
    suffixes = iter(("12as3", "12as3", "xy9b2"))

    profile_id = create_profile_id(
        "Snoweye", existing_ids={"snoweye_12as3"}, suffix_factory=lambda: next(suffixes),
    )

    assert profile_id == "snoweye_xy9b2"


def test_first_resolution_creates_id_once_and_following_resolution_reuses_it(tmp_path):
    path = profile_registry_path(tmp_path)
    created = resolve_profile("Snoweye", path, now=NOW, suffix_factory=lambda: "12as3")
    reused = resolve_profile("snoweye", path, choose_fn=lambda _: "1", now=NOW)

    assert created.profile_id == reused.profile_id == "snoweye_12as3"
    assert created.action == "created" and reused.action == "reused"
    registry = json.loads(path.read_text(encoding="utf-8"))
    assert len(registry["profiles"]) == 1
    assert registry["profiles"][0]["player_name"] == "Snoweye"


def test_new_profile_creates_distinct_id_for_same_player_name(tmp_path):
    path = profile_registry_path(tmp_path)
    resolve_profile("Snoweye", path, now=NOW, suffix_factory=lambda: "12as3")

    second = resolve_profile(
        "Snoweye", path, new_profile=True, now=NOW, suffix_factory=lambda: "ab456",
    )

    assert second.action == "created"
    assert second.profile_id == "snoweye_ab456"
    assert len(json.loads(path.read_text(encoding="utf-8"))["profiles"]) == 2


def test_existing_single_name_match_requires_an_explicit_reuse_or_new_choice(tmp_path):
    path = profile_registry_path(tmp_path)
    existing = resolve_profile("Snoweye", path, now=NOW, suffix_factory=lambda: "12as3")
    prompts = []

    result = resolve_profile("Snoweye", path, choose_fn=lambda prompt: prompts.append(prompt) or "n", now=NOW,
                             suffix_factory=lambda: "ab456")

    assert result.profile_id == "snoweye_ab456" and result.action == "created"
    assert prompts and len(json.loads(path.read_text(encoding="utf-8"))["profiles"]) == 2


def test_multiple_same_name_profiles_prompt_to_choose_or_create(tmp_path):
    path = profile_registry_path(tmp_path)
    resolve_profile("Snoweye", path, now=NOW, suffix_factory=lambda: "12as3")
    resolve_profile("Snoweye", path, new_profile=True, now=NOW, suffix_factory=lambda: "ab456")
    prompts = []

    selected = resolve_profile("Snoweye", path, choose_fn=lambda prompt: prompts.append(prompt) or "2", now=NOW)
    created = resolve_profile(
        "Snoweye", path, choose_fn=lambda _: "n", now=NOW, suffix_factory=lambda: "z9q8w",
    )

    assert selected.profile_id == "snoweye_ab456" and selected.action == "selected"
    assert created.profile_id == "snoweye_z9q8w" and created.action == "created"
    assert prompts and "Select profile" in prompts[0]


def test_invalid_or_unreadable_registry_fails_closed(tmp_path):
    path = profile_registry_path(tmp_path)
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ProfileIdentityError, match="unreadable"):
        resolve_profile("Snoweye", path)


def test_manager_auto_profile_uses_resolved_id_and_reports_identity(monkeypatch, tmp_path, capsys):
    from profile_identity import PlayerNameReading, ProfileResolution

    monkeypatch.setattr(
        manager, "resolve_profile_from_game",
        lambda **_: (ProfileResolution("snoweye_12as3", "Snoweye", "reused"),
                     PlayerNameReading("ok", "Snoweye", ("Snoweye",) * 4)),
    )
    monkeypatch.setattr(manager, "_command_list", lambda args, *_: {"profile": args.profile, "status": "ok"})

    code = manager.main(["--profile", "auto", "--profiles-dir", str(tmp_path), "list"], now=NOW)
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["profile"] == "snoweye_12as3"
    assert report["profile_identity"] == {
        "player_name": "Snoweye", "profile_id": "snoweye_12as3", "action": "reused",
        "ocr_passes": ["Snoweye"] * 4,
    }


def test_explicit_profile_skips_screen_ocr(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(manager, "resolve_profile_from_game", lambda **_: pytest.fail("must not capture or OCR"))
    monkeypatch.setattr(manager, "_command_list", lambda args, *_: {"profile": args.profile})

    assert manager.main(["--profile", "manual-account", "--profiles-dir", str(tmp_path), "list"], now=NOW) == 0
    assert json.loads(capsys.readouterr().out)["profile"] == "manual-account"


def test_uncertain_player_name_does_not_create_a_registry_entry(monkeypatch, tmp_path):
    import army_training_live_e2e
    import profile_identity

    monkeypatch.setattr(
        army_training_live_e2e, "capture_primary_monitor",
        lambda: (np.zeros((1080, 1920, 3), dtype=np.uint8), (0, 0)),
    )
    monkeypatch.setattr(
        profile_identity, "read_player_name",
        lambda *_args, **_kwargs: profile_identity.PlayerNameReading(
            "ambiguous", None, ("Snoweye", "Snoweye_"), "ocr_passes_disagree",
        ),
    )

    with pytest.raises(ProfileIdentityError, match="Could not confidently read"):
        profile_identity.resolve_profile_from_game(profiles_dir=tmp_path)
    assert not profile_registry_path(tmp_path).exists()


def test_new_profile_flag_requires_auto_profile(tmp_path, capsys):
    assert manager.main(["--profile", "manual", "--new-profile", "--profiles-dir", str(tmp_path), "list"], now=NOW) == 2
    assert "requires --profile auto" in capsys.readouterr().err
