# Desktop and Browser UI Support Plan

## Purpose

Prepare the project for two client surfaces: keep the current desktop application UI unchanged, and support the updated browser UI as a separate target after it is available and stable. The updated UI replaces the browser game's current UI; it does not replace the UI used by the desktop application. Keep game behavior and task planning independent from visual layout, coordinates, templates, and screen-specific recognition.

This document is a plan only. It does not declare browser UI support implemented or verified.

## Goals

- Preserve the existing desktop application interface and workflows unchanged.
- Treat browser and desktop as separate client targets, so regions and templates from one client can never silently be used for the other.
- Add browser-interface recognition screen by screen after its visuals stabilize.
- Reuse logical screen and element identifiers where the underlying game behavior is the same.
- Keep screenshots, regions, templates, and verification fixtures associated with their client.
- Eventually select the client per game profile/window, independently of other profiles.

## Non-goals

- Do not change or replace the existing desktop application UI as part of browser support.
- Do not implement browser-interface coordinates, templates, OCR regions, or game flows until representative browser screenshots are provided and verified.
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

The exact file layout is to be confirmed during implementation. Existing files must remain usable during migration; moving them is not required for the first step. A client registry should map each client ID to its region, template, screenshot, and verification roots, plus an explicit readiness state. The intended targets are `desktop` (current assets, ready) and `browser` (planned, no usable regions until captured and verified).

Current implementation status: the first technical iteration still uses IDs `legacy` and `modern`: `legacy` points at the current desktop assets and `modern` is planned and unavailable. `ui_variants.py` validates selection and constrains resolved paths; the verifier, annotator, army-training scanner, and resource OCR tool accept an optional variant and default to `legacy`. This is transitional naming from the earlier version-based assumption. Before browser support is implemented, migrate the registry and CLI terminology to client-based IDs `desktop` and `browser`, keeping `desktop` mapped to the current assets. No browser assets or flows have been added. The annotator refuses unavailable targets. Profile-level selection remains unimplemented.

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

Status: partially implemented. A shared resolver exists, but its `legacy` / `modern` IDs reflect the superseded version-based assumption and need a deliberate migration to client-based IDs. Profile-level selection is deferred because profile configuration does not yet exist.

### Phase 2: Client-aware read-only tooling

- Add an explicit client option to annotation, verification, and army-training scanning tools.
- Make omitted client selection preserve existing desktop behavior.
- Route reads and writes only through the selected client's configured paths.
- Reject writes to clients or screens that are marked unavailable unless explicitly initialized for annotation.
- Add tests proving desktop defaults remain unchanged and client paths cannot cross-contaminate.

Status: in progress. Read-only tools resolve current desktop regions/templates through the registry and reject planned clients. The annotator routes saves through configured roots but currently accepts only ready clients; adding an explicit safe initialization flow for browser assets remains open.

### Phase 3: Desktop baseline

- Register existing desktop assets under `desktop` without changing their image contents or recognition thresholds.
- Run regression verification on existing fixtures and record the baseline.
- Change asset paths only after parity tests pass; this migration can be deferred if it creates unnecessary churn.

### Phase 4: Browser visual inventory

- Wait for representative browser-client screenshots and note browser/version, window crop, resolution, DPI, zoom, account/profile, and relevant UI states.
- Inventory screens and controls without assuming one-to-one mappings.
- Annotate browser assets into the browser client only.
- Mark a screen or element verified only after regression fixtures cover its relevant states.

### Phase 5: Incremental browser feature support

- Add browser recognition for one screen/flow at a time.
- Reuse the same domain behavior and task model where semantics match.
- Implement a client-specific adapter only when recognition or interaction behavior genuinely differs.
- Keep all actions disabled or in dry-run until screen recognition and expected transitions are verified.

## Acceptance Criteria for the Preparation Step

- Existing desktop behavior remains the default when no client is specified.
- Browser is independently selectable when initialized and cannot accidentally use desktop assets.
- Tooling has a single, explicit asset-resolution boundary rather than constructing client paths independently.
- Tests cover default selection, explicit selection, unknown client, unavailable screen, and no cross-client fallback.
- Desktop verification output remains at the existing `debug/verify/` path.
- No browser coordinates or templates are invented before representative browser screenshots exist.
- Documentation makes clear that browser UI support is not yet implemented and desktop UI remains unchanged.

## Open Decisions for Implementation

- Whether to move desktop assets immediately or keep their existing paths behind the registry until a later cleanup.
- Whether to rename registry IDs and CLI options from the initial `legacy` / `modern` implementation to `desktop` / `browser` in one migration or through a compatibility period.
- The exact profile configuration field and migration behavior for existing profiles.
- Whether annotation initializes a planned variant automatically or requires a separate explicit initialization command.
- The capture normalization strategy for different window sizes and UI scaling; coordinates remain relative to a verified game-window capture.

## Related References

- Repository workflow and scope rules: `AGENTS.md`
- Screen-specific recognition: `docs/screens/`
- Capture and display configuration: `docs/game/konfiguracja.md`
- Game behavior independent of appearance: `docs/game/mechaniki.md`
