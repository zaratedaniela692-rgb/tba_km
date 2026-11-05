#!/usr/bin/env python3
"""Read-only scanner for the army training screen.

This module intentionally does not click or change the game state. It reads a
screenshot (or a live frame) and reports the key training states that are needed to
plan the next action safely.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from ui_variants import UIVariantError, resolve_asset_path, resolve_variant

ROOT_DIR = Path(__file__).resolve().parent
REGIONS_PATH = ROOT_DIR / "regions.json"


class ArmyTrainingScannerError(ValueError):
    """Raised when the screenshot, region map, or OCR data is invalid."""


def _read_image(path):
    path = Path(path)
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ArmyTrainingScannerError(f"Nie można odczytać obrazu: {path}")
    return image


def _load_regions(path=REGIONS_PATH):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArmyTrainingScannerError(f"Nie można odczytać regionów: {error}") from error
    return payload


def _region_crop(image, region):
    if not isinstance(region, dict):
        raise ArmyTrainingScannerError("Nieprawidłowy opis regionu.")
    x = int(region["x"])
    y = int(region["y"])
    w = int(region["w"])
    h = int(region["h"])
    height, width = image.shape[:2]
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ArmyTrainingScannerError(f"Region poza obrazem: {(x, y, w, h)}")
    return image[y:y + h, x:x + w]


def _template_match_score(image, template_path, threshold=0.8):
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise ArmyTrainingScannerError(f"Nie można odczytać wzorca: {template_path}")
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, best_score, _, _ = cv2.minMaxLoc(result)
    return float(best_score)


def _locate_template(image, template_path):
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise ArmyTrainingScannerError(f"Nie można odczytać wzorca: {template_path}")
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, best_score, _, location = cv2.minMaxLoc(result)
    return float(best_score), location


def _classify_training_unit_image(crop):
    """Classify the unobstructed unit portrait, leaving borderline crops unknown."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    detail_score = float(gray.std())
    if detail_score >= 20:
        return "active", detail_score
    return "unknown", detail_score


def _ocr_numeric_crop(crop):
    if crop is None or crop.size == 0:
        return {"raw": "", "value": None, "confidence": None}
    enlarged = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    try:
        data = pytesseract.image_to_data(thresh, config="--psm 7 -c tessedit_char_whitelist=0123456789,.", output_type=Output.DICT)
    except pytesseract.TesseractNotFoundError as error:
        raise ArmyTrainingScannerError("Nie znaleziono programu Tesseract OCR.") from error

    tokens = []
    confidences = []
    for token, confidence in zip(data.get("text", []), data.get("conf", [])):
        token = str(token).strip()
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            continue
        if token and confidence >= 0:
            tokens.append(token)
            confidences.append(confidence)
    text = " ".join(tokens)
    if not text:
        return {"raw": "", "value": None, "confidence": None}
    cleaned = re.sub(r"[^0-9,\.]", "", text)
    if not cleaned:
        return {"raw": text, "value": None, "confidence": min(confidences) if confidences else None}
    cleaned = cleaned.replace(".", "").replace(",", "")
    try:
        value = int(cleaned)
    except ValueError:
        value = None
    return {
        "raw": text,
        "value": value,
        "confidence": min(confidences) if confidences else None,
    }


