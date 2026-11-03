#!/usr/bin/env python3
"""Verify annotated screen templates against PNG screenshots."""

import argparse
import json
import math
import sys
import unicodedata
from pathlib import Path

import cv2
import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[1]
REGIONS_PATH = ROOT_DIR / "regions.json"
CONFIG_PATH = ROOT_DIR / "config.json"
OUTPUT_DIR = ROOT_DIR / "debug" / "verify"


class VerificationError(Exception):
    pass


def load_json(path, description):
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"Nie można odczytać {description} ({path}): {error}") from error


def read_image(path):
    try:
        encoded = np.fromfile(str(path), dtype=np.uint8)
    except OSError as error:
        raise VerificationError(f"Nie można odczytać obrazu {path}: {error}") from error
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise VerificationError(f"Nie można zdekodować obrazu: {path}")
    return image


def write_image(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise VerificationError(f"Nie można zakodować obrazu wynikowego: {path}")
    try:
        path.write_bytes(encoded.tobytes())
    except OSError as error:
        raise VerificationError(f"Nie można zapisać obrazu wynikowego {path}: {error}") from error


def validate_threshold(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
        raise VerificationError(f"Próg '{label}' musi być liczbą z zakresu 0-100.")
    return float(value)


def get_threshold(config, screen, element):
    default = validate_threshold(config.get("default_min_confidence"), "default_min_confidence")
    screens = config.get("screens", {})
    if not isinstance(screens, dict):
        raise VerificationError("Pole 'screens' w config.json musi być obiektem.")
    screen_config = screens.get(screen, {})
    if not isinstance(screen_config, dict):
        raise VerificationError(f"Konfiguracja progów dla ekranu '{screen}' musi być obiektem.")
    if element not in screen_config:
        return default
    return validate_threshold(screen_config[element], f"screens.{screen}.{element}")


def load_templates(regions, screen, config):
    screens = regions.get(screen)
    if not isinstance(screens, dict) or not screens:
        raise VerificationError(f"Brak elementów dla ekranu '{screen}' w regions.json.")

    templates = []
    for name, region in screens.items():
        if not isinstance(region, dict):
            raise VerificationError(f"Brak poprawnego wpisu lub ścieżki template dla elementu '{name}'.")
        if region.get("type") == "number":
            continue
        if "template" not in region:
            raise VerificationError(f"Brak poprawnego wpisu lub ścieżki template dla elementu '{name}'.")
        template_path = Path(region["template"])
        if not template_path.is_absolute():
            template_path = ROOT_DIR / template_path
        template = read_image(template_path)
        threshold = get_threshold(config, screen, name)
        templates.append((name, region, template, threshold))
    return templates


def match_template(image, template):
    image_height, image_width = image.shape[:2]
    template_height, template_width = template.shape[:2]
    if template_height > image_height or template_width > image_width:
        return None, None

    result = cv2.matchTemplate(image, template, cv2.TM_SQDIFF_NORMED)
    min_error, _, min_location, _ = cv2.minMaxLoc(result)
    if not math.isfinite(min_error):
        return None, None
    confidence = max(0.0, min(100.0, (1.0 - min_error) * 100.0))
    return confidence, min_location


def display_label(value):
    value = value.replace("ł", "l").replace("Ł", "L")
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def draw_result(image, number, region, template, confidence, threshold, location):
    output = image.copy()
    image_height, image_width = output.shape[:2]
    template_height, template_width = template.shape[:2]

    if location is None:
        x = max(0, min(image_width - 1, int(region.get("x", 0))))
        y = max(0, min(image_height - 1, int(region.get("y", 0))))
        box_width = max(1, min(template_width, image_width - x))
        box_height = max(1, min(template_height, image_height - y))
        status = "BRAK DOPASOWANIA"
        color = (0, 0, 230)
    else:
        x, y = location
        box_width = template_width
        box_height = template_height
        passed = confidence >= threshold
        status = "OK" if passed else "PONIŻEJ PROGU"
        color = (40, 180, 40) if passed else (0, 0, 230)

    cv2.rectangle(output, (x, y), (x + box_width - 1, y + box_height - 1), color, 2)
    marker_top = max(0, y - 18)
    marker_right = min(image_width - 1, x + 19)
    cv2.rectangle(output, (x, marker_top), (marker_right, min(image_height - 1, marker_top + 17)), color, -1)
    cv2.putText(output, str(number), (x + 3, marker_top + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return output, status


def add_legend(image, results):
    image_height, image_width = image.shape[:2]
    line_height = 25
    legend_height = 12 + len(results) * line_height
    output = np.full((image_height + legend_height, image_width, 3), (28, 28, 28), dtype=np.uint8)
    output[:image_height] = image

    for index, result in enumerate(results, start=1):
        if result["confidence"] is None:
            confidence = "brak dopasowania"
        else:
            confidence = f"{result['confidence']:.1f}%"
        label = (
            f"{index}. {display_label(result['name'])}: {confidence} "
            f"(min {result['threshold']:.1f}%) - {result['status']}"
        )
        color = (40, 180, 40) if result["status"] == "OK" else (0, 0, 230)
        baseline = image_height + 20 + (index - 1) * line_height
        cv2.putText(output, label, (12, baseline), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)
    return output


def verify_image(image_path, screen, templates):
    image = read_image(image_path)
    output = image.copy()
    results = []
    for number, (name, region, template, threshold) in enumerate(templates, start=1):
        confidence, location = match_template(image, template)
        output, status = draw_result(output, number, region, template, confidence, threshold, location)
        results.append({
            "name": name,
            "confidence": confidence,
            "threshold": threshold,
            "location": location,
            "status": status,
        })

    output = add_legend(output, results)
    output_path = OUTPUT_DIR / screen / image_path.name
    write_image(output_path, output)
    return results, output_path


def run(screen, input_dir, regions_path=REGIONS_PATH, config_path=CONFIG_PATH):
    if not input_dir.is_dir():
        raise VerificationError(f"Folder wejściowy nie istnieje: {input_dir}")

    regions = load_json(regions_path, "regions.json")
    config = load_json(config_path, "config.json")
    if not isinstance(regions, dict) or not isinstance(config, dict):
        raise VerificationError("regions.json i config.json muszą zawierać obiekty JSON.")
    templates = load_templates(regions, screen, config)
    inputs = sorted(path for path in input_dir.iterdir() if path.is_file() and path.suffix.lower() == ".png")
    if not inputs:
        raise VerificationError(f"Nie znaleziono plików PNG w folderze: {input_dir}")

    for image_path in inputs:
        results, output_path = verify_image(image_path, screen, templates)
        print(f"\n{image_path.name}")
        for item in results:
            confidence = "brak" if item["confidence"] is None else f"{item['confidence']:.1f}%"
            position = "brak" if item["location"] is None else f"({item['location'][0]}, {item['location'][1]})"
            print(
                f"  {item['name']}: zgodność={confidence}, próg={item['threshold']:.1f}%, "
                f"pozycja={position}, status={item['status']}"
            )
        print(f"  wynik: {output_path.relative_to(ROOT_DIR)}")


def main():
    parser = argparse.ArgumentParser(description="Weryfikuj szablony ekranu na zrzutach PNG.")
    parser.add_argument("--screen", required=True, help="nazwa ekranu z regions.json")
    parser.add_argument("--input", required=True, help="folder zawierający wejściowe pliki PNG")
    parser.add_argument("--regions", default=str(REGIONS_PATH), help="ścieżka do regions.json")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="ścieżka do config.json z progami")
    args = parser.parse_args()

    try:
        run(args.screen, Path(args.input), Path(args.regions), Path(args.config))
    except VerificationError as error:
        print(f"Błąd: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
