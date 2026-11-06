import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from speedup_calibration import (
    CalibrationError,
    CONFIRMATION_PHRASE,
    dialog_anchor_matches,
    run_scroll_calibration,
)


ROOT = Path(__file__).resolve().parents[1]
FRAME_SIZE = (1920, 1080)
REGIONS = {
    "speedup_inventory_viewport": {"x": 10, "y": 20, "w": 100, "h": 50},
}


def image(value=0, size=FRAME_SIZE):
    return np.full((size[1], size[0], 3), value, dtype=np.uint8)


def run_calibration(tmp_path, frames, **kwargs):
    frames = iter(frames)
    events = []
    saved = []

    def capture():
        events.append("capture")
        return next(frames), (100, 200)

    result = run_scroll_calibration(
        capture,
        lambda desktop_x, desktop_y: events.append(("move", desktop_x, desktop_y)),
        lambda amount: events.append(("scroll", amount)),
        lambda: FRAME_SIZE,
        tmp_path / "run",
        sleep_fn=lambda _: None,
        save_frame_fn=lambda path, frame: saved.append(path.name),
        anchor_fn=lambda frame, regions: True,
        regions=REGIONS,
        **kwargs,
    )
    return result, events, saved


def test_moves_into_panel_before_each_scroll_and_saves_each_view(tmp_path):
    result, events, saved = run_calibration(tmp_path, [image(), image(40), image(40)])

    assert result.status == "COMPLETE"
    assert result.reason == "viewport_unchanged"
    assert result.captures == 3
    assert result.scrolls == 2
    assert events == [
        "capture",
        ("move", 160, 245),
        ("scroll", -1),
        "capture",
        ("move", 160, 245),
        ("scroll", -1),
        "capture",
    ]
    assert saved == [
        "step_000_initial.png",
        "step_001_after_scroll.png",
        "step_002_after_scroll.png",
    ]
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["pointer_frame_point"] == {"x": 60, "y": 45}
    assert manifest["scrolls"][0]["pointer_desktop_point"] == {"x": 160, "y": 245}
    assert manifest["captures"][-1]["viewport_changed_fraction"] == 0.0


def test_saves_first_unchanged_view_then_stops(tmp_path):
    result, events, saved = run_calibration(tmp_path, [image(), image()])

    assert result.status == "COMPLETE"
    assert result.scrolls == 1
    assert saved == ["step_000_initial.png", "step_001_after_scroll.png"]
    assert events.count(("scroll", -1)) == 1


def test_emergency_stop_blocks_before_pointer_move_and_is_recorded(tmp_path):
    result, events, _ = run_calibration(
        tmp_path,
        [image()],
        stop_fn=lambda: (_ for _ in ()).throw(RuntimeError("operator stop")),
    )

    assert result.status == "BLOCKED"
    assert result.reason.startswith("emergency_stop")
    assert events == ["capture"]
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "frame, display_size, anchor, reason",
    [
        (image(size=(1280, 720)), (1280, 720), True, "unexpected_frame_size"),
        (image(), (1280, 720), True, "display_size_mismatch"),
        (image(), FRAME_SIZE, False, "speedup_dialog_not_recognized"),
    ],
)
def test_preflight_failure_never_moves_or_scrolls(tmp_path, frame, display_size, anchor, reason):
    output_dir = tmp_path / "run"
    result = run_scroll_calibration(
        lambda: (frame, (0, 0)),
        lambda *_: pytest.fail("pointer moved before preflight passed"),
        lambda *_: pytest.fail("scroll sent before preflight passed"),
        lambda: display_size,
        output_dir,
        save_frame_fn=lambda *_: None,
        anchor_fn=lambda *_: anchor,
        regions=REGIONS,
    )

    assert result.status == "BLOCKED"
    assert result.reason.startswith(reason)
    assert result.captures == 1
    assert json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))["scrolls"] == []


def test_scroll_limit_is_capped_at_ten(tmp_path):
    with pytest.raises(CalibrationError, match="between 1 and 10"):
        run_scroll_calibration(
            lambda: (image(), (0, 0)),
            lambda *_: None,
            lambda *_: None,
            lambda: FRAME_SIZE,
            tmp_path / "run",
            regions=REGIONS,
            max_steps=11,
        )


def test_cli_requires_explicit_calibration_confirmation(capsys):
    from speedup_calibration import main

    with pytest.raises(SystemExit) as error:
        main(["--calibrate-scroll", "--confirm", "not the phrase"])

    assert error.value.code == 2
    assert CONFIRMATION_PHRASE in capsys.readouterr().err


@pytest.mark.parametrize(
    "relative_path, expected",
    [
        ("debug/speedup/calibration_20261106_195223_110853/step_000_initial.png", True),
        ("debug/speedup/calibration_20261106_195249_832058/step_000_initial.png", True),
        ("debug/speedup/calibration_20261106_195330_491310/step_000_initial.png", True),
        ("screenshots/speedup_module/after_click_7days_speedup.png", True),
        ("screenshots/speedup_module/speedup_view.png", True),
        ("screenshots/speedup_module/speedup_view2.png", True),
        ("screenshots/speedup_module/speedup_view3.png", True),
        ("screenshots/speedup_module/academy_speeduo_button.png", False),
    ],
)
def test_dialog_anchor_recognition_handles_small_offset_and_rejects_other_screens(relative_path, expected):
    frame = cv2.imread(str(ROOT / relative_path))

    assert frame is not None, relative_path
    assert dialog_anchor_matches(frame) is expected