from datetime import datetime, timezone
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from client_router import (
    CLIENT_BROWSER,
    CLIENT_DESKTOP,
    CLIENT_NOT_GAME,
    CLIENT_UNKNOWN,
    ForegroundWindow,
    RouteObservation,
    classify_foreground_window,
    observe_foreground_profile,
    watch_foreground,
)
from profile_identity import profile_registry_path, resolve_profile
from task_controller import task_queue_path
from ui_variants import UIVariantError, resolve_variant

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "window, expected",
    (
        (ForegroundWindow("Total Battle - Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"), CLIENT_BROWSER),
        (ForegroundWindow("Total Battle", r"C:\Games\TotalBattle\TotalBattle.exe"), CLIENT_DESKTOP),
        (ForegroundWindow("VS Code", r"C:\Program Files\Microsoft VS Code\Code.exe"), CLIENT_NOT_GAME),
        (ForegroundWindow("Total Battle - Chrome", ""), CLIENT_UNKNOWN),
        (None, CLIENT_UNKNOWN),
    ),
)
def test_classifies_only_known_foreground_game_clients(window, expected):
    client_id, _reason = classify_foreground_window(window)

    assert client_id == expected


def test_browser_variant_is_explicitly_planned_and_never_falls_back_to_desktop():
    with pytest.raises(UIVariantError, match="not available"):
        resolve_variant("browser")


def test_browser_is_detected_but_blocked_until_browser_identity_assets_are_ready(tmp_path):
    capture_calls = []

    observation = observe_foreground_profile(
        ForegroundWindow("Total Battle - Chrome", "chrome.exe"),
        capture_fn=lambda: capture_calls.append(True),
        profiles_dir=tmp_path,
    )

    assert observation.status == "blocked"
    assert observation.client_id == CLIENT_BROWSER
    assert observation.reason == "browser_identity_unconfigured"
    assert observation.profile_id is None
    assert observation.queue_path is None
    assert capture_calls == []


def test_desktop_routes_only_to_one_registered_profile_queue(tmp_path):
    profile_id = resolve_profile("Snoweye", profile_registry_path(tmp_path), now=NOW).profile_id
    frame = object()

    observation = observe_foreground_profile(
        ForegroundWindow("Total Battle", "TotalBattle.exe"),
        capture_fn=lambda: (frame, (0, 0)),
        profiles_dir=tmp_path,
        name_reader=lambda actual_frame, **kwargs: SimpleNamespace(
            status="ok", player_name=" snoweye ", candidates=("Snoweye",) * 4,
        ),
    )

    assert observation.status == "routed"
    assert observation.client_id == CLIENT_DESKTOP
    assert observation.player_name == " snoweye "
    assert observation.profile_id == profile_id
    assert observation.queue_path == str(task_queue_path(profile_id, tmp_path))


def test_desktop_auto_registration_creates_and_reuses_missing_profile(tmp_path):
    registry_path = profile_registry_path(tmp_path)
    reader = lambda *_args, **_kwargs: SimpleNamespace(
        status="ok", player_name="Snoweye", candidates=("Snoweye",) * 4,
    )

    created = observe_foreground_profile(
        ForegroundWindow("Total Battle", "TotalBattle.exe"),
        capture_fn=lambda: (object(), (0, 0)),
        profiles_dir=tmp_path,
        name_reader=reader,
    )
    routed = observe_foreground_profile(
        ForegroundWindow("Total Battle", "TotalBattle.exe"),
        capture_fn=lambda: (object(), (0, 0)),
        profiles_dir=tmp_path,
        name_reader=reader,
    )

    assert created.status == "routed"
    assert created.reason == "profile_registered"
    assert created.profile_id == routed.profile_id
    assert routed.status == "routed"


def test_read_only_opt_out_does_not_register_missing_profile(tmp_path):
    observation = observe_foreground_profile(
        ForegroundWindow("Total Battle", "TotalBattle.exe"),
        capture_fn=lambda: (object(), (0, 0)),
        profiles_dir=tmp_path,
        name_reader=lambda *_args, **_kwargs: SimpleNamespace(
            status="ok", player_name="Snoweye", candidates=("Snoweye",) * 4,
        ),
        register_missing=False,
    )

    assert observation.status == "blocked"
    assert observation.reason.startswith("profile_unresolved:")
    assert not profile_registry_path(tmp_path).exists()


def test_registry_write_failure_blocks_profile_routing(tmp_path, monkeypatch):
    import profile_identity

    monkeypatch.setattr(
        profile_identity,
        "save_profile_registry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("access denied")),
    )

    observation = observe_foreground_profile(
        ForegroundWindow("Total Battle", "TotalBattle.exe"),
        capture_fn=lambda: (object(), (0, 0)),
        profiles_dir=tmp_path,
        name_reader=lambda *_args, **_kwargs: SimpleNamespace(
            status="ok", player_name="Snoweye", candidates=("Snoweye",) * 4,
        ),
    )

    assert observation.status == "blocked"
    assert observation.profile_id is None
    assert observation.queue_path is None
    assert observation.reason.startswith("profile_registry_write_failed:")


