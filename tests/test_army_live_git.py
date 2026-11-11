from pathlib import Path
from types import SimpleNamespace

from tools import run_live_test_git as live_git


def _completed(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


def test_pull_latest_reports_checkout_update(monkeypatch, tmp_path):
    responses = iter((_completed(stdout="old\n"), _completed(), _completed(stdout="new\n")))
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return next(responses)

    monkeypatch.setattr(live_git.subprocess, "run", fake_run)
    messages = []

    result = live_git.pull_latest(tmp_path, messages.append)

    assert result == {"status": "updated"}
    assert commands[1] == ["git", "pull", "--ff-only"]
    assert messages == ["Git sync: updated checkout."]


def test_pull_failure_warns_and_allows_caller_to_continue(monkeypatch, tmp_path):
    responses = iter((_completed(stdout="head\n"), _completed(returncode=1), _completed(stdout="head\n")))
    monkeypatch.setattr(live_git.subprocess, "run", lambda *args, **kwargs: next(responses))
    messages = []

    result = live_git.pull_latest(tmp_path, messages.append)

    assert result == {"status": "failed_skipped", "returncode": 1}
    assert messages == ["Warning: git pull failed (exit 1); continuing with current checkout."]


def test_updated_checkout_restart_failure_warns_and_continues(monkeypatch, tmp_path):
    script = tmp_path / "runner.py"
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(live_git, "pull_latest", lambda *_args: {"status": "updated"})
    monkeypatch.setattr(live_git.os, "execv", lambda *_args: (_ for _ in ()).throw(OSError("restart failed")))
    messages = []

    result = live_git.prepare_live_checkout(tmp_path, script, messages.append)

    assert result == {"status": "updated_restart_failed", "error": "OSError"}
    assert messages[-1] == "Warning: wrapper restart failed (OSError); continuing with updated checkout."


def test_failed_report_publish_commits_only_text_files_then_pushes(monkeypatch, tmp_path):
    run_dir = tmp_path / "device_runs" / "device" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text("{}", encoding="utf-8")
    (run_dir / "failure.png").write_bytes(b"image")
    (tmp_path / "unrelated.txt").write_text("keep", encoding="utf-8")
    commands = []
    monkeypatch.setattr(
        live_git,
        "_run_git",
        lambda root, *args: commands.append(args) or _completed(),
    )
    messages = []

    result = live_git.publish_failure_reports(tmp_path, run_dir, messages.append)

    assert result == {
        "status": "pushed",
        "files": ["device_runs/device/run/report.json"],
    }
    assert commands == [
        ("add", "--", "device_runs/device/run/report.json"),
        ("commit", "--only", "-m", "test: publish failed live run reports", "--", "device_runs/device/run/report.json"),
        ("push",),
    ]
    assert messages == ["Failed-run reports committed and pushed."]


def test_report_push_failure_is_reported_without_raising(monkeypatch, tmp_path):
    run_dir = tmp_path / "device_runs" / "device" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text("{}", encoding="utf-8")
    commands = []

    def fake_run(root, *args):
        commands.append(args)
        return _completed(returncode=1 if args == ("push",) else 0)

    monkeypatch.setattr(live_git, "_run_git", fake_run)
    messages = []

    result = live_git.publish_failure_reports(tmp_path, run_dir, messages.append)

    assert result == {"status": "push_failed", "returncode": 1}
    assert commands[-1] == ("push",)
    assert messages == ["Warning: report push failed (exit 1); report commit remains local."]


def test_commit_failure_skips_push(monkeypatch, tmp_path):
    run_dir = tmp_path / "device_runs" / "device" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text("{}", encoding="utf-8")
    commands = []

    def fake_run(root, *args):
        commands.append(args)
        return _completed(returncode=1 if args[0] == "commit" else 0)

    monkeypatch.setattr(live_git, "_run_git", fake_run)
    messages = []

    result = live_git.publish_failure_reports(tmp_path, run_dir, messages.append)

    assert result == {"status": "commit_failed", "returncode": 1}
    assert commands == [
        ("add", "--", "device_runs/device/run/report.json"),
        ("commit", "--only", "-m", "test: publish failed live run reports", "--", "device_runs/device/run/report.json"),
    ]
    assert messages == ["Warning: report commit failed (exit 1); skipping push."]


def test_report_publish_rejects_paths_outside_repository(tmp_path):
    outside = Path(tmp_path.parent) / "outside-run"
    outside.mkdir()
    messages = []

    result = live_git.publish_failure_reports(tmp_path, outside, messages.append)

    assert result == {"status": "skipped_outside_repository"}
    assert messages == ["Warning: failed-run report is outside the repository; Git publishing skipped."]