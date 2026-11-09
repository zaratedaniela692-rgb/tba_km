import numpy as np

from speedup_live import create_desktop_callbacks
from speedup_readings import ParsedReading


def _session(max_position=16):
    position = {"value": 0}
    frame_shape = (20, 20, 3)
    regions = {
        "speedup_dialog_anchor": {},
        "speedup_inventory_viewport": {"x": 4, "y": 5, "w": 4, "h": 4},
        "speedup_item_quantity": {"x": 8, "y": 7, "w": 2, "h": 2},
        "speedup_use_button": {"x": 7, "y": 7, "w": 2, "h": 2},
    }
    checkpoints = tuple({
        "scroll_count": step,
        "buttons": [{"duration_label": "1h", "duration_seconds": 3600,
                     "rectangle": {"x": 1, "y": 1, "width": 1, "height": 1},
                     "center": {"x": 1, "y": 1}}],
    } for step in (3, 11, 16))
    button_map = {"coordinate_space": "speedup_inventory_viewport", "checkpoints": checkpoints}
    events = {"moves": [], "wheels": [], "clicks": []}

    def frame():
        result = np.zeros(frame_shape, dtype=np.uint8)
        viewport = result[5:9, 4:8]
        viewport[:, :, :] = position["value"] * 20
        return result

    def wheel(notches):
        events["wheels"].append(notches)
        position["value"] = min(max_position, max(0, position["value"] - notches))

    def read_inventory(image, checkpoint, *_args):
        assert int(image[0, 0, 0]) // 20 == checkpoint["scroll_count"]
        return type("Inventory", (), {
            "status": "complete", "reason": "", "items": (
                type("Item", (), {
                    "duration_seconds": 3600,
                    "quantity": ParsedReading("12", 12, 100.0, "ok"),
                    "button_center": {"x": 1, "y": 2},
                })(),
            ),
        })()

    callbacks = create_desktop_callbacks(
        lambda: (frame(), (100, 200)),
        lambda x, y: events["moves"].append((x, y)),
        wheel,
        lambda x, y: events["clicks"].append((x, y)),
        lambda: (20, 20),
        lambda: None,
        sleep_fn=lambda _: None,
        regions=regions,
        button_map=button_map,
        button_template=np.zeros((1, 1, 3), dtype=np.uint8),
        anchor_fn=lambda *_: True,
        timer_reader=lambda *_: ParsedReading("1d:0h", 86400, 100.0, "ok"),
        inventory_reader=read_inventory,
        expected_size=(20, 20),
    )
    return callbacks, events


def test_live_callbacks_track_list_to_checkpoint_and_translate_use_point():
    (capture, read, click, scroll, state), events = _session()
    initial = read(capture())
    assert initial.timer.value == 86400

    scroll(-1)
    top = read(capture())
    scroll(-1)
    top = read(capture())
    assert top.signature == "list_step:0"

    checkpoint = None
    for _ in range(3):
        scroll(1)
        checkpoint = read(capture())

    assert checkpoint.signature == "list_step:3"
    assert checkpoint.rows_complete is True
    assert checkpoint.rows[0].click_point == (5, 7)
    click(checkpoint.rows[0].click_point)
    assert events["clicks"] == [(105, 207)]
    assert state["position"] == 3


def test_list_ending_before_last_checkpoint_is_not_reported_complete():
    (capture, read, _click, scroll, _state), _events = _session(max_position=10)
    read(capture())
    scroll(-1)
    read(capture())
    scroll(-1)
    read(capture())
    for _ in range(10):
        scroll(1)
        reading = read(capture())

    scroll(1)
    ended = read(capture())
    assert reading.signature == "list_step:10"
    assert ended.rows_complete is False