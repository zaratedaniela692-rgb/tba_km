import json
from types import SimpleNamespace

import pytest

from tools import run_army_e2e as wrapper


def test_profile_router_must_return_unique_desktop_profile():
    route = json.dumps({"status": "routed", "client_id": "desktop", "profile_id": "account_1"})

    assert wrapper.resolve_desktop_profile(route) == "account_1"


@pytest.mark.parametrize("route", [
    {"status": "blocked", "client_id": "browser", "reason": "browser_identity_unconfigured"},
    {"status": "blocked", "client_id": "desktop", "reason": "profile_unresolved"},
    {"status": "not_game", "client_id": None, "reason": "foreground_window_is_not_game"},
])
def test_profile_router_blocks_before_any_device_scenario(route):
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(route), stderr="")

    with pytest.raises(wrapper.E2EError, match="A unique registered desktop profile is required"):
        wrapper.run_e2e(runner=runner)

    assert len(calls) == 1
    assert calls[0][1].endswith("client_router.py")
    assert "--register-missing" in calls[0]


def test_default_wrapper_previews_navigation_and_does_not_read_barracks(monkeypatch):
    calls = []
    monkeypatch.setattr(wrapper, "EXECUTE_GAME_ACTIONS", False)
    monkeypatch.setattr(wrapper, "RUN_NAVIGATION", True)
    monkeypatch.setattr(wrapper, "RUN_ARMY_SLOTS", True)

    def runner(command, **_kwargs):
        calls.append(command)
        if command[1].endswith("client_router.py"):
            stdout = json.dumps({"status": "routed", "client_id": "desktop", "profile_id": "account_1"})
        else:
            stdout = "{}"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    assert wrapper.run_e2e(runner=runner) == 0

    assert "--register-missing" in calls[0]
    scenario_commands = [command for command in calls if command[1].endswith("device_test.py")]
    assert [command[2] for command in scenario_commands] == ["preflight", "army_navigate"]
    assert all("--no-git" in command and "--no-push" in command for command in scenario_commands)
    assert all("--execute" not in command for command in scenario_commands)
    assert all("--profile" not in command for command in scenario_commands if command[2] == "preflight")
    assert "account_1" in scenario_commands[1]


def test_live_wrapper_passes_execute_only_to_explicit_navigation_and_keeps_train_off(monkeypatch):
    calls = []
    monkeypatch.setattr(wrapper, "EXECUTE_GAME_ACTIONS", True)
    monkeypatch.setattr(wrapper, "RUN_NAVIGATION", True)
    monkeypatch.setattr(wrapper, "RUN_ARMY_SLOTS", True)
    monkeypatch.setattr(wrapper, "RUN_ARMY_SCROLL", False)
    monkeypatch.setattr(wrapper, "RUN_SPECIALIST_TRAIN", False)

    def runner(command, **_kwargs):
        calls.append(command)
        stdout = json.dumps({"status": "routed", "client_id": "desktop", "profile_id": "account_1"})
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    assert wrapper.run_e2e(runner=runner) == 0

    scenario_commands = [command for command in calls if command[1].endswith("device_test.py")]
    assert [command[2] for command in scenario_commands] == ["preflight", "army_navigate", "army_slots"]
    assert "--execute" in scenario_commands[1]
    assert all("--execute" not in command for command in (scenario_commands[0], scenario_commands[2]))
    assert all(command[2] != "speedup_use" for command in scenario_commands)