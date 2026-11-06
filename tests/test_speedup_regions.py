import json
from pathlib import Path

import cv2
import pytest

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "screenshots" / "speedup_module"
FIXTURES = ("speedup_view", "speedup_view2", "speedup_view3", "after_click_7days_speedup")
REGIONS = json.loads((ROOT / "regions.json").read_text(encoding="utf-8"))["speedup"]


def _template(name):
    return cv2.imread(str(ROOT / REGIONS[name]["template"]))


def _matches(image, name, threshold, search=None):
    x, y, w, h = search or (0, 0, image.shape[1], image.shape[0])
    result = cv2.matchTemplate(image[y:y + h, x:x + w], _template(name), cv2.TM_CCOEFF_NORMED)
    found = []
    while True:
        _, score, _, loc = cv2.minMaxLoc(result)
        if score < threshold:
            return sorted(found)
        found.append((y + loc[1], x + loc[0]))
        result[max(0, loc[1] - 10):loc[1] + 10, max(0, loc[0] - 10):loc[0] + 10] = -1


@pytest.fixture(params=FIXTURES)
def image(request):
    return cv2.imread(str(SHOTS / f"{request.param}.png"))


def test_dialog_anchor_is_found_at_the_annotated_position(image):
    region = REGIONS["speedup_dialog_anchor"]

    assert _matches(image, "speedup_dialog_anchor", 0.95) == [(region["y"], region["x"])]


def test_use_buttons_are_found_in_rows_inside_the_viewport(image):
    viewport = REGIONS["speedup_inventory_viewport"]
    search = (viewport["x"], viewport["y"], viewport["w"] + 20, viewport["h"])

    rows = _matches(image, "speedup_use_button", 0.95, search)

    assert 3 <= len(rows) <= 4
    assert all(x == REGIONS["speedup_use_button"]["x"] for _, x in rows)
    assert all(b - a == 110 for (a, _), (b, _) in zip(rows, rows[1:]))


def test_scroll_thumb_stays_inside_the_track(image):
    track = REGIONS["speedup_scroll_track"]

    (y, x), = _matches(image, "speedup_scroll_thumb", 0.9)[:1]

    assert x == track["x"]
    assert track["y"] <= y <= track["y"] + track["h"]


def test_purchase_offer_is_not_matched_as_use_button():
    image = cv2.imread(str(SHOTS / "speedup_view3.png"))
    offer = REGIONS["speedup_purchase_offer"]
    crop = image[offer["y"]:offer["y"] + offer["h"], offer["x"]:offer["x"] + offer["w"]]

    score = cv2.matchTemplate(crop, _template("speedup_use_button"), cv2.TM_CCOEFF_NORMED).max()

    assert score < 0.8
