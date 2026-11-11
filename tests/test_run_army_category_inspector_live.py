import json

import tools.run_army_category_inspector_live as live


def test_live_inspector_writes_read_only_report(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    monkeypatch.setattr(live, "GIT_SYNC_RESULT", {"status": "up_to_date"})
    monkeypatch.setattr(live, "resolve_variant", lambda: {"id": "legacy"})
    monkeypatch.setattr(live, "inspect_image", lambda frame, expected_unit_type, variant: {
        "status": "INSPECTED_READ_ONLY", "actions_executed": False,
        "queue_modified": False, "category": {"unit_type": "specialists"},
    })
    captures = []

    def capture():
        captures.append(True)
        return type("Frame", (), {"shape": (1080, 1920, 3)})(), (0, 0)

    def create_run_dir():
        run_dir.mkdir()
        return run_dir

    result = live.run_live_inspection(
        capture_fn=capture,
        run_dir_factory=create_run_dir,
        output=lambda _: None,
    )

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert result == 0
    assert len(captures) == 1
    assert report["status"] == "INSPECTED_READ_ONLY"
    assert report["actions_executed"] is False
    assert report["queue_modified"] is False
    assert report["git_sync"]["status"] == "up_to_date"


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
    )

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert result == 2
    assert len(captures) == 1
    assert report["status"] == "BLOCKED_CAPTURE"
    assert report["reason"].startswith("inspection_failed:OSError")
    assert report["actions_executed"] is False
    assert published == [run_dir]