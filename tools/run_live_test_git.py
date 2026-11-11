"""Best-effort Git synchronization and failed-report publishing for live tests."""

import os
import subprocess
import sys
from pathlib import Path


REPORT_SUFFIXES = {".json", ".jsonl", ".txt"}
RESTART_MARKER = "TBA_LIVE_TEST_SYNC_RESTART"


def _run_git(repo_root, *arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def pull_latest(repo_root, output=print):
    """Pull fast-forward updates; report failures without blocking the test."""
    try:
        before = _run_git(repo_root, "rev-parse", "HEAD")
        pulled = _run_git(repo_root, "pull", "--ff-only")
        after = _run_git(repo_root, "rev-parse", "HEAD")
    except (OSError, subprocess.TimeoutExpired) as error:
        output(f"Warning: Git sync skipped ({type(error).__name__}); continuing with current checkout.")
        return {"status": "failed_skipped", "error": type(error).__name__}

    if pulled.returncode:
        output(f"Warning: git pull failed (exit {pulled.returncode}); continuing with current checkout.")
        return {"status": "failed_skipped", "returncode": pulled.returncode}

    if before.returncode == 0 and after.returncode == 0:
        updated = before.stdout.strip() != after.stdout.strip()
        status = "updated" if updated else "up_to_date"
    else:
        status = "up_to_date"
    output("Git sync: updated checkout." if status == "updated" else "Git sync: checkout is current.")
    return {"status": status}


def prepare_live_checkout(repo_root, script_path, output=print):
    """Pull before live imports and restart once if the checked-out code changed."""
    script_path = Path(script_path).resolve()
    if os.environ.get(RESTART_MARKER) == str(script_path):
        os.environ.pop(RESTART_MARKER, None)
        return {"status": "updated"}

    result = pull_latest(repo_root, output)
    if result["status"] == "updated":
        os.environ[RESTART_MARKER] = str(script_path)
        output("Restarting live test wrapper to load the updated code.")
        try:
            os.execv(sys.executable, [sys.executable, str(script_path), *sys.argv[1:]])
        except OSError as error:
            os.environ.pop(RESTART_MARKER, None)
            output(f"Warning: wrapper restart failed ({type(error).__name__}); continuing with updated checkout.")
            return {"status": "updated_restart_failed", "error": type(error).__name__}
    return result


def publish_failure_reports(repo_root, run_dir, output=print):
    """Commit and push only textual reports from this failed run directory."""
    repo_root = Path(repo_root).resolve()
    run_dir = Path(run_dir).resolve()
    try:
        relative_run_dir = run_dir.relative_to(repo_root)
    except ValueError:
        output("Warning: failed-run report is outside the repository; Git publishing skipped.")
        return {"status": "skipped_outside_repository"}

    report_files = sorted(
        path for path in run_dir.iterdir()
        if path.is_file() and path.suffix.lower() in REPORT_SUFFIXES
    )
    if not report_files:
        output("Warning: no textual reports found; Git publishing skipped.")
        return {"status": "skipped_no_reports"}

    relative_files = [
        (relative_run_dir / path.name).as_posix()
        for path in report_files
    ]
    try:
        added = _run_git(repo_root, "add", "--", *relative_files)
    except (OSError, subprocess.TimeoutExpired) as error:
        output(f"Warning: report staging failed ({type(error).__name__}); skipping commit and push.")
        return {"status": "stage_failed", "error": type(error).__name__}
    if added.returncode:
        output(f"Warning: report staging failed (exit {added.returncode}); skipping commit and push.")
        return {"status": "stage_failed", "returncode": added.returncode}

    try:
        committed = _run_git(
            repo_root, "commit", "--only", "-m", "test: publish failed live run reports", "--", *relative_files,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        output(f"Warning: report commit failed ({type(error).__name__}); skipping push.")
        return {"status": "commit_failed", "error": type(error).__name__}
    if committed.returncode:
        output(f"Warning: report commit failed (exit {committed.returncode}); skipping push.")
        return {"status": "commit_failed", "returncode": committed.returncode}

    try:
        pushed = _run_git(repo_root, "push")
    except (OSError, subprocess.TimeoutExpired) as error:
        output(f"Warning: report push failed ({type(error).__name__}); report commit remains local.")
        return {"status": "push_failed", "error": type(error).__name__}
    if pushed.returncode:
        output(f"Warning: report push failed (exit {pushed.returncode}); report commit remains local.")
        return {"status": "push_failed", "returncode": pushed.returncode}

    output("Failed-run reports committed and pushed.")
    return {"status": "pushed", "files": relative_files}