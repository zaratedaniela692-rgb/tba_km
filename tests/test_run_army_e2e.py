import json
from types import SimpleNamespace

import pytest

from tools import run_army_e2e as wrapper


def test_test_profile_is_the_only_unmarked_finish_profile():
    assert wrapper.TEST_PROFILE_ID == "test"


def test_live_flow_is_testable_with_mocked_subprocess_and_profile(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    calls = []
    prepared = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 1:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"status": "TRAINING_IDLE_FOR_TEST"}),
                stderr="",
            )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "START_CONFIRMED", "quantity_confirmed": 100}),
            stderr="",
        )

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    monkeypatch.setattr(wrapper, "prepare_test_profile", lambda **kwargs: prepared.append(kwargs) or {"task_id": "task-1"})
    monkeypatch.setattr(wrapper, "_create_numbered_run_dir", lambda _started_at: run_dir)

    assert wrapper.run_e2e() == 0

    assert prepared == [{"finished_training": True}]
    assert len(calls) == 2
    preflight_command = calls[0][0]
    assert "--finish-active-for-test" in preflight_command
    assert "--navigate-only" in preflight_command
    training_command, training_kwargs = calls[1]
    assert training_command[training_command.index("--profile") + 1] == wrapper.TEST_PROFILE_ID
    assert training_command[training_command.index("--quantity") + 1] == str(wrapper.TRAINING_QUANTITY)
    assert training_command[training_command.index("--test-task-id") + 1] == "task-1"
    assert training_kwargs["env"]["TBA_RUN_DIR"] == str(run_dir)
    assert training_kwargs["env"]["TBA_PROFILE_ID"] == wrapper.TEST_PROFILE_ID

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["live_test_status"] == "PASSED"
    assert report["test_task_id"] == "task-1"


def test_preflight_failure_stops_before_profile_or_training_changes(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=2,
            stdout=json.dumps({"status": "TRAINING_STATE_UNKNOWN", "reason": "not_confirmed_idle"}),
            stderr="",
        )

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    monkeypatch.setattr(wrapper, "_create_numbered_run_dir", lambda _: tmp_path)
    monkeypatch.setattr(
        wrapper,
        "prepare_test_profile",
        lambda **_kwargs: pytest.fail("profile preparation must not run when preflight is blocked"),
    )

    with pytest.raises(wrapper.E2EError, match="did not confirm idle"):
        wrapper.run_e2e()

    assert len(calls) == 1
    assert "--finish-active-for-test" in calls[0]
    assert "--quantity" not in calls[0]
    assert json.loads((tmp_path / "report.json").read_text())["status"] == "FINISH_PREFLIGHT_FAILED"


@pytest.mark.parametrize("output", ("not json", "[]", '{"status":"BLOCKED_ACTIVE_TRAINING_FINISH"}'))
def test_invalid_or_blocked_preflight_never_prepares_goal(monkeypatch, tmp_path, output):
    calls = []
    monkeypatch.setattr(wrapper, "_create_numbered_run_dir", lambda _: tmp_path)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: calls.append(kwargs) or SimpleNamespace(
        returncode=0, stdout=output, stderr="diagnostic",
    ))
    monkeypatch.setattr(wrapper, "prepare_test_profile", lambda **_: pytest.fail("must not prepare goal"))

    with pytest.raises(wrapper.E2EError, match="did not confirm idle"):
        wrapper.run_e2e()

    assert len(calls) == 1
    assert calls[0]["env"]["TBA_RUN_DIR"] == str(tmp_path)
    assert "diagnostic" in (tmp_path / "preflight_log.txt").read_text()
    assert (tmp_path / "report.json").is_file()


def test_e2e_rejects_other_profile_before_subprocess(monkeypatch):
    monkeypatch.setattr(wrapper, "TEST_PROFILE_ID", "production")
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not launch"))
    with pytest.raises(wrapper.E2EError, match="restricted to the test profile"):
        wrapper.run_e2e()


def test_prepare_goal_preserves_unrelated_tasks_and_rearms_history(monkeypatch, tmp_path):
    from army_training_process import Slot, TrainingGoal, enqueue_training_goal
    from task_controller import create_task_queue, complete_task, enqueue_task, load_task_queue, save_task_queue, task_queue_path

    monkeypatch.setattr(wrapper, "ROOT_DIR", tmp_path)
    queue = create_task_queue("test")
    old = enqueue_training_goal(queue, TrainingGoal("test", Slot("guardsmen", 7, 1)), wrapper.datetime.now(wrapper.timezone.utc))
    complete_task(queue, old["task_id"], "e2e_idle_confirmed")
    unrelated = enqueue_task(queue, "building_upgrade", task_id="keep-building", payload={"building": "keep"})
    path = task_queue_path("test", tmp_path / "profiles")
    save_task_queue(queue, path)
    old_history = queue["tasks"][0]["payload"]["process"]["history"][:]

    prepared = wrapper.prepare_test_profile(finished_training=True)
    saved = load_task_queue(path, expected_profile_id="test")

    assert prepared["task_id"] == old["task_id"]
    assert prepared["status"] == "queued"
    assert saved["tasks"][1] == unrelated
    assert saved["tasks"][0]["payload"]["process"]["history"][:-1] == old_history


@pytest.mark.parametrize("blocker", ("marker", "active", "paused", "not_confirmed"))
def test_prepare_goal_blockers_preserve_saved_queue(monkeypatch, tmp_path, blocker):
    from army_state import army_state_path, open_training_marker
    from task_controller import create_task_queue, enqueue_task, save_task_queue, task_queue_path

    monkeypatch.setattr(wrapper, "ROOT_DIR", tmp_path)
    queue = create_task_queue("test")
    enqueue_task(queue, "building_upgrade", task_id="keep-building")
    if blocker == "active":
        queue["tasks"][0]["status"] = "waiting_help_delay"
    if blocker == "paused":
        queue["paused"] = True
        queue["pause_reason"] = "operator_pause"
    path = task_queue_path("test", tmp_path / "profiles")
    save_task_queue(queue, path)
    before = path.read_bytes()
    if blocker == "marker":
        now = wrapper.datetime.now(wrapper.timezone.utc)
        open_training_marker(army_state_path("test", tmp_path / "profiles"), "order", "old", {}, now, now)

    with pytest.raises(wrapper.E2EError):
        wrapper.prepare_test_profile(finished_training=blocker != "not_confirmed")
    assert path.read_bytes() == before