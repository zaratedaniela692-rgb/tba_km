import pytest

import speedup_browser as browser
from speedup import DialogReading, FINISHED, InventoryRow, PLANNED
from speedup_readings import ParsedReading
from ui_variants import UIVariantError, resolve_variant


def _callbacks(position, clicks, client_id="browser"):
    def capture():
        return position["value"]

    def read_dialog(frame):
        if clicks:
            timer = 0
            rows = ()
        else:
            timer = 3600
            rows = (InventoryRow(3600, 1, (10, 20)),)
        return DialogReading(
            ParsedReading(str(timer), timer, 100.0, "ok"),
            rows,
            True,
            frame,
        )

    def scroll(direction):
        position["value"] = min(1, max(0, position["value"] + direction))

    return browser.BrowserSpeedupCallbacks(
        client_id=client_id,
        capture_fn=capture,
        read_dialog_fn=read_dialog,
        click_fn=lambda point: clicks.append(point),
        scroll_fn=scroll,
        stop_fn=lambda: None,
    )


def test_browser_channel_blocks_before_calling_any_callback_while_assets_are_unverified(monkeypatch):
    calls = []
    monkeypatch.setattr(browser, "BROWSER_SPEEDUP_ASSETS_READY", False)
    callbacks = browser.BrowserSpeedupCallbacks(
        client_id="browser",
        capture_fn=lambda: calls.append("capture"),
        read_dialog_fn=lambda _frame: calls.append("read"),
        click_fn=lambda _point: calls.append("click"),
        scroll_fn=lambda _direction: calls.append("scroll"),
        stop_fn=lambda: calls.append("stop"),
    )

    result = browser.finish_browser_dialog(callbacks, execute=True)

    assert result.status == "BLOCKED"
    assert result.reason == "browser_speedup_assets_unverified"
    assert calls == []


def test_speedup_feature_gate_is_independent_of_global_browser_variant(monkeypatch):
    with pytest.raises(UIVariantError, match="not available"):
        resolve_variant("browser")

    monkeypatch.setattr(browser, "BROWSER_SPEEDUP_ASSETS_READY", True)
    position = {"value": 0}
    clicks = []

    result = browser.finish_browser_dialog(
        _callbacks(position, clicks),
        sleep_fn=lambda _seconds: None,
    )

    assert result.status == PLANNED
    assert clicks == []


def test_browser_channel_rejects_callbacks_from_another_client(monkeypatch):
    monkeypatch.setattr(browser, "BROWSER_SPEEDUP_ASSETS_READY", True)
    callbacks = _callbacks({"value": 0}, [], client_id="desktop")

    result = browser.finish_browser_dialog(callbacks, execute=True)

    assert result.status == "BLOCKED"
    assert result.reason == "browser_speedup_adapter_variant_mismatch"


def test_browser_channel_uses_shared_orchestrator_for_dry_run(monkeypatch):
    monkeypatch.setattr(browser, "BROWSER_SPEEDUP_ASSETS_READY", True)
    position = {"value": 0}
    clicks = []

    result = browser.finish_browser_dialog(
        _callbacks(position, clicks),
        sleep_fn=lambda _seconds: None,
    )

    assert result.status == PLANNED
    assert result.reason == "dry_run"
    assert clicks == []


def test_browser_channel_uses_shared_orchestrator_for_confirmed_execution(monkeypatch):
    monkeypatch.setattr(browser, "BROWSER_SPEEDUP_ASSETS_READY", True)
    position = {"value": 0}
    clicks = []

    result = browser.finish_browser_dialog(
        _callbacks(position, clicks),
        execute=True,
        sleep_fn=lambda _seconds: None,
    )

    assert result.status == FINISHED
    assert result.reason == "task_finished"
    assert clicks == [(10, 20)]
