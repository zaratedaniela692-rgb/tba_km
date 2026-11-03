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
    template = cv2.imread(str(ROOT_DIR / template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise ArmyTrainingScannerError(f"Nie można odczytać wzorca: {template_path}")
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, best_score, _, _ = cv2.minMaxLoc(result)
    return float(best_score)


def _ocr_numeric_crop(crop):
    if crop is None or crop.size == 0:
        return None
    enlarged = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    try:
        data = pytesseract.image_to_data(thresh, config="--psm 7 -c tessedit_char_whitelist=0123456789,.", output_type=Output.DICT)
    except pytesseract.TesseractNotFoundError as error:
        raise ArmyTrainingScannerError("Nie znaleziono programu Tesseract OCR.") from error

    tokens = []
    for token in data.get("text", []):
        token = str(token).strip()
        if token:
            tokens.append(token)
    text = " ".join(tokens)
    if not text:
        return None
    cleaned = re.sub(r"[^0-9,\.]", "", text)
    if not cleaned:
        return None
    cleaned = cleaned.replace(".", "").replace(",", "")
    try:
        return int(cleaned)
    except ValueError:
        return None


def read_army_training_snapshot(image_path, screen="army_training", regions_path=REGIONS_PATH):
    """Return a safe snapshot of the army-training panel without clicking anything."""
    image = _read_image(image_path)
    regions = _load_regions(regions_path).get(screen)
    if not isinstance(regions, dict):
        raise ArmyTrainingScannerError(f"Brak regionów dla ekranu '{screen}'.")

    current_panel_region = regions.get("current_trainin_army")
    speedup_region = regions.get("speedup_panel")
    queue_region = regions.get("current_unit_troop_count")

    if current_panel_region is None:
        raise ArmyTrainingScannerError("Brak regionu 'current_trainin_army' w regions.json.")
    if speedup_region is None:
        raise ArmyTrainingScannerError("Brak regionu 'speedup_panel' w regions.json.")
    if queue_region is None:
        raise ArmyTrainingScannerError("Brak regionu 'current_unit_troop_count' w regions.json.")

    template_path = "templates/army_training/current_trainin_army.png"
    speedup_template = "templates/army_training/speedup_panel.png"

    panel_crop = _region_crop(image, current_panel_region)
    speedup_crop = _region_crop(image, speedup_region)
    queue_crop = _region_crop(image, queue_region)

    has_active_training = _template_match_score(panel_crop, template_path) >= 0.8
    speedup_button_detected = _template_match_score(speedup_crop, speedup_template) >= 0.85
    queue_count = _ocr_numeric_crop(queue_crop)

    return {
        "screen": screen,
        "has_active_training": bool(has_active_training),
        "speedup_button_detected": bool(speedup_button_detected),
        "queue_count": queue_count,
        "status": "active" if has_active_training else "idle",
    }


def main():
    parser = argparse.ArgumentParser(description="Odczytaj stan ekranu szkolenia armii bez klikania.")
    parser.add_argument("--screen", default="army_training", help="nazwa ekranu w regions.json")
    parser.add_argument("--input", required=True, help="ścieżka do pliku PNG z obrazem ekranu")
    args = parser.parse_args()

    try:
        snapshot = read_army_training_snapshot(args.input, screen=args.screen)
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0
    except (ArmyTrainingScannerError, OSError, ValueError) as error:
        print(f"Błąd: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
