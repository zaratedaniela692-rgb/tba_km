import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_import_does_not_parse_arguments_or_start_automation():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import crypt; print('crypt import completed')",
            "--not-a-crypt-option",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "crypt import completed"


def test_crypt_types_are_available_without_running_cli():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import crypt; assert crypt.common_crypts; assert crypt.rare_crypts; assert crypt.epic_crypts",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_help_does_not_require_live_automation_dependencies():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "crypt.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--min-progress" in completed.stdout