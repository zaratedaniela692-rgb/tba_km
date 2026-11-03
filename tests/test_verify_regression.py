import json
from pathlib import Path

import pytest

from tools.verify import get_threshold, load_templates, match_template, read_image


ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT_DIR / "tests" / "data"
REGIONS_PATH = ROOT_DIR / "regions.json"
CONFIG_PATH = ROOT_DIR / "config.json"


@pytest.mark.parametrize("expected_path", sorted(TEST_DATA_DIR.glob("*/*.json")))
def test_template_detections_match_expected_regions(expected_path):
    expected_data = json.loads(expected_path.read_text(encoding="utf-8"))
    screen = expected_data["screen"]
    image_path = expected_path.parent / expected_data["image"]
    image = read_image(image_path)

    regions = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    templates = load_templates(regions, screen, config)
    templates_by_name = {name: (region, template, threshold) for name, region, template, threshold in templates}

    assert set(expected_data["expected"]).issubset(templates_by_name)
    tolerance = expected_data.get("position_tolerance", 0)

    for name, expected in expected_data["expected"].items():
        _, template, threshold = templates_by_name[name]
        confidence, location = match_template(image, template)
        visible = confidence is not None and confidence >= threshold
        assert visible is expected["visible"], (
            f"{expected_path.name}: {name} visible={visible}, "
            f"confidence={confidence}, threshold={threshold}"
        )

        if expected["visible"] and "position" in expected:
            expected_x, expected_y = expected["position"]
            actual_x, actual_y = location
            assert abs(actual_x - expected_x) <= tolerance, (
                f"{expected_path.name}: {name} x={actual_x}, expected {expected_x} +/- {tolerance}"
            )
            assert abs(actual_y - expected_y) <= tolerance, (
                f"{expected_path.name}: {name} y={actual_y}, expected {expected_y} +/- {tolerance}"
            )


def test_numeric_regions_are_not_loaded_as_templates():
    regions = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    screen_regions = regions["world_map"]
    numeric_names = {
        name for name, region in screen_regions.items()
        if region.get("type") == "number"
    }

    templates = load_templates(regions, "world_map", config)
    template_names = {name for name, _, _, _ in templates}

    assert numeric_names == {
        "wood_count", "iron_count", "stone_count",
        "food_count", "silver_count", "gold_count",
    }
    assert numeric_names.isdisjoint(template_names)
