#!/usr/bin/env python3
"""Live probes of the game window used by device_test scenarios; they never click."""

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

EXPECTED_SIZE = (1920, 1080)
STOP_FILE = Path.home() / ".tba_stop"
DEFAULT_BATCHES = 6


def _capture():
    import cv2
    import mss
    import numpy as np

    with mss.mss() as grabber:
        monitor = grabber.monitors[1]
        frame = np.asarray(grabber.grab(monitor))
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR), (int(monitor["left"]), int(monitor["top"]))


def _save(path, frame):
    import cv2

    if not cv2.imwrite(str(path), frame):
        raise OSError(f"cannot save {path}")


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _json_default(value):
    return asdict(value) if is_dataclass(value) else str(value)


def _stop_check():
    if STOP_FILE.exists():
        raise RuntimeError(f"Emergency stop file exists: {STOP_FILE}")


def _library_versions():
    versions = {}
    for name in ("cv2", "numpy", "pytesseract", "pyautogui", "mss"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", "installed")
        except Exception as error:
            versions[name] = f"MISSING: {error}"
    return versions


def preflight(out_dir, _args):
    report = {"libraries": _library_versions()}
    try:
        import pyautogui

        report["display_size"] = list(map(int, pyautogui.size()))
    except Exception as error:
        report["display_size"] = f"ERROR: {error}"
    try:
        from speedup_reader import configure_tesseract

        report["tesseract"] = configure_tesseract()
    except Exception as error:
        report["tesseract"] = f"ERROR: {error}"
    try:
        frame, origin = _capture()
        _save(out_dir / "monitor.png", frame)
        report["capture_size"] = [frame.shape[1], frame.shape[0]]
        report["monitor_origin"] = list(origin)
    except Exception as error:
        report["capture_size"] = f"ERROR: {error}"
    problems = [name for name, value in report["libraries"].items() if str(value).startswith("MISSING")]
    if report.get("tesseract") in (None, "") or str(report.get("tesseract")).startswith("ERROR"):
        problems.append("tesseract")
    if report.get("capture_size") != list(EXPECTED_SIZE):
        problems.append("capture_size")
    if report.get("display_size") != list(EXPECTED_SIZE):
        problems.append("display_size")
    report["problems"] = problems
    _write_json(out_dir / "preflight.json", report)
    return 0 if not problems else 2, report


def _barracks_readings(frame):
    from army_training_levels import read_slot_selector_levels
    from army_training_scanner import _load_regions
    from army_training_slot_reader import read_slot_readings
    from army_training_slots import STATUS_OK, locate_slots
    from ui_variants import resolve_variant

    variant = resolve_variant()
    regions = _load_regions(variant["regions"])["army_training"]
    layout = locate_slots(frame, regions, variant)
    summary = {"layout_status": layout.status, "layout_reason": layout.reason, "slots": []}
    if layout.status != STATUS_OK:
        return summary, layout, variant
    for slot in layout.slots:
        entry = {"index": slot.index, "row": slot.row, "column": slot.column, "dx": slot.dx, "dy": slot.dy}
        for key, reader in (("selector", read_slot_selector_levels), ("readings", read_slot_readings)):
            try:
                entry[key] = reader(frame, slot)
            except Exception as error:
                entry[key] = f"ERROR: {type(error).__name__}: {error}"
        summary["slots"].append(entry)
    return summary, layout, variant


def army_slots(out_dir, _args):
    frame, _ = _capture()
    _save(out_dir / "barracks.png", frame)
    if (frame.shape[1], frame.shape[0]) != EXPECTED_SIZE:
        report = {"error": f"unexpected_frame_size:{(frame.shape[1], frame.shape[0])}"}
        _write_json(out_dir / "army_slots.json", report)
        return 2, report
    summary, _, variant = _barracks_readings(frame)
    try:
        from army_training_scanner import read_army_training_snapshot_from_image

        summary["training_state"] = read_army_training_snapshot_from_image(frame, variant=variant)
    except Exception as error:
        summary["training_state"] = f"ERROR: {type(error).__name__}: {error}"
    _write_json(out_dir / "army_slots.json", summary)
    return (0 if summary["layout_status"] == "ok" else 2), summary


def army_scroll(out_dir, args):
    import pyautogui

    from army_training_scroll import SCROLL_DOWN, SCROLL_UP, search_in_direction

    pyautogui.FAILSAFE = True
    first, origin = _capture()
    if (first.shape[1], first.shape[0]) != EXPECTED_SIZE:
        report = {"error": f"unexpected_frame_size:{(first.shape[1], first.shape[0])}"}
        _write_json(out_dir / "army_scroll.json", report)
        return 2, report
    if _barracks_readings(first)[0]["layout_status"] != "ok":
        report = {"error": "barracks_slots_not_recognized"}
        _write_json(out_dir / "army_scroll.json", report)
        return 2, report

    report = {"directions": {}}
    exit_code = 0
    for label, direction in (("down", SCROLL_DOWN), ("up", SCROLL_UP)):
        counter = {"n": 0}

        def inspect(frame, label=label, counter=counter):
            _save(out_dir / f"{label}_{counter['n']:02d}.png", frame)
            counter["n"] += 1
            try:
                summary, _, _ = _barracks_readings(frame)
            except Exception as error:
                summary = {"error": f"{type(error).__name__}: {error}"}
            return {"status": "continue", "slots": summary}

        start = first if label == "down" else _capture()[0]
        try:
            result = search_in_direction(
                start, origin, direction, _capture, lambda point: pyautogui.moveTo(*point),
                pyautogui.scroll, inspect, _stop_check, max_batches=args.batches,
            )
            report["directions"][label] = {
                "status": result.status, "reason": result.reason, "batches": result.batches,
                "observations": [obs["slots"] for obs in result.observations],
            }
            if result.status == "blocked":
                exit_code = 1
        except Exception as error:
            report["directions"][label] = {"status": "error", "reason": f"{type(error).__name__}: {error}"}
            exit_code = 1
            break
    _write_json(out_dir / "army_scroll.json", report)
    return exit_code, report


PROBES = {"preflight": preflight, "army_slots": army_slots, "army_scroll": army_scroll}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only live probes of the game window.")
    parser.add_argument("probe", choices=sorted(PROBES))
    parser.add_argument("--out", required=True, help="directory for screenshots and JSON")
    parser.add_argument("--batches", type=int, default=DEFAULT_BATCHES, help="scroll batches per direction")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    code, report = PROBES[args.probe](out_dir, args)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default)[:4000])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
