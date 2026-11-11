import json
from types import SimpleNamespace

import pytest

from tools import run_army_navigation_live as wrapper


def _route(status="routed", client_id="desktop", profile_id="player_12345"):
    return SimpleNamespace(
        status=status,
        client_id=client_id,
        player_name="Player",
        profile_id=profile_id,
        queue_path="ignored-queue-path",
        reason="profile_reused",
        window_title="Total Battle",
        process_name="TotalBattle.exe",
    )


def test_live_navigation_wrapper_runs_once_and_reports_confirmed_slots(tmp_path):
    calls = []
    outputs = []

    def navigate(execute):
        calls.append((execute, wrapper.os.environ.get("TBA_PROFILE_ID")))
        return {"status": "BARRACKS_OPENED", "actions_executed": True, "visible_slots": 3}

    result = wrapper.run_live_navigation(
        route_fn=lambda: _route(),
        navigate_fn=navigate,
        run_dir_factory=lambda: tmp_path,
        output=outputs.append,
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert result == 0
    assert calls == [(True, "player_12345")]
    assert report["status"] == "BARRACKS_OPENED"
    assert report["queue_modified"] is False
    assert report["route"]["player_name"] == "Player"
    assert report["report_file"].endswith("report.json")
    assert outputs


@pytest.mark.parametrize(
    "route",
    (_route(status="blocked"), _route(client_id="browser"), _route(profile_id=None)),
)
def test_unresolved_or_unsupported_route_stops_before_navigation(tmp_path, route, monkeypatch):
    navigation_calls = []
    published = []
    monkeypatch.setattr(
        wrapper,
        "publish_failure_reports",
        lambda root, run_dir, output: published.append((root, run_dir)),
    )

    result = wrapper.run_live_navigation(
        route_fn=lambda: route,
        navigate_fn=lambda **kwargs: navigation_calls.append(kwargs),
        run_dir_factory=lambda: tmp_path,
        output=lambda _text: None,
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert result == 2
    assert navigation_calls == []
    assert report["status"] == "BLOCKED_ROUTE"
    assert report["actions_executed"] is False
    assert report["queue_modified"] is False
    assert published == [(wrapper.ROOT_DIR, tmp_path)]


def test_unconfirmed_navigation_is_reported_without_retry(tmp_path):
    calls = []

    def navigate(execute):
        calls.append(execute)
        return {"status": "UNKNOWN_AFTER_ARMY_CLICK_ATTEMPT", "actions_executed": True}

    result = wrapper.run_live_navigation(
        route_fn=lambda: _route(),
        navigate_fn=navigate,
        run_dir_factory=lambda: tmp_path,
        output=lambda _text: None,
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert result == 2
    assert calls == [True]
    assert report["status"] == "UNKNOWN_AFTER_ARMY_CLICK_ATTEMPT"
    assert "do_not_retry" in report["reason"]


def test_navigation_exception_saves_one_failure_screen_without_checkpoint(tmp_path, monkeypatch):
    captures = []
    monkeypatch.setattr(
        wrapper,
        "_save_failure_screen",
        lambda run_dir: captures.append(run_dir) or {"file": "failure.png", "status": "saved"},
    )

    result = wrapper.run_live_navigation(
        route_fn=lambda: _route(),
        navigate_fn=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("navigation failed")),
        run_dir_factory=lambda: tmp_path,
        output=lambda _text: None,
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert result == 2
    assert captures == [tmp_path]
    assert report["failure_screen"] == {"file": "failure.png", "status": "saved"}
    assert report["actions_executed"] == "unknown"


def test_navigation_exception_does_not_duplicate_checkpoint_screenshot(tmp_path, monkeypatch):
    (tmp_path / "checkpoint_01_armia_click.png").write_bytes(b"checkpoint")
    captures = []
    monkeypatch.setattr(
        wrapper,
        "_save_failure_screen",
        lambda run_dir: captures.append(run_dir) or {"file": "failure.png", "status": "saved"},
    )

    result = wrapper.run_live_navigation(
        route_fn=lambda: _route(),
        navigate_fn=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("navigation failed")),
        run_dir_factory=lambda: tmp_path,
        output=lambda _text: None,
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert result == 2
    assert captures == []
    assert "failure_screen" not in report


def test_wrapper_rejects_runtime_arguments(monkeypatch, capsys):
    monkeypatch.setattr(wrapper, "run_live_navigation", lambda: pytest.fail("must not run with arguments"))

    assert wrapper.main(["--execute"]) == 2
    assert "takes no arguments" in capsys.readouterr().err