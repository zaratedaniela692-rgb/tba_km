import json

from tools import (
    test_army_queue_e2e as army_queue_e2e,
    test_army_training_module as army_module,
    test_speedup_module as speedup_module,
    test_task_queue_module as queue_module,
)


def test_module_wrappers_report_offline_result_and_provenance():
    for wrapper in (speedup_module, army_module, queue_module, army_queue_e2e):
        reports = []
        assert wrapper.main([], reports.append) == 0
        report = json.loads(reports[0])
        assert report["status"] == "PASSED"
        assert report["mode"].startswith(("offline", "offline_fixture"))
        assert report["evidence_inputs"]
        assert report["artifacts_dir"] is None
        assert "click" not in " ".join(report["side_effects"]).lower()
        assert "game" not in " ".join(report["side_effects"]).lower()

    e2e = army_queue_e2e.run_check()
    assert e2e["result"]["simulated_finish_status"] == "FINISHED"
    assert e2e["result"]["simulated_click_count"] == 1
    assert e2e["side_effects"] == ["in_memory_speedup_dialog_simulation", "in_memory_task_queue_only"]


def test_module_wrappers_reject_arguments_without_running_checks():
    calls = []
    wrappers = (
        (speedup_module, "planner", lambda *_: calls.append("speedup")),
        (army_module, "snapshot_reader", lambda *_args, **_kwargs: calls.append("army")),
        (queue_module, "selector", lambda *_args, **_kwargs: calls.append("queue")),
        (army_queue_e2e, "reconcile", lambda *_args, **_kwargs: calls.append("e2e")),
    )
    for wrapper, dependency, replacement in wrappers:
        setattr(wrapper, dependency, replacement)
        reports = []
        assert wrapper.main(["--execute"], reports.append) == 2
        assert json.loads(reports[0])["status"] == "BLOCKED_ARGUMENTS"
    assert calls == []


def test_wrappers_fail_closed_when_injected_check_is_unavailable():
    def fail(*_args, **_kwargs):
        raise RuntimeError("injected offline failure")

    assert speedup_module.run_check(fail)["status"] == "FAILED"
    assert army_module.run_check(fail)["status"] == "FAILED"
    assert queue_module.run_check(fail)["status"] == "FAILED"
    assert army_queue_e2e.run_check(reconcile=fail)["status"] == "FAILED"
    assert army_queue_e2e.run_check(speedup_finisher=fail)["status"] == "FAILED"


def test_army_wrapper_fails_when_fixture_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(army_module, "FIXTURE", tmp_path / "missing.png")
    report = army_module.run_check()
    assert report["status"] == "FAILED"
    assert "fixture_unreadable" in report["error"]