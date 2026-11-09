

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
    items = dt.resolve_selection([], dt.load_scenarios())

    assert 1 <= len(items) <= dt.MAX_SCENARIOS


def test_speedup_scenarios_use_the_confirmation_phrases_of_speedup_run():
    from speedup_run import SCAN_CONFIRMATION, USE_CONFIRMATION

    scenarios = dt.load_scenarios()

    assert scenarios["speedup_scan"]["steps"][0]["argv"][-1] == SCAN_CONFIRMATION
    assert scenarios["speedup_use"]["steps"][0]["execute_argv"][-1] == USE_CONFIRMATION
