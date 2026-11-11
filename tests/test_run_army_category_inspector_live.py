import json

import cv2
import numpy as np

import army_training_navigation as navigation
import tools.run_army_category_inspector_live as live

ROOT = live.ROOT_DIR


def _route():
    return {"status": "routed", "client_id": "desktop", "profile_id": "player_12345"}


def test_live_inspector_writes_read_only_report(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    monkeypatch.setattr(live, "GIT_SYNC_RESULT", {"status": "up_to_date"})
    monkeypatch.setattr(live, "inspect_image", lambda frame, expected_unit_type, variant: {
        "status": "INSPECTED_READ_ONLY", "actions_executed": False,
        "queue_modified": False, "category": {"unit_type": "specialists"},
    })
    captures = []
    image = cv2.imread(str(ROOT / "screenshots" / "army_training" / "specialist_view.png"))

    def capture():
        captures.append(True)
        return image.copy(), (0, 0)

    def create_run_dir():
        run_dir.mkdir()
        return run_dir

    result = live.run_live_inspection(
        capture_fn=capture,
        run_dir_factory=create_run_dir,
        output=lambda _: None,
        route_fn=lambda **kwargs: _route(),
    )

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert result == 0
    assert len(captures) == 1
    assert report["status"] == "INSPECTED_READ_ONLY"
    assert report["actions_executed"] is False
    assert report["queue_modified"] is False
    assert report["git_sync"]["status"] == "up_to_date"
    assert report["navigation"]["status"] == "SKIPPED_ALREADY_OPEN"
    assert report["route"]["profile_id"] == "player_12345"


def test_capture_failure_is_reported_and_published_without_retry(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    captures = []
    published = []

    def capture():
        captures.append(True)
        raise OSError("capture unavailable")

    def create_run_dir():
        run_dir.mkdir()
        return run_dir

    monkeypatch.setattr(live, "publish_failure_reports", lambda root, path, output: published.append(path))
    result = live.run_live_inspection(
        capture_fn=capture,
        run_dir_factory=create_run_dir,
        output=lambda _: None,
        route_fn=lambda **kwargs: _route(),
    )

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert result == 2
    assert len(captures) == 1
    assert report["status"] == "BLOCKED_INITIAL_CAPTURE"
    assert "capture unavailable" in report["reason"]
    assert report["actions_executed"] is False
    assert published == [run_dir]


def test_live_inspector_navigates_once_when_barracks_is_not_visible(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    world_map = np.zeros((1080, 1920, 3), dtype=np.uint8)
    barracks = cv2.imread(str(ROOT / "screenshots" / "army_training" / "specialist_view.png"))
    frames = iter(((world_map, (0, 0)), (barracks, (0, 0))))
    navigation_calls = []
    inspected = []
    monkeypatch.setattr(live, "inspect_image", lambda frame, expected_unit_type, variant: inspected.append(frame) or {
        "status": "INSPECTED_READ_ONLY", "actions_executed": False,
        "queue_modified": False, "category": {"unit_type": "specialists"},
    })

    def create_run_dir():
        run_dir.mkdir()
        return run_dir

    def ensure(**kwargs):
        kwargs["navigate_fn"] = lambda **nav_kwargs: navigation_calls.append(nav_kwargs) or {
            "status": "BARRACKS_OPENED", "actions_executed": True, "visible_slots": 3,
        }
        return navigation.ensure_army_training_screen(**kwargs)

    result = live.run_live_inspection(
        capture_fn=lambda: next(frames),
        run_dir_factory=create_run_dir,
        output=lambda _: None,
        route_fn=lambda **kwargs: _route(),
        ensure_fn=ensure,
    )

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert result == 0
    assert report["status"] == "INSPECTED_READ_ONLY"
    assert report["actions_executed"] is True
    assert report["queue_modified"] is False
    assert report["navigation"]["status"] == "BARRACKS_OPENED"
    assert len(navigation_calls) == 1
    assert navigation_calls[0]["execute"] is True
    assert len(inspected) == 1
    assert inspected[0] is barracks or (inspected[0] == barracks).all()


def test_unresolved_profile_blocks_inspector_navigation(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    navigation_calls = []

    def create_run_dir():
        run_dir.mkdir()
        return run_dir

    result = live.run_live_inspection(
        capture_fn=lambda: (_ for _ in ()).throw(AssertionError("capture must not run")),
        run_dir_factory=create_run_dir,
        output=lambda _: None,
        route_fn=lambda **kwargs: {"status": "blocked", "client_id": "desktop", "profile_id": None},
        ensure_fn=lambda **kwargs: navigation_calls.append(kwargs),
    )

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert result == 2
    assert report["status"] == "BLOCKED_ROUTE"
    assert report["actions_executed"] is False
    assert navigation_calls == []