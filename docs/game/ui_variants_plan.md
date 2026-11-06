# Desktop and Browser UI Support Plan

## Purpose

Prepare the project for two client surfaces: keep the current desktop application UI unchanged, and support the updated browser UI as a separate target after it is available and stable. The updated UI replaces the browser game's current UI; it does not replace the UI used by the desktop application. Keep game behavior and task planning independent from visual layout, coordinates, templates, and screen-specific recognition.

This document tracks the incremental browser-support plan and current verification status. Browser support is implemented only for the read-only army-training slot geometry and OCR covered by the fixture below; it does not imply general browser UI or action support.

## Browser screenshot received: army training

The repository now contains `screenshots/zrzut_pulpitu_website.png`, a 1920x1080 capture showing Chrome and the Barracks screen. It includes browser chrome. The desktop reference `screenshots/army_training/pelny_army_training_empty_queue.png` is also 1920x1080. Probing the browser capture with existing templates found several controls at full template scale; the three Train buttons were detected at `(775,774)`, `(1036,774)`, and `(1297,774)`. Thus, at least this capture appears to preserve the desktop slot size and stride while shifting the panel. This is candidate evidence for this screenshot only, not verified support across browser sizes, zooms, or states.

Confirmed:
- Both captures show the Barracks/training screen and are 1920x1080 image files.
- The browser capture includes the browser frame; it is not a game-window-only crop.
- The isolated browser regression fixture is `ui/browser/tests/army_training/zrzut_pulpitu_website.png`.
- Existing desktop templates match several browser controls at their original scale; three Train anchors and slider tracks align at the expected 261-pixel stride.
- The registry exposes `desktop` and `browser`; the desktop path/default is unchanged, and `legacy` is a compatibility alias.

Assumptions, not verified:
- The visible controls have equivalent behavior in browser and desktop.
- The received browser capture represents a stable browser layout and its intended zoom.

Deferred:
- Browser window-only capture and its client-area dimensions, browser zoom, and Windows DPI.
- Other browser screen states, resolutions, and zoom levels.
- Any game clicks or live browser execution.
- Browser speedup control and resource preflight.

First browser screen contract (user asked the assistant to attempt as much matching as possible, with later correction for uncertain elements):
- Scope is read-only recognition of `army_training` only.
- Keep all current desktop assets, defaults, and behavior unchanged.
- Store browser regions, templates, screenshots, and expected results separately; never fall back to desktop assets.
- Existing desktop regions/templates may be used as computer-vision search references to propose browser candidates. A match is only a candidate, not confirmation; do not copy desktop coordinates/templates or assume same position/scale. Persist only browser-specific coordinates and crops where the candidate is unambiguous and regression-testable.
- Leave missing/ambiguous matches unconfigured for user correction; do not infer coordinates from visual inspection.
- Use the received screenshot as a browser fixture. A screen/element is not `verified` beyond the detections covered by passing regression checks. This single capture does not establish support across sizes or states.
- Read-only probing detected three aligned slots and read queue limits, city counts, and silver costs per slot. Selector-level reading remains unknown; speedup state and resource preflight are unsupported.
- Active/non-active fixtures are now tested by the browser scanner. At the configured ROI, active detail is 57.665; idle detail is 2.053 with empty-template score 1.0. Other or conflicting evidence returns `unknown`. These thresholds have only been exercised on the supplied pair.

Flow:

```text
browser screenshot
  -> explicitly selected browser asset set
  -> use desktop templates only to propose candidate matches
  -> create browser-only regions/templates for clear candidates
  -> run read-only slot/OCR/state recognition and regression
  -> pass: mark only covered elements verified
  -> ambiguous/fail/missing evidence: keep unknown/unverified; no desktop fallback; request correction
```

Current code status: browser variant is selectable and has isolated regions, templates, screenshots/test roots, and verification output. `army_training_slots.py` detects all three slots in the browser fixture; `army_training_slot_reader.py` reads their queue limits, city counts, and silver costs. The browser scanner classifies `active`/`idle`/`unknown` from the state ROI using the active/non-active fixtures; speedup and trained-count data remain unsupported. Regression tests cover browser state, path isolation, and the unchanged desktop baseline. `tools.verify.py` passes on the original fixture, but its 100% template scores are expected because those templates are crops from that same image. Level semantics, resources, other screens/sizes, window capture, and game actions are not supported.

## Goals

- Preserve the existing desktop application interface and workflows unchanged.
- Treat browser and desktop as separate client targets, so regions and templates from one client can never silently be used for the other.
- Add browser-interface recognition screen by screen after its visuals stabilize.
- Reuse logical screen and element identifiers where the underlying game behavior is the same.
- Keep screenshots, regions, templates, and verification fixtures associated with their client.
- Eventually select the client per game profile/window, independently of other profiles.

## Non-goals

- Do not change or replace the existing desktop application UI as part of browser support.
- Do not infer additional browser coordinates, templates, OCR regions, or game flows beyond the states covered by representative screenshots and regression checks.
- Do not duplicate or change the training planner, task queue, or business rules solely to support a different appearance.
- Do not assume that a visual control has the same location, shape, state, or behavior in both clients.
- Do not migrate all existing assets as part of the initial preparation step.

## Proposed Organization

Keep shared behavior and logical identifiers separate from visual assets. A future layout may use client-specific folders such as:

