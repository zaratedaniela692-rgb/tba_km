"""Supervised CLI adapter for the desktop speedup checkpoint runner."""

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2

from speedup_calibration import _capture_primary_monitor, _desktop_size, _emergency_stop, _move_pointer, _scroll_down
from speedup_checkpoint_runner import EXPECTED_FRAME_SIZE, run_checkpoint_speedups
from speedup_reader import configure_tesseract

ROOT_DIR = Path(__file__).resolve().parent
BUTTON_MAP_PATH = ROOT_DIR / "speedup_button_map.json"
SCAN_CONFIRMATION = "SCAN SPEEDUP LIST FROM TOP"
USE_CONFIRMATION = "USE OWNED SPEEDUPS FROM TOP"
EVIDENCE_CAPTURE_INDEXES = (0, 3, 11, 16)  # initial frame and the three checkpoints


class EvidenceCapture:
    """Wraps a capture function: keeps the latest frame and saves the checkpoint frames."""

    def __init__(self, capture_fn, run_dir, indexes=EVIDENCE_CAPTURE_INDEXES):
        self.capture_fn = capture_fn
        self.run_dir = Path(run_dir)
        self.indexes = indexes
        self.latest = None
        self.count = 0
        self.saved = []
        self.errors = []

    def __call__(self):
        captured = self.capture_fn()
        self.latest = captured[0]
        if self.count in self.indexes:
            path = self.run_dir / f"frame_{self.count:03d}.png"
            (self.saved if cv2.imwrite(str(path), self.latest) else self.errors).append(path.name)
        self.count += 1
        return captured


def _create_live_adapters():
    import pyautogui

    pyautogui.FAILSAFE = True

    def click(point):
        pyautogui.click(*point)

    return _capture_primary_monitor, _move_pointer, _scroll_down, click, _emergency_stop, _desktop_size


def run_open_dialog(execute=True, tesseract_cmd=None):
    """Run the checkpoint finisher from an already-open dialog for an approved caller."""
    capture_fn, move_fn, scroll_fn, click_fn, stop_fn, display_size_fn = _create_live_adapters()
    display_size = tuple(map(int, display_size_fn()))
    if display_size != EXPECTED_FRAME_SIZE:
        raise ValueError(f"unsupported_display_size:{display_size}")
    if configure_tesseract(tesseract_cmd) is None:
        raise ValueError("tesseract_not_found")

    button_map = json.loads(BUTTON_MAP_PATH.read_text(encoding="utf-8"))
    template_path = ROOT_DIR / button_map["button_template"]
    button_template = cv2.imread(str(template_path))
    if button_template is None:
        raise ValueError(f"use_button_template_unavailable:{template_path}")
    from speedup_calibration import load_speedup_regions

    return run_checkpoint_speedups(
        capture_fn,
        move_fn,
        scroll_fn,
        click_fn,
        button_map,
        button_template,
        regions=load_speedup_regions(),
        stop_fn=_emergency_stop,
        dry_run=not execute,
    )


def _serialize_plan(plan):
    return asdict(plan) if is_dataclass(plan) else plan


def _block(reason):
    print(json.dumps({"status": "BLOCKED", "reason": reason}, ensure_ascii=False, indent=2))
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scan the open desktop Speed Up dialog and optionally use owned items."
    )
    parser.add_argument("--execute", action="store_true", help="use planned owned items; otherwise only scan and plan")
    parser.add_argument("--confirm", default="", help="exactly confirm the requested live action")
    parser.add_argument("--tesseract", help="path to tesseract.exe when it is not on PATH or the standard install path")
    args = parser.parse_args(argv)
    expected_confirmation = USE_CONFIRMATION if args.execute else SCAN_CONFIRMATION
    if args.confirm != expected_confirmation:
        parser.error(f"this live action requires --confirm \"{expected_confirmation}\"")

    timestamp = datetime.now(timezone.utc).isoformat()
    run_dir = ROOT_DIR / "debug" / "speedup" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    try:
        capture_fn, move_fn, scroll_fn, click_fn, stop_fn, display_size_fn = _create_live_adapters()
        display_size = tuple(map(int, display_size_fn()))
        if display_size != EXPECTED_FRAME_SIZE:
            return _block(f"unsupported_display_size:{display_size}")
        if configure_tesseract(args.tesseract) is None:
            return _block("tesseract_not_found")

        button_map = json.loads(BUTTON_MAP_PATH.read_text(encoding="utf-8"))
        template_path = ROOT_DIR / button_map["button_template"]
        button_template = cv2.imread(str(template_path))
        if button_template is None:
            return _block(f"use_button_template_unavailable:{template_path}")

        from speedup_calibration import load_speedup_regions

        regions = load_speedup_regions()
        run_dir.mkdir(parents=True, exist_ok=False)
        evidence = EvidenceCapture(capture_fn, run_dir)

        result = run_checkpoint_speedups(
            evidence,
            move_fn,
            scroll_fn,
            click_fn,
            button_map,
            button_template,
            regions=regions,
            stop_fn=stop_fn,
            dry_run=not args.execute,
        )
        report = {
            "timestamp": timestamp,
            "mode": "execute" if args.execute else "dry_run",
            "status": result.status,
            "reason": result.reason,
            "remaining_seconds": result.remaining_seconds,
            "inventory": [{"duration_seconds": duration, "quantity": quantity} for duration, quantity in result.inventory],
            "inventory_evidence": list(result.inventory_evidence),
            "plan": _serialize_plan(result.plan),
            "used": [{"duration_seconds": duration, "quantity": quantity} for duration, quantity in result.used],
            "shortfall_seconds": result.shortfall_seconds,
            "replan": _serialize_plan(result.replan),
            "checkpoint_steps": list(result.checkpoint_steps),
            "evidence_frames": evidence.saved,
        }
        if evidence.errors:
            report["evidence_frame_errors"] = evidence.errors
        if result.status in {"BLOCKED", "UNCERTAIN"} and evidence.latest is not None:
            debug_path = run_dir / "uncertain.png"
            if not cv2.imwrite(str(debug_path), evidence.latest):
                report["debug_capture_error"] = "could_not_save_uncertain_frame"
            else:
                report["debug_capture"] = debug_path.name
        report_path = run_dir / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"report_path={report_path}")
        return 0 if result.status in {"PLANNED", "FINISHED", "NOT_ENOUGH"} else 2
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as error:
        return _block(f"speedup_run_failed:{error}")


if __name__ == "__main__":
    sys.exit(main())