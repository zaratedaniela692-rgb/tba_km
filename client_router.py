"""Read-only foreground game client and player-profile observer."""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from profile_identity import (
    ProfileIdentityError,
    profile_registry_path,
    read_player_name,
    resolve_registered_profile,
)
from task_controller import PROFILES_DIR, task_queue_path
from ui_variants import resolve_variant

CLIENT_DESKTOP = "desktop"
CLIENT_BROWSER = "browser"
CLIENT_NOT_GAME = "not_game"
CLIENT_UNKNOWN = "unknown"
CLIENT_BROWSER_UNAVAILABLE = "browser_identity_unconfigured"


@dataclass(frozen=True)
class ForegroundWindow:
    title: str
    process_name: str


@dataclass(frozen=True)
class RouteObservation:
    status: str
    client_id: str | None
    player_name: str | None
    profile_id: str | None
    queue_path: str | None
    reason: str
    window_title: str
    process_name: str
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def classify_foreground_window(window, game_title_token="total battle"):
    """Classify by foreground process and title; never treat Chrome itself as proof of the game."""
    if window is None:
        return CLIENT_UNKNOWN, "foreground_window_unavailable"
    title = window.title.strip().casefold()
    process = Path(window.process_name.strip().replace("/", "\\")).name.casefold()
    if not title or not process:
        return CLIENT_UNKNOWN, "foreground_window_metadata_incomplete"

    is_game_title = game_title_token.casefold() in title
    if process in {"chrome.exe", "msedge.exe", "firefox.exe"}:
        if is_game_title:
            return CLIENT_BROWSER, "game_title_in_browser_foreground"
        return CLIENT_NOT_GAME, "browser_without_game_title"
    if is_game_title:
        return CLIENT_DESKTOP, "game_title_in_native_foreground"
    return CLIENT_NOT_GAME, "foreground_window_is_not_game"


def get_foreground_window():
    """Read foreground window title and process executable using the Windows API."""
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    title_length = user32.GetWindowTextLengthW(hwnd)
    title_buffer = ctypes.create_unicode_buffer(title_length + 1)
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))

    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    process_handle = kernel32.OpenProcess(0x1000, False, process_id.value)
    if not process_handle:
        return ForegroundWindow(title_buffer.value, "")
    try:
        path_length = wintypes.DWORD(32768)
        path_buffer = ctypes.create_unicode_buffer(path_length.value)
        if not kernel32.QueryFullProcessImageNameW(
            process_handle, 0, path_buffer, ctypes.byref(path_length),
        ):
            return ForegroundWindow(title_buffer.value, "")
        process_name = Path(path_buffer.value).name
    finally:
        kernel32.CloseHandle(process_handle)
    return ForegroundWindow(title_buffer.value, process_name)


def observe_foreground_profile(
    window=None,
    capture_fn=None,
    profiles_dir=PROFILES_DIR,
    name_reader=read_player_name,
):
    """Observe client and account. A result is routable only for a unique configured profile."""
    window = get_foreground_window() if window is None else window
    title = window.title if window else ""
    process_name = window.process_name if window else ""
    client_id, classification_reason = classify_foreground_window(window)
    if client_id == CLIENT_UNKNOWN:
        return RouteObservation("unknown", None, None, None, None, classification_reason, title, process_name)
    if client_id == CLIENT_NOT_GAME:
        return RouteObservation("not_game", None, None, None, None, classification_reason, title, process_name)
    if client_id == CLIENT_BROWSER:
        return RouteObservation(
            "blocked", CLIENT_BROWSER, None, None, None, CLIENT_BROWSER_UNAVAILABLE, title, process_name,
        )

    if capture_fn is None:
        from army_training_live_e2e import capture_primary_monitor

        capture_fn = capture_primary_monitor
    try:
        frame, _origin = capture_fn()
    except Exception as error:
        return RouteObservation("blocked", client_id, None, None, None, f"capture_failed:{error}", title, process_name)

    try:
        reading = name_reader(frame, variant=resolve_variant("legacy"))
    except Exception as error:
        return RouteObservation("blocked", client_id, None, None, None, f"player_name_read_failed:{error}", title, process_name)
    if reading.status != "ok" or not reading.player_name:
        return RouteObservation(
            "blocked", client_id, None, None, None,
            f"player_name_{reading.status}:{reading.reason}", title, process_name,
        )

    try:
        profile = resolve_registered_profile(reading.player_name, profile_registry_path(profiles_dir))
    except ProfileIdentityError as error:
        return RouteObservation(
            "blocked", client_id, reading.player_name, None, None,
            f"profile_unresolved:{error}", title, process_name,
        )
    return RouteObservation(
        "routed", client_id, reading.player_name, profile.profile_id,
        str(task_queue_path(profile.profile_id, profiles_dir)), "unique_registered_profile",
        title, process_name,
    )


def watch_foreground(
    observe_fn=observe_foreground_profile,
    interval_seconds=1.0,
    stop_fn=lambda: False,
    sleep_fn=time.sleep,
    output=print,
):
    """Report route changes only; queue execution is intentionally not part of this observer."""
    previous = None
    while not stop_fn():
        observation = observe_fn()
        identity = (
            observation.status,
            observation.client_id,
            observation.player_name,
            observation.profile_id,
            observation.reason,
            observation.window_title,
            observation.process_name,
        )
        if identity != previous:
            output(json.dumps(asdict(observation), ensure_ascii=False, sort_keys=True))
            previous = identity
        sleep_fn(interval_seconds)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Observe the foreground game client and its registered profile; no actions are run."
    )
    parser.add_argument("--once", action="store_true", help="report one foreground observation and exit")
    parser.add_argument("--interval", type=float, default=1.0, help="watch polling interval in seconds")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.once:
        print(json.dumps(asdict(observe_foreground_profile()), ensure_ascii=False, indent=2))
        return 0
    try:
        watch_foreground(interval_seconds=args.interval)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