```text
ui/
  desktop/
    regions.json
    templates/
    screenshots/
    tests/
  browser/
    regions.json
    templates/
    screenshots/
    tests/
```

The active registry maps `desktop` to current root-level assets and `browser` to isolated `ui/browser/` assets. Desktop files were not moved. Browser regression screenshots and verification output are also client-specific.

Current implementation status: `desktop` is the default and `legacy` resolves to the same desktop assets for compatibility. `browser` resolves only to browser roots. `modern` remains planned/unavailable. The resolver constrains paths; the verifier, annotator, army-training scanner, slot detector, and resource OCR tool accept a variant. The annotator writes only through the selected variant's roots. Profile-level selection remains unimplemented.

## Selection and Isolation Rules

- Use stable client IDs such as `desktop` and `browser`; do not use release labels as client identity.
- Existing commands and profiles must continue to use the current desktop UI by default.
- Permit explicit CLI client selection for tooling and tests.
- Store the selected client per profile/window when profile configuration is introduced or extended.
- Resolve every screen's regions and templates through the selected client registry.
- If a client or required screen is missing or not ready, fail with a clear error. Never fall back from browser to desktop assets implicitly.
- Keep profile state isolated: the active client, captures, OCR, caches, and recognition results must not leak between windows/accounts.

## Documentation Model

- Keep screen documentation centered on logical purpose, state transitions, and behavior.
- Record visual differences and capture-specific details under the relevant client subsection or linked client screen card.
- Track each screen/element as `planned`, `captured`, `annotated`, `verified`, or `implemented` per client.
- Treat a screenshot as evidence only for its actual client, resolution, scale, and window context.
- Record unresolved observations explicitly rather than inferring browser behavior from desktop screenshots.

## Phased Work

### Phase 1: Inventory and compatibility contract

- List the current region, template, screenshot, and regression-test locations.
- Define the client registry schema and readiness semantics for desktop and browser.
- Confirm how the selected client will be stored per profile without storing credentials.
- Keep current desktop commands and asset paths working unchanged during transition.

Status: implemented for explicit `desktop`/`browser` IDs and a compatibility `legacy` alias. Profile-level selection is deferred because profile configuration does not yet exist.

### Phase 2: Client-aware read-only tooling

- Add an explicit client option to annotation, verification, and army-training scanning tools.
- Make omitted client selection preserve existing desktop behavior.
- Route reads and writes only through the selected client's configured paths.
- Reject writes to clients or screens that are marked unavailable unless explicitly initialized for annotation.
- Add tests proving desktop defaults remain unchanged and client paths cannot cross-contaminate.

Status: in progress. Read-only tools resolve assets through the selected variant and do not fall back across clients. Browser army-training slot detection, OCR, and active/idle/unknown state classification are fixture-tested; resource scanning and other screens remain open.

### Phase 3: Desktop baseline

- Register existing desktop assets under `desktop` without changing their image contents or recognition thresholds.
- Run regression verification on existing fixtures and record the baseline.
- Change asset paths only after parity tests pass; this migration can be deferred if it creates unnecessary churn.

Status: current desktop paths and default behavior remain unchanged; focused desktop regression tests pass. No asset move was needed.

### Phase 4: Browser visual inventory

- Wait for representative browser-client screenshots and note browser/version, window crop, resolution, DPI, zoom, account/profile, and relevant UI states.
- Inventory screens and controls without assuming one-to-one mappings.
- Annotate browser assets into the browser client only.
- Mark a screen or element verified only after regression fixtures cover its relevant states.

Status: the initial browser army-training capture and one active/idle pair are stored as fixtures. Empty-queue slot geometry, per-slot OCR, and active/idle/unknown ROI classification pass. Alternate scale/window and level-selection states still need representative captures.

### Phase 5: Incremental browser feature support

- Add browser recognition for one screen/flow at a time.
- Reuse the same domain behavior and task model where semantics match.
- Implement a client-specific adapter only when recognition or interaction behavior genuinely differs.
- Keep all actions disabled or in dry-run until screen recognition and expected transitions are verified.

Status: read-only browser slot/OCR and active-state classification implemented; no browser action flow is enabled.

## Acceptance Criteria for the Preparation Step

- Existing desktop behavior remains the default when no client is specified.
- Browser is independently selectable when initialized and cannot accidentally use desktop assets.
- Tooling has a single, explicit asset-resolution boundary rather than constructing client paths independently.
- Tests cover default selection, explicit selection, unknown client, unavailable screen, and no cross-client fallback.
- Desktop verification output remains at the existing `debug/verify/` path.
- Browser coordinates/templates are stored separately and tied to the supplied fixture.
- Documentation makes clear that only the tested browser slice is implemented and desktop UI remains unchanged.

## Open Decisions for Implementation

- Whether to move desktop assets immediately or keep their existing paths behind the registry until a later cleanup.
- The exact profile configuration field and migration behavior for existing profiles.
- The capture normalization strategy for different window sizes and UI scaling; coordinates remain relative to a verified game-window capture.

## Related References

- Repository workflow and scope rules: `AGENTS.md`
- Screen-specific recognition: `docs/screens/`
- Capture and display configuration: `docs/game/konfiguracja.md`
- Game behavior independent of appearance: `docs/game/mechaniki.md`
