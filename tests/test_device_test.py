import subprocess
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tools import device_test as dt

START = datetime(2026, 11, 7, 12, 0, 0)


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(work)], check=True, capture_output=True)
    _git(work, "checkout", "-b", "main")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("x\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "init")
    _git(work, "push", "-u", "origin", "main")
    return SimpleNamespace(work=work, remote=remote)


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now


CLOCK = Clock()


def _context(repo, calls, execute=False, git=True, **kwargs):
    def fake_run(argv, **_):
        calls.append(argv)
        if kwargs.get("effect"):
            kwargs["effect"]()
        return SimpleNamespace(returncode=kwargs.get("returncode", 0), stdout="out", stderr="")

    return dt.Context(
        root=repo.work, device="pc1", execute=execute, delay=0,
        git=dt.Git(repo.work) if git else None, sleep_fn=lambda _: None, now_fn=CLOCK,
        run_fn=fake_run, screenshot_fn=lambda _: None, stop_fn=lambda: None, out=lambda _: None,
    )


SCENARIO = {
    "name": "demo", "description": "d", "prepare": "p",
    "steps": [{"name": "probe", "argv": ["{python}", "probe.py", "--out", "{run_dir}", "{profile}"]}],
}
CLICKING = {
    "name": "clicky", "description": "d", "prepare": "p",
    "steps": [{"name": "use", "execute_argv": ["{python}", "use.py", "--execute"]}],
}


def test_registry_is_valid_and_clicking_steps_have_a_safe_default():
    scenarios = dt.load_scenarios()

    assert {"preflight", "army_slots", "army_scroll", "army_specialist_train", "speedup_scan", "speedup_use"} <= set(scenarios)
    assert set(scenarios["speedup_use"]["steps"][0]) == {"name", "execute_argv"}
    assert "argv" in scenarios["army_navigate"]["steps"][0]
    specialist_step = scenarios["army_specialist_train"]["steps"][0]
    assert specialist_step["argv"][-4:] == ["--level", "5", "--match", "1"]
    assert specialist_step["execute_argv"][-2:] == ["--confirm", "TRAIN ONE SPECIALIST"]
    assert "--execute" in specialist_step["execute_argv"]
    assert "--execute" not in specialist_step["argv"]


def test_bad_placeholder_is_rejected(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(
        '{"scenarios":[{"name":"a","description":"d","prepare":"p","steps":[{"name":"s","argv":["{nope}"]}]}]}',
        encoding="utf-8",
    )

    with pytest.raises(dt.DeviceTestError):
        dt.load_scenarios(path)


def test_clicking_scenario_without_execute_is_skipped_without_running_anything(repo):
    calls = []

    code, results = dt.run_scenarios(["clicky"], _context(repo, calls), {"clicky": CLICKING})

    assert code == 0
    assert results == [{"scenario": "clicky", "status": dt.SKIPPED}]
    assert calls == []


def test_execute_selects_the_clicking_command(repo):
    calls = []

    dt.run_scenarios(["clicky"], _context(repo, calls, execute=True), {"clicky": CLICKING})

    assert [call[1:] for call in calls] == [["use.py", "--execute"]]


def test_run_writes_evidence_commits_only_its_directory_and_pushes(repo):
    calls = []
    messages = []

    def stage_unrelated_file():
        (repo.work / "other.txt").write_text("staged\n", encoding="utf-8")
        _git(repo.work, "add", "other.txt")

    context = _context(repo, calls, effect=stage_unrelated_file)
    context.out = messages.append

    code, results = dt.run_scenarios(["demo"], context, {"demo": SCENARIO})

    assert code == 0
    run_dirs = list((repo.work / "device_runs" / "pc1" / "demo").iterdir())
    assert len(run_dirs) == 1
    assert run_dirs[0].name.startswith("1_")
    assert (run_dirs[0] / "report.json").exists() and (run_dirs[0] / "log.txt").exists()
    report = __import__("json").loads((run_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["run_dir"] == str(run_dirs[0].resolve())
    assert any(report["run_dir"] in message for message in messages)
    assert calls[0][-1] == "device_test" and str(run_dirs[0]) in calls[0]
    assert _git(repo.work, "log", "-1", "--format=%s") == "device_runs: demo on pc1 - OK"
    assert "other.txt" not in _git(repo.work, "show", "--name-only", "--format=", "HEAD")
    assert _git(repo.work, "diff", "--cached", "--name-only") == "other.txt"
    assert _git(repo.remote, "log", "-1", "--format=%s", "main") == "device_runs: demo on pc1 - OK"
    assert results[-1]["scenario"] == "git_push" and results[-1]["status"] == dt.OK


def test_run_log_includes_module_event_trace(repo):
    def create_module_trace():
        module_run = repo.work / "debug" / "speedup" / "run_fixture"
        module_run.mkdir(parents=True)
        (module_run / "report.json").write_text(
            '{"timestamp":"2026-11-07T12:00:03+00:00"}', encoding="utf-8",
        )
        (module_run / "event_trace.jsonl").write_text(
            '{"elapsed_ms":125.0,"event":"plan_choice","step":16,"data":{"selected_duration_seconds":3600}}\n'
            '{"elapsed_ms":250.0,"event":"use_click","step":3,"data":{"use_number":1,"screen_point":[1122,529]}}\n',
            encoding="utf-8",
        )

    context = _context(repo, [], effect=create_module_trace)
    scenario = {**SCENARIO, "debug_dirs": ["debug/speedup"]}

    code, results = dt.run_scenarios(["demo"], context, {"demo": scenario})

    run_dir = next((repo.work / "device_runs" / "pc1" / "demo").iterdir())
    log = (run_dir / "log.txt").read_text(encoding="utf-8")
    report = __import__("json").loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert code == 0
    assert results[0]["status"] == dt.OK
    assert "plan_choice" in log and '"selected_duration_seconds":3600' in log
    assert "use_click" in log and '"screen_point":[1122,529]' in log
    assert log.index("use_click") < log.index("step 1 probe: OK")
    assert report["module_trace_events"] == 2
    assert (run_dir / "module_debug" / "speedup" / "run_fixture" / "event_trace.jsonl").exists()


def test_retention_keeps_the_current_run_and_three_earlier_ones(repo):
    context = _context(repo, [])
    context.push = False
    context.force = True
    for _ in range(6):
        dt.run_scenarios(["demo"], context, {"demo": SCENARIO})

    scenario_dir = repo.work / "device_runs" / "pc1" / "demo"
    on_disk = sorted(path.name for path in scenario_dir.iterdir())
    tracked = _git(repo.work, "ls-files", "device_runs/pc1/demo").splitlines()

    assert len(on_disk) == dt.KEEP_RUNS
    assert {line.split("/")[3] for line in tracked} == set(on_disk)
    assert {path.name.split("_", 1)[0] for path in scenario_dir.iterdir()} == {"3", "4", "5", "6"}


def test_run_counter_continues_after_legacy_timestamp_folders(tmp_path):
    scenario_dir = tmp_path / "device_runs" / "pc1" / "speedup_scan"
    scenario_dir.mkdir(parents=True)
    (scenario_dir / "20261106_120000").mkdir()
    (scenario_dir / "20261107_120000").mkdir()

    first_number, first_path = dt._create_run_directory(scenario_dir, START)
    second_number, second_path = dt._create_run_directory(scenario_dir, START)

    assert first_number == 3
    assert first_path.name == "3_20261107_120000"
    assert second_number == 4
    assert second_path.name == "4_20261107_120000"


def test_retention_uses_timestamp_not_lexical_run_number(tmp_path):
    scenario_dir = tmp_path / "runs"
    scenario_dir.mkdir()
    for run_number in range(1, 13):
        (scenario_dir / f"{run_number}_20261107_{run_number:06d}").mkdir()

    removed = dt.prune_old_runs(scenario_dir)

    assert len(removed) == 8
    assert {path.name for path in scenario_dir.iterdir()} == {
        f"{run_number}_20261107_{run_number:06d}" for run_number in range(9, 13)
    }


def test_previous_code_commit_uses_latest_numbered_run(tmp_path):
    scenario_dir = tmp_path / "runs"
    earlier = scenario_dir / "9_20261107_000009"
    latest = scenario_dir / "10_20261107_000010"
    earlier.mkdir(parents=True)
    latest.mkdir()
    (earlier / "report.json").write_text('{"code_commit":"old"}', encoding="utf-8")
    (latest / "report.json").write_text('{"code_commit":"new"}', encoding="utf-8")

    assert dt.previous_code_commit(scenario_dir) == "new"


def test_tracked_changes_skip_pull_but_still_run_on_current_checkout(repo):
    calls = []
    (repo.work / "README.md").write_text("changed\n", encoding="utf-8")

    code, results = dt.run_scenarios(["demo"], _context(repo, calls), {"demo": SCENARIO})

    assert code == 0 and results[0]["status"] == dt.OK
    assert len(calls) == 1
    assert _git(repo.work, "diff", "--", "README.md")
    assert _git(repo.remote, "log", "-1", "--format=%s", "main") == "device_runs: demo on pc1 - OK"


def test_pull_failure_warns_but_does_not_block_scenario(repo, monkeypatch):
    calls = []
    messages = []
    context = _context(repo, calls)
    context.out = messages.append
    monkeypatch.setattr(dt, "sync_repository", lambda _git: (False, "pull_failed; using_current_checkout: network down"))

    code, results = dt.run_scenarios(["demo"], context, {"demo": SCENARIO})

    assert code == 0 and results[0]["status"] == dt.OK
    assert len(calls) == 1
    assert any("WARNING: git sync skipped" in message for message in messages)


def test_git_commands_are_noninteractive_and_time_bounded(tmp_path):
    observed = {}

    def runner(args, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    code, output = dt.Git(tmp_path, runner=runner).run("status")

    assert (code, output) == (0, "ok")
    assert observed["timeout"] == dt.GIT_TIMEOUT_SECONDS
    assert observed["stdin"] is subprocess.DEVNULL
    assert observed["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_git_timeout_returns_instead_of_waiting(tmp_path):
    def runner(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("git pull", dt.GIT_TIMEOUT_SECONDS)

    code, output = dt.Git(tmp_path, runner=runner).run("pull", "--ff-only")

    assert code == 124
    assert "timed out" in output


def test_failed_step_stops_the_sequence_and_is_still_published(repo):
    calls = []
    scenario = {
        **SCENARIO, "steps": [
            {"name": "first", "argv": ["a"]}, {"name": "second", "argv": ["b"]},
        ],
    }
    context = _context(repo, calls, returncode=3)
    context.push = False

    code, results = dt.run_scenarios(["demo"], context, {"demo": scenario})

    assert code == 1 and results[0]["status"] == dt.FAILED
    assert calls == [["a"]]
    assert _git(repo.work, "log", "-1", "--format=%s") == "device_runs: demo on pc1 - FAILED"


def test_failed_run_is_pushed_by_default(repo):
    calls = []
    code, results = dt.run_scenarios(
        ["demo"], _context(repo, calls, returncode=4), {"demo": SCENARIO},
    )

    assert code == 1
    assert results[0]["status"] == dt.FAILED
    assert results[-1]["scenario"] == "git_push"
    assert results[-1]["status"] == dt.OK
    assert _git(repo.remote, "log", "-1", "--format=%s", "main") == "device_runs: demo on pc1 - FAILED"


def test_module_debug_created_during_the_run_is_moved_into_it(repo):
    base = repo.work / "debug" / "mod"
    (base / "old").mkdir(parents=True)
    scenario = {**SCENARIO, "debug_dirs": ["debug/mod"]}
    context = _context(repo, [], git=False, effect=lambda: (base / "new_run").mkdir())

    _, results = dt.run_scenarios(["demo"], context, {"demo": scenario})

    assert results[0]["module_debug"] == ["debug/mod/new_run"]
    assert (base / "old").is_dir() and not (base / "new_run").exists()


def test_emergency_stop_blocks_the_step(repo):
    calls = []
    context = _context(repo, calls, git=False)
    context.stop_fn = lambda: (_ for _ in ()).throw(RuntimeError("stop"))

    _, results = dt.run_scenarios(["demo"], context, {"demo": SCENARIO})

    assert results[0]["status"] == dt.BLOCKED and calls == []


def test_same_code_as_the_previous_run_is_not_published_without_force(repo):
    calls = []
    context = _context(repo, calls)
    dt.run_scenarios(["demo"], context, {"demo": SCENARIO})
    published = _git(repo.work, "rev-parse", "HEAD")

    code, results = dt.run_scenarios(["demo"], _context(repo, calls), {"demo": SCENARIO})

    assert code == 3 and results == [
        {"scenario": "demo", "status": dt.UNCHANGED, "detail": _git(repo.work, "log", "-1", "--format=%H", "--", ".", ":(exclude)device_runs")},
    ]
    assert len(calls) == 1
    assert _git(repo.work, "rev-parse", "HEAD") == published


def test_force_runs_again_on_the_same_code(repo):
    calls = []
    dt.run_scenarios(["demo"], _context(repo, calls), {"demo": SCENARIO})
    forced = _context(repo, calls)
    forced.force = True

    code, results = dt.run_scenarios(["demo"], forced, {"demo": SCENARIO})

    assert code == 0 and results[0]["status"] == dt.OK
    assert len(calls) == 2


def test_new_code_commit_allows_the_next_run(repo):
    calls = []
    dt.run_scenarios(["demo"], _context(repo, calls), {"demo": SCENARIO})
    (repo.work / "feature.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo.work, "add", "feature.py")
    _git(repo.work, "commit", "-m", "feature")

    code, results = dt.run_scenarios(["demo"], _context(repo, calls), {"demo": SCENARIO})

    assert code == 0 and results[0]["status"] == dt.OK
    assert len(calls) == 2


def test_guard_is_per_scenario(repo):
    calls = []
    other = {**SCENARIO, "name": "other"}
    scenarios = {"demo": SCENARIO, "other": other}
    dt.run_scenarios(["demo"], _context(repo, calls), scenarios)

    code, results = dt.run_scenarios(["other"], _context(repo, calls), scenarios)

    assert code == 0 and results[0]["status"] == dt.OK


def test_plan_selects_scenarios_and_marks_clicking_entries(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text('{"scenarios": ["demo", {"name": "clicky", "execute": true}]}', encoding="utf-8")
    scenarios = {"demo": SCENARIO, "clicky": CLICKING}

    assert dt.resolve_selection([], scenarios, plan) == [("demo", False), ("clicky", True)]
    assert dt.resolve_selection(["demo"], scenarios, plan, execute=True) == [("demo", True)]


def test_more_than_two_scenarios_need_an_explicit_override(tmp_path):
    scenarios = {name: {**SCENARIO, "name": name} for name in ("a", "b", "c")}
    plan = tmp_path / "plan.json"
    plan.write_text('{"scenarios": ["a", "b", "c"]}', encoding="utf-8")

    with pytest.raises(dt.DeviceTestError, match="--allow-many"):
        dt.resolve_selection([], scenarios, plan)
    assert len(dt.resolve_selection([], scenarios, plan, allow_many=True)) == 3
    with pytest.raises(dt.DeviceTestError):
        dt.resolve_selection(["all"], scenarios, plan)


def test_committed_plan_is_valid_and_within_the_limit():
    items = dt.resolve_selection([], dt.load_scenarios(), dt.SETTINGS_PATH)

    assert 1 <= len(items) <= dt.MAX_SCENARIOS
    assert items == [("preflight", False), ("speedup_use", True)]


def test_settings_default_to_publish_push_rerun_and_preparation_delay():
    settings = dt.load_settings()

    assert settings["delay_seconds"] == 5
    assert settings["publish"] is True
    assert settings["push"] is True
    assert settings["rerun_same_code"] is True


def test_settings_reject_invalid_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"scenarios":["demo"],"delay_seconds":-1}', encoding="utf-8")

    with pytest.raises(dt.DeviceTestError, match="delay_seconds"):
        dt.load_settings(path)

    path.write_text('{"scenarios":["demo"],"delay_seconds":6}', encoding="utf-8")
    with pytest.raises(dt.DeviceTestError, match="delay_seconds"):
        dt.load_settings(path)


def test_speedup_scenarios_use_the_confirmation_phrases_of_speedup_run():
    from speedup_run import SCAN_CONFIRMATION, USE_CONFIRMATION

    scenarios = dt.load_scenarios()

    assert scenarios["speedup_scan"]["steps"][0]["argv"][-1] == SCAN_CONFIRMATION
    assert scenarios["speedup_use"]["steps"][0]["execute_argv"][-1] == USE_CONFIRMATION