@pytest.mark.parametrize("duplicate", (False, True))
def test_auto_registration_routes_first_duplicate_profile_or_creates_new_profile(tmp_path, duplicate):
    registry_path = profile_registry_path(tmp_path)
    first_profile = None
    if duplicate:
        first_profile = resolve_profile("Snoweye", registry_path, now=NOW)
        resolve_profile("Snoweye", registry_path, new_profile=True, now=NOW)

    observation = observe_foreground_profile(
        ForegroundWindow("Total Battle", "TotalBattle.exe"),
        capture_fn=lambda: (object(), (0, 0)),
        profiles_dir=tmp_path,
        name_reader=lambda *_args, **_kwargs: SimpleNamespace(
            status="ok", player_name="Snoweye", candidates=("Snoweye",) * 4,
        ),
    )

    assert observation.status == "routed"
    assert observation.profile_id is not None
    assert observation.queue_path == str(task_queue_path(observation.profile_id, tmp_path))
    if duplicate:
        assert observation.profile_id == first_profile.profile_id
    else:
        assert observation.reason == "profile_registered"


def test_auto_registration_routes_first_duplicate_profile(tmp_path):
    registry_path = profile_registry_path(tmp_path)
    first_profile = resolve_profile("Snoweye", registry_path, now=NOW)
    resolve_profile("Snoweye", registry_path, new_profile=True, now=NOW)

    observation = observe_foreground_profile(
        ForegroundWindow("Total Battle", "TotalBattle.exe"),
        capture_fn=lambda: (object(), (0, 0)),
        profiles_dir=tmp_path,
        name_reader=lambda *_args, **_kwargs: SimpleNamespace(
            status="ok", player_name="Snoweye", candidates=("Snoweye",) * 4,
        ),
    )

    assert observation.status == "routed"
    assert observation.profile_id == first_profile.profile_id


def test_ambiguous_name_ocr_saves_crop_and_blocks_routing(tmp_path, monkeypatch):
    import client_router

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[115:135, 714:914] = (13, 27, 41)
    output_path = tmp_path / "player_name_region.png"
    monkeypatch.setattr(
        client_router,
        "_save_ambiguous_player_name_crop",
        lambda actual_frame: client_router.save_player_name_crop(actual_frame, output_path),
    )
    observation = observe_foreground_profile(
        ForegroundWindow("Total Battle", "TotalBattle.exe"),
        capture_fn=lambda: (frame, (0, 0)),
        profiles_dir=tmp_path,
        name_reader=lambda *_args, **_kwargs: SimpleNamespace(
            status="ambiguous", player_name=None, candidates=("Snoweye", "Snoweye_"), reason="ocr_disagree",
        ),
    )

    assert observation.status == "blocked"
    assert observation.profile_id is None
    assert observation.queue_path is None
    assert observation.reason.startswith("player_name_ambiguous:")
    assert observation.evidence_path == str(output_path)
    assert observation.evidence_error is None
    assert not profile_registry_path(tmp_path).exists()
    saved_crop = cv2.imread(str(output_path))
    assert saved_crop.shape == (20, 200, 3)
    assert tuple(saved_crop[0, 0]) == (13, 27, 41)


def test_cli_defaults_to_registration_and_supports_read_only_opt_out(monkeypatch, capsys):
    import client_router

    registration_modes = []

    def observe(register_missing=True):
        registration_modes.append(register_missing)
        return RouteObservation("blocked", "desktop", None, None, None, "test", "Total Battle", "game.exe")

    monkeypatch.setattr(client_router, "observe_foreground_profile", observe)

    assert client_router.main(["--once"]) == 0
    capsys.readouterr()
    assert client_router.main(["--once", "--no-register-missing"]) == 0
    capsys.readouterr()

    assert registration_modes == [True, False]


def test_continuous_cli_defaults_to_registration(monkeypatch):
    import client_router

    called = {}

    def fake_watch(observe_fn, interval_seconds):
        called["observation"] = observe_fn()
        called["interval"] = interval_seconds

    monkeypatch.setattr(client_router, "watch_foreground", fake_watch)
    monkeypatch.setattr(
        client_router,
        "observe_foreground_profile",
        lambda register_missing=True: RouteObservation(
            "routed", "desktop", "Snoweye", "snoweye_12345", "queue", "ok", "Total Battle", "game.exe",
        ) if register_missing else None,
    )

    assert client_router.main([]) == 0
    assert called["observation"].profile_id == "snoweye_12345"
    assert called["interval"] == 1.0


def test_watch_outputs_only_when_foreground_route_changes():
    observations = iter((
        RouteObservation("routed", "desktop", "A", "p1", "queue-p1", "ok", "Total Battle", "game.exe"),
        RouteObservation("routed", "desktop", "A", "p1", "queue-p1", "ok", "Total Battle", "game.exe"),
        RouteObservation("blocked", "browser", None, None, None, "browser_identity_unconfigured",
                         "Total Battle - Chrome", "chrome.exe"),
    ))
    stop_values = iter((False, False, False, True))
    outputs = []

    watch_foreground(
        observe_fn=lambda: next(observations),
        stop_fn=lambda: next(stop_values),
        sleep_fn=lambda _: None,
        output=outputs.append,
    )

    assert len(outputs) == 2
    assert '"profile_id": "p1"' in outputs[0]
    assert '"client_id": "browser"' in outputs[1]