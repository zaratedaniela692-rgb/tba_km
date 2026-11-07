"""Build a viewport-relative map of owned speedup Use buttons from checkpoints."""

import argparse
import json
import sys
from pathlib import Path

import cv2

from speedup_calibration import dialog_anchor_matches, load_speedup_regions
from speedup_readings import parse_duration

ROOT_DIR = Path(__file__).resolve().parent
REGIONS_PATH = ROOT_DIR / "regions.json"
CHECKPOINT_STEPS = (3, 11, 16)
CHECKPOINT_BUTTON_DURATIONS = {
    3: ("15m", "1h", "3h", "8h"),
    11: ("15h", "1d", "3d"),
    16: ("3d", "7d", "30d"),
}
MIN_MATCH_SCORE = 0.95


class ButtonMapError(ValueError):
    """The checkpoint evidence cannot produce an unambiguous button map."""


def locate_use_buttons(image, viewport, template, threshold=MIN_MATCH_SCORE):
    """Return complete, non-overlapping Use-button matches in top-to-bottom order."""
    left, top, width, height = (int(viewport[key]) for key in ("x", "y", "w", "h"))
    crop = image[top:top + height, left:left + width]
    if crop.shape[:2] != (height, width):
        raise ButtonMapError("inventory viewport is outside the checkpoint image")
    if template.shape[0] > height or template.shape[1] > width:
        raise ButtonMapError("Use-button template is larger than the inventory viewport")

    scores = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    template_height, template_width = template.shape[:2]
    matches = []
    while True:
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score < threshold:
            break
        matches.append({
            "x": left + int(x),
            "y": top + int(y),
            "width": template_width,
            "height": template_height,
            "confidence": float(score),
        })
        scores[
            max(0, y - template_height + 1):min(scores.shape[0], y + template_height),
            max(0, x - template_width + 1):min(scores.shape[1], x + template_width),
        ] = -1.0
    return sorted(matches, key=lambda match: (match["y"], match["x"]))


def build_button_map(checkpoint_images, viewport, template, button_template_path, threshold=MIN_MATCH_SCORE):
    """Associate complete matches with the visually confirmed checkpoint durations."""
    if set(checkpoint_images) != set(CHECKPOINT_STEPS):
        raise ButtonMapError(f"expected checkpoint images for steps {CHECKPOINT_STEPS}")

    viewport_width = int(viewport["w"])
    viewport_height = int(viewport["h"])
    mapped_checkpoints = []
    preferred_scrolls = {}
    for step in CHECKPOINT_STEPS:
        matches = locate_use_buttons(checkpoint_images[step], viewport, template, threshold)
        durations = CHECKPOINT_BUTTON_DURATIONS[step]
        if len(matches) != len(durations):
            raise ButtonMapError(
                f"checkpoint {step}: expected {len(durations)} complete Use buttons, found {len(matches)}"
            )

        buttons = []
        for duration_label, match in zip(durations, matches):
            reading = parse_duration(duration_label, 100.0)
            if reading.value is None:
                raise ButtonMapError(f"invalid known duration label: {duration_label}")
            relative_x = match["x"] - int(viewport["x"])
            relative_y = match["y"] - int(viewport["y"])
            rectangle = {
                "x": relative_x,
                "y": relative_y,
                "width": match["width"],
                "height": match["height"],
            }
            button = {
                "duration_label": duration_label,
                "duration_seconds": reading.value,
                "rectangle": rectangle,
                "center": {
                    "x": relative_x + match["width"] // 2,
                    "y": relative_y + match["height"] // 2,
                },
                "match_confidence": round(match["confidence"], 4),
            }
            buttons.append(button)
            preferred_scrolls.setdefault(duration_label, step)
        mapped_checkpoints.append({"scroll_count": step, "buttons": buttons})

    return {
        "schema_version": 1,
        "coordinate_space": "speedup_inventory_viewport",
        "viewport_size": {"width": viewport_width, "height": viewport_height},
        "button_template": str(button_template_path).replace("\\", "/"),
        "minimum_match_score": threshold,
        "duration_labels_source": "visually_reviewed_checkpoint_screenshots",
        "checkpoints": mapped_checkpoints,
        "preferred_scroll_count_by_duration": preferred_scrolls,
    }


def create_button_map(checkpoint_dir, regions_path=REGIONS_PATH, root_dir=ROOT_DIR):
    """Load a completed calibration run, validate its frames, and build its map."""
    checkpoint_dir = Path(checkpoint_dir)
    manifest_path = checkpoint_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ButtonMapError(f"could not read checkpoint manifest: {error}") from error
    if manifest.get("mode") != "checkpoint" or manifest.get("status") != "CHECKPOINTS_CAPTURED":
        raise ButtonMapError("input directory is not a completed checkpoint calibration")

    regions = load_speedup_regions(regions_path)
    button_template_path = Path(root_dir) / regions["speedup_use_button"]["template"]
    template = cv2.imread(str(button_template_path))
    if template is None:
        raise ButtonMapError(f"could not load Use-button template: {button_template_path}")

    captures = {entry.get("step"): entry for entry in manifest.get("checkpoints", [])}
    if tuple(sorted(captures)) != CHECKPOINT_STEPS:
        raise ButtonMapError(f"manifest checkpoints must be exactly {CHECKPOINT_STEPS}")

    expected_size = tuple(manifest.get("expected_frame_size", ()))
    images = {}
    for step in CHECKPOINT_STEPS:
        path = checkpoint_dir / captures[step].get("file", "")
        image = cv2.imread(str(path))
        if image is None:
            raise ButtonMapError(f"could not read checkpoint image: {path}")
        frame_size = (int(image.shape[1]), int(image.shape[0]))
        if frame_size != expected_size:
            raise ButtonMapError(f"checkpoint {step} has unexpected frame size {frame_size}")
        if not dialog_anchor_matches(image, regions=regions, root_dir=root_dir):
            raise ButtonMapError(f"speedup dialog anchor not recognized at checkpoint {step}")
        images[step] = image

    button_map = build_button_map(
        images,
        regions["speedup_inventory_viewport"],
        template,
        regions["speedup_use_button"]["template"],
    )
    button_map["source_run"] = checkpoint_dir.name
    button_map["source_started_at"] = manifest.get("started_at")
    return button_map


def main(argv=None):
    parser = argparse.ArgumentParser(description="Map owned speedup Use buttons from approved checkpoint screenshots.")
    parser.add_argument("--input-dir", required=True, help="completed checkpoint calibration directory")
    parser.add_argument("--output", type=Path, default=ROOT_DIR / "speedup_button_map.json")
    args = parser.parse_args(argv)

    try:
        button_map = create_button_map(args.input_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(button_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ButtonMapError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error)}, ensure_ascii=False))
        return 2

    print(json.dumps({"status": "MAPPED", "output": str(args.output), "durations": button_map["preferred_scroll_count_by_duration"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())