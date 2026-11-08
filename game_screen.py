"""Shared game-screen actions used before task-specific navigation."""

from pathlib import Path

ESCAPE_PRESS_COUNT = 3
ESCAPE_INTERVAL_SECONDS = 0.1
STOP_FILE = Path.home() / ".tba_stop"


class GameScreenError(RuntimeError):
    """A shared screen action could not be completed safely."""


def clear_game_screen(execute=False, press_key=None, stop_file=STOP_FILE, trace=None):
    """Plan or send three rapid Escape presses without inspecting the screen."""
    result = {
        "key": "esc",
        "presses": ESCAPE_PRESS_COUNT,
        "interval_seconds": ESCAPE_INTERVAL_SECONDS,
        "actions_executed": False,
    }
    if not execute:
        result["status"] = "DRY_RUN"
        if trace is not None:
            trace.record("reset_screen", action="press_escape_three_times", decision="preview_only")
        return result

    stop_file = Path(stop_file)
    if stop_file.exists():
        if trace is not None:
            trace.record("reset_screen", action="press_escape_three_times", decision="block",
                         verification="not_sent", reason="emergency_stop_file_exists")
        raise GameScreenError(f"Emergency stop file exists: {stop_file}")

    if press_key is None:
        try:
            import pyautogui
        except ImportError as error:
            raise GameScreenError("Live screen reset requires the 'pyautogui' package.") from error
        pyautogui.FAILSAFE = True
        press_key = pyautogui.press

    try:
        press_key("esc", presses=ESCAPE_PRESS_COUNT, interval=ESCAPE_INTERVAL_SECONDS)
    except Exception as error:
        if trace is not None:
            trace.record("reset_screen", action="press_escape_three_times", decision="stop",
                         verification="unknown", reason=str(error))
        raise GameScreenError(f"Escape sequence failed; screen state is uncertain: {error}") from error

    result.update(status="RESET_SENT", actions_executed=True)
    if trace is not None:
        trace.record("reset_screen", action="press_escape_three_times", decision="send", verification="completed")
    return result