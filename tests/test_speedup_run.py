import pytest

from speedup_run import SCAN_CONFIRMATION, USE_CONFIRMATION, main, run_open_dialog


@pytest.mark.parametrize(
    "arguments",
    (
        ["--confirm", "wrong"],
        ["--execute", "--confirm", SCAN_CONFIRMATION],
        ["--confirm", USE_CONFIRMATION],
    ),
)
def test_wrong_confirmation_is_rejected_before_live_adapters(arguments, monkeypatch):
    import speedup_run

    monkeypatch.setattr(speedup_run, "_create_live_adapters", lambda: pytest.fail("live input adapter was created"))

    with pytest.raises(SystemExit) as error:
        main(arguments)

    assert error.value.code == 2


def test_execute_confirmation_is_distinct_from_scan_confirmation():
    assert SCAN_CONFIRMATION != USE_CONFIRMATION


def test_open_dialog_adapter_runs_the_checkpoint_executor_in_execute_mode(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    import cv2
    import numpy as np
    import speedup_calibration
    import speedup_run

    template = np.zeros((4, 8, 3), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "button.png"), template)
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps({"button_template": "button.png"}), encoding="utf-8")
    adapters = (lambda: None, lambda *_: None, lambda *_: None, lambda *_: None, lambda: None, lambda: (1920, 1080))
    captured = {}
    monkeypatch.setattr(speedup_run, "_create_live_adapters", lambda: adapters)
    monkeypatch.setattr(speedup_run, "BUTTON_MAP_PATH", map_path)
    monkeypatch.setattr(speedup_run, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(speedup_run, "configure_tesseract", lambda _: "tesseract.exe")
    monkeypatch.setattr(speedup_calibration, "load_speedup_regions", lambda: {"speedup_inventory_viewport": {}})

    def run_checkpoint(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(status="FINISHED")

    monkeypatch.setattr(speedup_run, "run_checkpoint_speedups", run_checkpoint)

    result = speedup_run.run_open_dialog(execute=True)

    assert result.status == "FINISHED"
    assert captured["kwargs"]["dry_run"] is False
    assert captured["kwargs"]["regions"] == {"speedup_inventory_viewport": {}}


def test_army_caller_runs_checkpoint_finisher_after_preflight(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    import speedup_run
    import speedup_calibration

    button_map_path = tmp_path / "button_map.json"
    button_map_path.write_text(json.dumps({"button_template": "use.png"}), encoding="utf-8")
    expected_result = SimpleNamespace(status="FINISHED")
    calls = {}
    regions = {"speedup_inventory_viewport": {"x": 1, "y": 2, "w": 3, "h": 4}}
    adapters = (lambda: None, lambda *_: None, lambda _: None, lambda _: None, lambda: None, lambda: (1920, 1080))

    monkeypatch.setattr(speedup_run, "BUTTON_MAP_PATH", button_map_path)
    monkeypatch.setattr(speedup_run, "_create_live_adapters", lambda: adapters)
    monkeypatch.setattr(speedup_run, "configure_tesseract", lambda _: "tesseract.exe")
    monkeypatch.setattr(speedup_run.cv2, "imread", lambda _: object())
    monkeypatch.setattr(speedup_calibration, "load_speedup_regions", lambda: regions)

    def run_checkpoint(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return expected_result

    monkeypatch.setattr(speedup_run, "run_checkpoint_speedups", run_checkpoint)

    result = run_open_dialog(execute=True, tesseract_cmd="tesseract.exe")

    assert result is expected_result
    assert calls["kwargs"]["regions"] == regions
    assert calls["kwargs"]["stop_fn"] is speedup_run._emergency_stop
    assert calls["kwargs"]["dry_run"] is False