from types import SimpleNamespace

from tools import run_army_e2e as wrapper


def test_test_profile_is_the_default_and_can_be_overridden():
    assert wrapper.TEST_PROFILE_ID == "test"


def test_default_wrapper_previews_navigation_and_does_not_read_barracks(monkeypatch):
    calls = []
    monkeypatch.setattr(wrapper, "EXECUTE_GAME_ACTIONS", False)
    monkeypatch.setattr(wrapper, "RUN_NAVIGATION", True)
    monkeypatch.setattr(wrapper, "RUN_ARMY_SLOTS", True)

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    assert wrapper.run_e2e(runner=runner) == 0

    scenario_commands = [command for command in calls if command[1].endswith("device_test.py")]
    assert [command[2] for command in scenario_commands] == ["preflight", "army_navigate"]
    assert all("--no-git" in command and "--no-push" in command for command in scenario_commands)
    assert all("--execute" not in command for command in scenario_commands)
    assert all("--profile" not in command for command in scenario_commands if command[2] == "preflight")
    assert scenario_commands[1][scenario_commands[1].index("--profile") + 1] == "test"


def test_live_wrapper_passes_execute_only_to_explicit_navigation_and_keeps_train_off(monkeypatch):
    calls = []
    monkeypatch.setattr(wrapper, "EXECUTE_GAME_ACTIONS", True)
    monkeypatch.setattr(wrapper, "RUN_NAVIGATION", True)
    monkeypatch.setattr(wrapper, "RUN_ARMY_SLOTS", True)
    monkeypatch.setattr(wrapper, "RUN_ARMY_SCROLL", False)
    monkeypatch.setattr(wrapper, "RUN_SPECIALIST_TRAIN", False)

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    assert wrapper.run_e2e(runner=runner) == 0

    scenario_commands = [command for command in calls if command[1].endswith("device_test.py")]
    assert [command[2] for command in scenario_commands] == ["preflight", "army_navigate", "army_slots"]
    assert "--execute" in scenario_commands[1]
    assert scenario_commands[1][scenario_commands[1].index("--profile") + 1] == "test"
    assert all("--execute" not in command for command in (scenario_commands[0], scenario_commands[2]))
    assert all(command[2] != "speedup_use" for command in scenario_commands)


def test_queued_training_scenario_passes_exact_quantity_and_confirmation():
    scenario = wrapper._queued_training_scenario("account_1", 100)
    command = scenario["steps"][0]["execute_argv"]

    assert command[command.index("--quantity") + 1] == "100"
    assert command[command.index("--profile") + 1] == "account_1"
    assert command[command.index("--confirm") + 1] == "EXECUTE ARMY TRAINING"
    assert scenario["name"] == "army_training_quantity"