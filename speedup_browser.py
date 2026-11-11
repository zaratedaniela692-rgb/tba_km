"""Browser adapter boundary for the shared speedup finishing mechanics.

Browser-specific screen readers and input callbacks are intentionally absent until
verified browser Speed Up assets are supplied. Never substitute desktop assets here.
"""

import time
from dataclasses import dataclass
from typing import Callable

from speedup import BLOCKED, MAX_SCROLLS, SpeedupResult, finish_with_speedups

BROWSER_CLIENT_ID = "browser"
BROWSER_SPEEDUP_ASSETS_READY = False


@dataclass(frozen=True)
class BrowserSpeedupCallbacks:
    """Browser-specific I/O callbacks required by the shared speedup orchestrator."""

    client_id: str
    capture_fn: Callable
    read_dialog_fn: Callable
    click_fn: Callable
    scroll_fn: Callable
    stop_fn: Callable


def _blocked(reason):
    return SpeedupResult(BLOCKED, reason)


def finish_browser_dialog(
    callbacks=None,
    execute=False,
    sleep_fn=time.sleep,
    max_scrolls=MAX_SCROLLS,
):
    """Use the shared planner/orchestrator through a separately gated browser adapter.

    This is only an integration seam: without reviewed browser Speed Up assets and
    browser-specific callbacks, it returns BLOCKED without invoking any callback.
    """
    if not BROWSER_SPEEDUP_ASSETS_READY:
        return _blocked("browser_speedup_assets_unverified")

    if callbacks is None:
        return _blocked("browser_speedup_adapter_unavailable")
    if callbacks.client_id != BROWSER_CLIENT_ID:
        return _blocked("browser_speedup_adapter_variant_mismatch")

    return finish_with_speedups(
        callbacks.capture_fn,
        callbacks.read_dialog_fn,
        callbacks.click_fn,
        callbacks.scroll_fn,
        stop_fn=callbacks.stop_fn,
        sleep_fn=sleep_fn,
        dry_run=not execute,
        max_scrolls=max_scrolls,
    )
