"""Resolve interface-specific assets from the explicit UI variant registry."""

import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT_DIR / "ui_variants.json"


class UIVariantError(ValueError):
    """Raised when a UI variant is unknown, unavailable, or incomplete."""


def load_registry(path=REGISTRY_PATH):
    try:
        registry = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UIVariantError(f"Cannot read UI variant registry: {error}") from error
    if not isinstance(registry, dict) or not isinstance(registry.get("variants"), dict):
        raise UIVariantError("UI variant registry must contain a 'variants' object.")
    return registry


def resolve_variant(variant_id=None, registry_path=REGISTRY_PATH):
    registry = load_registry(registry_path)
    selected_id = variant_id or registry.get("default_variant")
    variants = registry["variants"]
    if not isinstance(selected_id, str) or selected_id not in variants:
        raise UIVariantError(f"Unknown UI variant: {selected_id!r}.")

    variant = variants[selected_id]
    if not isinstance(variant, dict):
        raise UIVariantError(f"Invalid configuration for UI variant '{selected_id}'.")
    if variant.get("status") != "ready":
        raise UIVariantError(
            f"UI variant '{selected_id}' is not available (status: {variant.get('status')!r})."
        )

    paths = {}
    for key in ("regions", "templates", "screenshots", "tests", "verification_output"):
        value = variant.get(key)
        if not isinstance(value, str) or not value:
            raise UIVariantError(f"UI variant '{selected_id}' has no usable '{key}' path.")
        path = Path(value)
        if path.is_absolute():
            raise UIVariantError(f"UI variant '{selected_id}' path '{key}' must be relative to the project root.")
        resolved = (ROOT_DIR / path).resolve()
        if not resolved.is_relative_to(ROOT_DIR.resolve()):
            raise UIVariantError(f"UI variant '{selected_id}' path '{key}' escapes the project root.")
        paths[key] = resolved

    return {"id": selected_id, "status": "ready", **paths}


def resolve_asset_path(variant, asset_path):
    """Resolve a region template path under the selected variant's template root."""
    template_root = Path(variant["templates"]).resolve()
    relative_path = Path(asset_path)
    if relative_path.is_absolute():
        raise UIVariantError("Template paths must be relative to the selected variant.")
    if relative_path.parts and relative_path.parts[0] == "templates":
        relative_path = Path(*relative_path.parts[1:])
        resolved = (template_root / relative_path).resolve()
    else:
        resolved = (ROOT_DIR / relative_path).resolve()
    if not resolved.is_relative_to(template_root):
        raise UIVariantError(f"Template path '{asset_path}' is outside the selected variant's template root.")
    return resolved
