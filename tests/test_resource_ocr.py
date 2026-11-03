import json
from pathlib import Path

import numpy as np
import pytest

from tools.resource_ocr import classify_text_color, parse_resource_amount, read_resource_snapshot


ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT_DIR / "tests" / "data" / "world_map"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("38.2M", 38200000),
        ("38,2M", 38200000),
        ("567M", 567000000),
        ("1K", 1000),
        ("1000K", 1000000),
        ("1B", 1000000000),
        ("1000B", 1000000000000),
        ("1T", 1000000000000),
        ("0", 0),
        ("bad", None),
        ("1.2.3M", None),
    ],
)
def test_parse_resource_amount(text, expected):
    assert parse_resource_amount(text) == expected


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        ((255, 255, 255), "white"),
        ((20, 25, 220), "red"),
        ((90, 90, 90), "unknown"),
    ],
)
def test_classify_text_color(color, expected):
    crop = np.full((21, 55, 3), color, dtype=np.uint8)
    assert classify_text_color(crop, min_color_pixels=20) == expected


def test_ambiguous_mixed_text_color_is_unknown():
    crop = np.zeros((21, 55, 3), dtype=np.uint8)
    crop[:, :27] = (255, 255, 255)
    crop[:, 27:] = (20, 25, 220)
    assert classify_text_color(crop, min_color_pixels=20) == "unknown"


@pytest.mark.parametrize("expected_path", sorted(TEST_DATA_DIR.glob("*.json")))
def test_resource_reads_match_screen_expectations(expected_path):
    expected_data = json.loads(expected_path.read_text(encoding="utf-8"))
    result = read_resource_snapshot(
        TEST_DATA_DIR / expected_data["image"],
        screen=expected_data["screen"],
    )

    for resource_name, expected in expected_data["resources"].items():
        actual = result[resource_name]
        assert actual["raw"] == expected["raw"]
        assert actual["value"] == expected["value"]
        assert actual["color"] == expected["color"]
        assert actual["confidence"] >= actual["minimum_confidence"]
        assert "allowed" not in actual
        assert "status" not in actual


def test_snapshot_is_feature_agnostic_and_reads_all_resources():
    result = read_resource_snapshot(TEST_DATA_DIR / "account_2.png")
    assert set(result) == {"wood", "iron", "stone", "food", "silver", "gold"}

    for reading in result.values():
        assert reading["confidence_ok"] is (
            reading["confidence"] is not None
            and reading["confidence"] >= reading["minimum_confidence"]
        )
        assert "allowed" not in reading
        assert "status" not in reading
