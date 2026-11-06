import json
from pathlib import Path

import numpy as np

from army_training_levels import read_layout_selector_levels
from army_training_slot_reader import read_slot_readings
from army_training_slots import STATUS_OK, find_slots
from army_training_scanner import (
    _read_image,
    read_army_training_snapshot,
    read_army_training_snapshot_from_image,
)
from tools.verify import load_templates
from ui_variants import resolve_asset_path, resolve_variant


ROOT_DIR = Path(__file__).resolve().parents[1]
BROWSER_SCREENSHOT = (
    ROOT_DIR / "ui" / "browser" / "tests" / "army_training" / "zrzut_pulpitu_website.png"
)
ACTIVE_SCREENSHOT = (
    ROOT_DIR / "ui" / "browser" / "tests" / "army_training" / "army_training_active_website.png"
)
IDLE_SCREENSHOT = (
    ROOT_DIR / "ui" / "browser" / "tests" / "army_training" / "army_training_nonactive_website.png"
)
CONFIG_PATH = ROOT_DIR / "config.json"


def test_browser_variant_detects_three_slots_and_reads_each_slot_independently():
    layout = find_slots(BROWSER_SCREENSHOT, variant_id="browser")
    image = _read_image(BROWSER_SCREENSHOT)

    assert layout.status == STATUS_OK
    assert [(x, y) for x, y, _ in layout.anchors] == [(775, 774), (1036, 774), (1297, 774)]
    assert all(slot.anchor_score >= 0.99 for slot in layout.slots)
    assert all(slot.check_score >= 0.99 for slot in layout.slots)

    readings = [read_slot_readings(image, slot) for slot in layout.slots]
    assert [reading.queue_limit.value for reading in readings] == [4170, 4170, 2085]
    assert [reading.city_count.value for reading in readings] == [4170, 0, 2085]
    assert [reading.silver_cost.value for reading in readings] == [2_730_000] * 3
    assert all(reading.queue_limit.reliable(70) for reading in readings)
    assert all(reading.city_count.reliable(70) for reading in readings)
    assert all(reading.silver_cost.reliable(70) for reading in readings)


def test_browser_selector_level_uncertainty_is_not_promoted_to_a_reading():
    layout = find_slots(BROWSER_SCREENSHOT, variant_id="browser")
    levels = read_layout_selector_levels(_read_image(BROWSER_SCREENSHOT), layout.slots)

    assert levels.status == "unknown"
    assert all(reading.status == "unknown" for reading in levels.slot_readings)


def test_browser_scanner_classifies_active_and_idle_training_from_fixture_roi():
    active = read_army_training_snapshot(ACTIVE_SCREENSHOT, variant_id="browser")
    idle = read_army_training_snapshot(IDLE_SCREENSHOT, variant_id="browser")

    assert active["status"] == "active"
    assert active["has_active_training"] is True
    assert active["training_unit_image_detail"] >= 20
    assert idle["status"] == "idle"
    assert idle["has_active_training"] is False
    assert idle["empty_unit_template_score"] >= 0.90
    assert active["speedup_button_detected"] is None
    assert idle["speedup_button_detected"] is None
    assert active["trained_unit_count_error"] == "not_supported_for_browser_variant"


def test_browser_scanner_keeps_ambiguous_training_roi_unknown():
    image = _read_image(IDLE_SCREENSHOT)
    variant = resolve_variant("browser")
    image[326:384, 668:728] = 0

    snapshot = read_army_training_snapshot_from_image(image, variant=variant)

    assert snapshot["status"] == "unknown"
    assert snapshot["has_active_training"] is None


def test_browser_templates_are_resolved_only_from_browser_assets():
    variant = resolve_variant("browser")
    regions = json.loads(variant["regions"].read_text(encoding="utf-8"))
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    templates = load_templates(regions, "army_training", config, variant)

    assert templates
    assert all(template is not None for _, _, template, _ in templates)
    assert all(
        resolve_asset_path(variant, region["template"]).is_relative_to(variant["templates"])
        for _, region, _, _ in templates
    )
