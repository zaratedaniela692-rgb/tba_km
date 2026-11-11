# Shared Resource Reading Workflow

## Migration Validation Run

Executed 2026-11-10 in the workspace venv with installed Tesseract temporarily on PATH and `--continue-on-collection-errors`: resource/tool group **27 passed, 4 failed, 4 errors**. Reported failures/errors are in `test_device_test.py`, not resource OCR: missing definitions/`repo` fixture and missing speedup CLI constants. Initial execution without Tesseract on PATH also failed OCR; this environment-corrected rerun supersedes that result. Full repository: **345 passed, 19 failed, 8 errors**. This is automated fixture evidence, not live resource validation. Log: operating-system temporary directory, `tba_docs_resources_tools_ocr_20261110.log`.

## Feature Contents

- [Offline resource measurements](#offline-resource-measurements)

This area owns shared resource measurement behavior, not recruitment eligibility or spending decisions. Shared game facts remain in [mechaniki.md](mechaniki.md); visual regions and reference evidence remain in [world_map.md](../screens/world_map.md).

## Offline Resource Measurements

### Purpose and Current Behavior

Read `wood`, `iron`, `stone`, `food`, `silver`, and `gold` from an existing image. The reader is feature-agnostic: it does not capture the live screen, identify the account, click, purchase, or decide whether an action is allowed. Reading gold is not permission to spend it.

### Inputs and Defaults

- API: `read_resource_snapshot(image_path, screen="world_map", regions_path=None, config_path=CONFIG_PATH, variant_id=None)`. Region selection uses `resolve_variant`; an explicit regions path overrides the variant's regions file, but does not bypass variant resolution.
- CLI: required `--input` accepts a file or directory; a directory supplies sorted, nonrecursive `*.png` files. `--screen` defaults to `world_map`; `--variant` is optional. The help text mentions only food/silver, but the implementation reads all six counters.
- Each screen must provide all six `<resource>_count` rectangles. Every rectangle must fit the supplied image. No automatic screen recognition, alignment, scaling correction, or partial-resource mode is provided.
- Configuration defaults: `resource_ocr.minimum_confidence=70` (numeric, range 0-100) and `resource_ocr.food_color_min_pixels=20` (positive integer, excluding booleans). Despite its name, the color pixel setting applies to every resource crop.
- No reading cache, profile identity, source timestamp, or freshness guarantee is attached. Callers must associate measurements with the correct profile/source and obtain fresh data immediately before balance-dependent decisions; old image files are not current balances.

### Algorithm and Outputs

1. Resolve the variant, load region/configuration JSON, and decode the image as BGR. Process all six counters in fixed resource order; a failing counter prevents a complete snapshot return.
2. Classify color on the original crop. White pixels have all channels at least 160 and channel spread at most 80. Red pixels have red at least 100 and exceed both green and blue by at least 35. A class needs the configured minimum pixel count. If both qualify, a 1.5-times count advantage selects the dominant class; otherwise return `unknown`.
3. Enlarge the crop 4x with cubic interpolation, convert to grayscale, apply Otsu binary thresholding, and use Tesseract PSM 7 with digits, dot/comma, and `KMBT` in both cases whitelisted.
4. Strip and concatenate nonempty OCR tokens with numeric confidence at least zero. Confidence is the minimum accepted token confidence, not an average; no accepted tokens yields `None`.
5. Parse a full unsigned amount with an optional decimal dot/comma and optional case-insensitive suffix: `K=10^3`, `M=10^6`, `B=10^9`, `T=10^12`. Surrounding whitespace and whitespace before the suffix are accepted. Decimal arithmetic rounds the scaled result to an integer using `ROUND_HALF_UP`; e.g. `38,2M` becomes `38200000`, and `1000K` becomes `1000000`. Signs, thousands-grouping syntax, malformed amounts, and unsupported suffixes return `None`, not zero.

The API returns a dictionary keyed by the six resource names. Each measurement contains `raw`, `value` (integer or `None`), `color` (`white`, `red`, or `unknown`), `confidence` (number or `None`), `minimum_confidence`, and `confidence_ok`. The latter tests only confidence against the threshold: it does not require successful parsing or an acceptable color. There is no `allowed` or feature `status` field.

The CLI prints per-image measurements, including `LOW` confidence, and returns 0 even for uncertain individual readings. It returns 2 for an empty PNG directory or caught `ResourceReadError`/`UIVariantError`. File/decode errors, missing screen/region configuration, invalid supported OCR settings, out-of-bounds rectangles, and missing Tesseract have explicit error paths; this is not a guarantee that every malformed input or OCR runtime exception is normalized.

### Safety and Limitations

Uncertain OCR remains uncertain; neither `value=None` nor low confidence means an empty balance. Color is a crop-wide pixel heuristic, not segmented text recognition, and can include unrelated pixels. Numeric confidence and color are independent evidence. Consumers own their required fields, costs, and stop conditions. Recruitment-specific food/silver gates belong to the [army workflow](army_training_slot_workflow.md), not this reader.

There are no evidence-image writes in this utility. It reads offline inputs only. Existing world-map references document white food text; actual red food calibration is still missing, and synthetic red/mixed-color tests do not establish live reliability.

### Status and Verification

**Source review: 2026-11-10.** Implemented behavior above was inspected in the complete resource reader and focused test file. No Python behavior changed in this migration. Automated-test evidence is source inspection only: tests were read, not executed; no passing result is claimed. No live validation or game actions were performed.

The inspected tests cover suffix/decimal examples and malformed strings, synthetic white/red/unknown and ambiguous mixed colors, expected image readings driven by world-map JSON fixtures, all-six-resource keys, confidence flag consistency, and absence of feature decisions. Expected-image assertions apply to resources listed by each fixture, not necessarily every field of every counter. No new run establishes Tesseract availability or confidence thresholds on this machine. Error-path and alternate-variant coverage were not established by this review.

### Proposed and Deferred Changes

Live capture integration, profile/source metadata, consumer-specific preflight decisions, additional error/variant coverage, and calibration against genuine red food text remain outside this migration. Documentation approval does not authorize implementation, game input, or spending.

### Implementation and Tests

- [tools/resource_ocr.py](../../tools/resource_ocr.py): `parse_resource_amount`, `classify_text_color`, `read_resource_region`, `read_resource_snapshot`, and `main`.
- [tests/test_resource_ocr.py](../../tests/test_resource_ocr.py): parser, synthetic color, fixture-expectation, and feature-agnostic snapshot tests; inspected only.
- [world_map.md](../screens/world_map.md): region/evidence ownership and red-food evidence limitation; historical verification statements there are not new test results from this migration.