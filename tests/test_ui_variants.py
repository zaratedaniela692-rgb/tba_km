import json
from pathlib import Path

import pytest

from army_training_scanner import read_army_training_snapshot
from ui_variants import UIVariantError, resolve_asset_path, resolve_variant
from tools.verify import load_templates, run


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_default_variant_resolves_to_existing_desktop_assets():
    variant = resolve_variant()

    assert variant["id"] == "desktop"
    assert variant["status"] == "ready"
    assert variant["regions"] == ROOT_DIR / "regions.json"
    assert variant["templates"] == ROOT_DIR / "templates"
    assert variant["verification_output"] == ROOT_DIR / "debug" / "verify"
    assert resolve_asset_path(variant, "templates/army_training/current_training_unit.png").is_file()


def test_legacy_variant_alias_preserves_existing_commands():
    assert resolve_variant("legacy")["id"] == "desktop"


def test_browser_variant_resolves_to_isolated_asset_roots():
    desktop = resolve_variant("desktop")
    browser = resolve_variant("browser")

    assert browser["id"] == "browser"
    assert browser["regions"] == ROOT_DIR / "ui" / "browser" / "regions.json"
    assert browser["templates"] == ROOT_DIR / "ui" / "browser" / "templates"
    assert browser["screenshots"] == ROOT_DIR / "ui" / "browser" / "screenshots"
    assert browser["tests"] == ROOT_DIR / "ui" / "browser" / "tests"
    assert browser["regions"] != desktop["regions"]
    assert browser["templates"] != desktop["templates"]


def test_explicit_modern_variant_is_rejected_without_falling_back():
    with pytest.raises(UIVariantError, match="not available"):
        resolve_variant("modern")


def test_unknown_variant_is_rejected():
    with pytest.raises(UIVariantError, match="Unknown UI variant"):
        resolve_variant("future")


def test_variant_asset_path_cannot_escape_desktop_template_root():
    variant = resolve_variant("legacy")

    with pytest.raises(UIVariantError, match="outside"):
        resolve_asset_path(variant, "templates/../regions.json")


def test_template_reference_resolves_from_selected_variant_root(tmp_path):
    variant = {
        "templates": tmp_path / "modern_templates",
    }

    assert resolve_asset_path(variant, "templates/army_training/panel.png") == (
        tmp_path / "modern_templates" / "army_training" / "panel.png"
    )


def test_desktop_scanner_default_matches_explicit_variant():
    image_path = ROOT_DIR / "screenshots" / "army_training" / "pelny.png"

    assert read_army_training_snapshot(image_path) == read_army_training_snapshot(
        image_path, variant_id="desktop"
    )


def test_scanner_rejects_unavailable_modern_before_reading_game_image(tmp_path):
    with pytest.raises(UIVariantError, match="not available"):
        read_army_training_snapshot(tmp_path / "missing.png", variant_id="modern")


def test_verifier_uses_registry_template_root():
    import json

    regions = json.loads((ROOT_DIR / "regions.json").read_text(encoding="utf-8"))
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))

    templates = load_templates(regions, "army_training", config, resolve_variant())

    assert templates
    assert all(template is not None for _, _, template, _ in templates)


def test_verifier_rejects_unavailable_modern_before_loading_assets(tmp_path):
    with pytest.raises(UIVariantError, match="not available"):
        run("world_map", tmp_path, variant_id="modern")


def test_registry_paths_must_stay_inside_project_root(tmp_path):
    registry_path = tmp_path / "ui_variants.json"
    registry_path.write_text(json.dumps({
        "default_variant": "legacy",
        "variants": {
            "legacy": {
                "status": "ready",
                "regions": "../regions.json",
                "templates": "templates",
                "screenshots": "screenshots",
                "tests": "tests",
            }
        },
    }), encoding="utf-8")

    with pytest.raises(UIVariantError, match="escapes the project root"):
        resolve_variant("legacy", registry_path)