def read_army_training_snapshot(image_path, screen="army_training", regions_path=None, variant_id=None):
    """Return a safe snapshot of the army-training panel without clicking anything."""
    variant = resolve_variant(variant_id)
    regions_path = Path(regions_path) if regions_path is not None else variant["regions"]
    image = _read_image(image_path)
    regions = _load_regions(regions_path).get(screen)
    if not isinstance(regions, dict):
        raise ArmyTrainingScannerError(f"Brak regionów dla ekranu '{screen}'.")

    current_panel_region = regions.get("current_trainin_army")
    training_unit_region = regions.get("current_training_unit")
    speedup_region = regions.get("speedup_panel")
    trained_unit_count_region = regions.get("current_unit_troop_count")

    if current_panel_region is None:
        raise ArmyTrainingScannerError("Brak regionu 'current_trainin_army' w regions.json.")
    if training_unit_region is None:
        raise ArmyTrainingScannerError("Brak regionu 'current_training_unit' w regions.json.")
    if speedup_region is None:
        raise ArmyTrainingScannerError("Brak regionu 'speedup_panel' w regions.json.")
    if trained_unit_count_region is None:
        raise ArmyTrainingScannerError("Brak regionu 'current_unit_troop_count' w regions.json.")

    panel_template_path = current_panel_region.get("template")
    empty_unit_template_path = training_unit_region.get("template")
    if not panel_template_path or not empty_unit_template_path:
        raise ArmyTrainingScannerError("Brak szablonu panelu lub pustego obrazu jednostki.")
    panel_template_path = resolve_asset_path(variant, panel_template_path)
    empty_unit_template_path = resolve_asset_path(variant, empty_unit_template_path)
    empty_unit_template = cv2.imread(str(empty_unit_template_path), cv2.IMREAD_COLOR)
    if empty_unit_template is None:
        raise ArmyTrainingScannerError(f"Nie można odczytać wzorca: {empty_unit_template_path}")

    speedup_template = resolve_asset_path(variant, "templates/army_training/speedup_panel.png")

    panel_score, panel_location = _locate_template(image, panel_template_path)
    panel_x, panel_y = (int(current_panel_region[key]) for key in ("x", "y"))
    unit_x, unit_y = (int(training_unit_region[key]) for key in ("x", "y"))
    unit_w, unit_h = (int(training_unit_region[key]) for key in ("w", "h"))
    unit_offset_x = unit_x - panel_x
    unit_offset_y = unit_y - panel_y
    empty_unit_score = None

    if panel_score >= 0.35:
        unit_crop = _region_crop(image, {
            "x": panel_location[0] + unit_offset_x,
            "y": panel_location[1] + unit_offset_y,
            "w": unit_w,
            "h": unit_h,
        })
        queue_state, detail_score = _classify_training_unit_image(unit_crop)
        if queue_state != "active":
            queue_state = "unknown"
    else:
        unit_crop = _region_crop(image, training_unit_region)
        empty_unit_score = float(
            cv2.matchTemplate(unit_crop, empty_unit_template, cv2.TM_CCOEFF_NORMED)[0, 0]
        )
        detail_score = float(cv2.cvtColor(unit_crop, cv2.COLOR_BGR2GRAY).std())
        queue_state = "idle" if empty_unit_score >= 0.90 else "unknown"

    speedup_crop = _region_crop(image, speedup_region)
    trained_unit_count_crop = _region_crop(image, trained_unit_count_region)

    speedup_button_detected = _template_match_score(speedup_crop, speedup_template) >= 0.85
    trained_unit_count_error = None
    try:
        trained_unit_count_reading = _ocr_numeric_crop(trained_unit_count_crop)
    except ArmyTrainingScannerError as error:
        if "Tesseract OCR" not in str(error):
            raise
        trained_unit_count_reading = {"raw": "", "value": None, "confidence": None}
        trained_unit_count_error = "tesseract_unavailable"

    return {
        "screen": screen,
        "has_active_training": True if queue_state == "active" else False if queue_state == "idle" else None,
        "speedup_button_detected": bool(speedup_button_detected),
        "trained_unit_count": trained_unit_count_reading["value"],
        "trained_unit_count_raw": trained_unit_count_reading["raw"],
        "trained_unit_count_confidence": trained_unit_count_reading["confidence"],
        "trained_unit_count_error": trained_unit_count_error,
        "training_unit_image_detail": detail_score,
        "empty_unit_template_score": empty_unit_score,
        "training_panel_match_score": panel_score,
        "status": queue_state,
    }


def main():
    parser = argparse.ArgumentParser(description="Odczytaj stan ekranu szkolenia armii bez klikania.")
    parser.add_argument("--screen", default="army_training", help="nazwa ekranu w regions.json")
    parser.add_argument("--input", required=True, help="ścieżka do pliku PNG z obrazem ekranu")
    parser.add_argument("--variant", help="wariant interfejsu; domyślnie legacy")
    args = parser.parse_args()

    try:
        snapshot = read_army_training_snapshot(args.input, screen=args.screen, variant_id=args.variant)
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0
    except (ArmyTrainingScannerError, UIVariantError, OSError, ValueError) as error:
        print(f"Błąd: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
