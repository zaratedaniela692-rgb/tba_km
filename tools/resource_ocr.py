#!/usr/bin/env python3
"""Read resource counters from a screenshot without performing game actions."""

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import sys

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ui_variants import UIVariantError, resolve_variant


CONFIG_PATH = ROOT_DIR / "config.json"
RESOURCE_NAMES = ("wood", "iron", "stone", "food", "silver", "gold")
SUFFIX_MULTIPLIERS = {
    "": Decimal(1),
    "K": Decimal(10) ** 3,
    "M": Decimal(10) ** 6,
    "B": Decimal(10) ** 9,
    "T": Decimal(10) ** 12,
}
AMOUNT_PATTERN = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([KMBT]?)\s*$", re.IGNORECASE)


class ResourceReadError(Exception):
    """Raised when screenshot, region, or OCR configuration cannot be used."""


def parse_resource_amount(text):
    if not isinstance(text, str):
        return None
    match = AMOUNT_PATTERN.fullmatch(text)
    if match is None:
        return None
    try:
        amount = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    multiplier = SUFFIX_MULTIPLIERS[match.group(2).upper()]
    return int((amount * multiplier).to_integral_value(rounding=ROUND_HALF_UP))


def classify_text_color(crop, min_color_pixels=20):
    if crop is None or crop.size == 0:
        return "unknown"

    pixels = crop.astype(np.int16)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    white_mask = (blue >= 160) & (green >= 160) & (red >= 160) & ((np.maximum(np.maximum(blue, green), red) - np.minimum(np.minimum(blue, green), red)) <= 80)
    red_mask = (red >= 100) & ((red - green) >= 35) & ((red - blue) >= 35)
    white_pixels = int(np.count_nonzero(white_mask))
    red_pixels = int(np.count_nonzero(red_mask))

    has_white = white_pixels >= min_color_pixels
    has_red = red_pixels >= min_color_pixels
    if has_white and has_red:
        if white_pixels >= red_pixels * 1.5:
            return "white"
        if red_pixels >= white_pixels * 1.5:
            return "red"
        return "unknown"
    if has_white:
        return "white"
    if has_red:
        return "red"
    return "unknown"


def read_image(path):
    path = Path(path)
    try:
        encoded = np.fromfile(str(path), dtype=np.uint8)
    except OSError as error:
        raise ResourceReadError(f"Nie można odczytać obrazu {path}: {error}") from error
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ResourceReadError(f"Nie można zdekodować obrazu: {path}")
    return image


def read_resource_region(image, region, min_confidence=70, min_color_pixels=20):
    x, y, width, height = (int(region[key]) for key in ("x", "y", "w", "h"))
    image_height, image_width = image.shape[:2]
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > image_width or y + height > image_height:
        raise ResourceReadError(f"Region zasobu poza obrazem: {(x, y, width, height)}")

    crop = image[y:y + height, x:x + width]
    color = classify_text_color(crop, min_color_pixels)
    enlarged = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    _, threshold = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ocr_config = "--psm 7 -c tessedit_char_whitelist=0123456789.,KMBTkmbt"
    try:
        data = pytesseract.image_to_data(threshold, config=ocr_config, output_type=Output.DICT)
    except pytesseract.TesseractNotFoundError as error:
        raise ResourceReadError("Nie znaleziono programu Tesseract OCR.") from error

    tokens = []
    confidences = []
    for token, confidence in zip(data["text"], data["conf"]):
        token = token.strip()
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            continue
        if token and confidence >= 0:
            tokens.append(token)
            confidences.append(confidence)

    raw = "".join(tokens)
    confidence = min(confidences) if confidences else None
    value = parse_resource_amount(raw)
    return {
        "raw": raw,
        "value": value,
        "color": color,
        "confidence": confidence,
        "minimum_confidence": float(min_confidence),
        "confidence_ok": confidence is not None and confidence >= min_confidence,
    }


def read_resource_snapshot(image_path, screen="world_map", regions_path=None, config_path=CONFIG_PATH, variant_id=None):
    variant = resolve_variant(variant_id)
    regions_path = Path(regions_path) if regions_path is not None else variant["regions"]
    try:
        regions_data = json.loads(Path(regions_path).read_text(encoding="utf-8"))
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ResourceReadError(f"Nie można odczytać konfiguracji: {error}") from error

    screen_regions = regions_data.get(screen)
    if not isinstance(screen_regions, dict):
        raise ResourceReadError(f"Brak regionów dla ekranu '{screen}'.")
    ocr_config = config.get("resource_ocr", {})
    if not isinstance(ocr_config, dict):
        raise ResourceReadError("Pole 'resource_ocr' w config.json musi być obiektem.")
    min_confidence = ocr_config.get("minimum_confidence", 70)
    min_color_pixels = ocr_config.get("food_color_min_pixels", 20)
    if not isinstance(min_confidence, (int, float)) or not 0 <= min_confidence <= 100:
        raise ResourceReadError("resource_ocr.minimum_confidence musi należeć do zakresu 0-100.")
    if isinstance(min_color_pixels, bool) or not isinstance(min_color_pixels, int) or min_color_pixels < 1:
        raise ResourceReadError("resource_ocr.food_color_min_pixels musi być dodatnią liczbą całkowitą.")

    image = read_image(image_path)
    result = {}
    for name in RESOURCE_NAMES:
        region_name = f"{name}_count"
        region = screen_regions.get(region_name)
        if not isinstance(region, dict):
            raise ResourceReadError(f"Brak regionu '{region_name}' dla ekranu '{screen}'.")
        result[name] = read_resource_region(image, region, min_confidence, min_color_pixels)

    return result


def main():
    parser = argparse.ArgumentParser(description="Odczytaj food i silver z obrazu bez klikania w grze.")
    parser.add_argument("--screen", default="world_map", help="nazwa ekranu w regions.json")
    parser.add_argument("--input", required=True, help="plik PNG albo folder PNG")
    parser.add_argument("--variant", help="wariant interfejsu; domyślnie legacy")
    args = parser.parse_args()

    input_path = Path(args.input)
    images = sorted(input_path.glob("*.png")) if input_path.is_dir() else [input_path]
    if not images:
        print(f"Błąd: brak plików PNG w {input_path}", file=sys.stderr)
        return 2

    try:
        for image_path in images:
            reading = read_resource_snapshot(image_path, args.screen, variant_id=args.variant)
            print(f"\n{image_path.name}")
            for name in RESOURCE_NAMES:
                item = reading[name]
                confidence = "brak" if item["confidence"] is None else f"{item['confidence']:.0f}%"
                confidence_state = "OK" if item["confidence_ok"] else "LOW"
                print(
                    f"  {name}: raw={item['raw']!r}, value={item['value']}, "
                    f"color={item['color']}, OCR={confidence} ({confidence_state}, "
                    f"min={item['minimum_confidence']:.0f}%)"
                )
    except (ResourceReadError, UIVariantError) as error:
        print(f"Błąd: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
