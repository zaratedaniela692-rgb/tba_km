# Desktop and Browser UI Support Plan

## Purpose

Keep the desktop application unchanged and develop browser recognition as a separate client target. The current implementation includes an observe-only foreground client/profile router; browser visual identity and queue execution remain unavailable until their own assets and flows are verified. Keep game behavior and task planning independent from visual layout, coordinates, templates, and screen-specific recognition.

This document is a plan only. It does not declare browser UI support implemented or verified.

## Goals

- Preserve the existing desktop application interface and workflows unchanged.
- Treat browser and desktop as separate client targets, so regions and templates from one client can never silently be used for the other.
- Add browser-interface recognition screen by screen after its visuals stabilize.
- Reuse logical screen and element identifiers where the underlying game behavior is the same.
- Keep screenshots, regions, templates, and verification fixtures associated with their client.
- Eventually select the client per game profile/window, independently of other profiles.
- Select the foreground client independently from the account profile and report the unique profile/queue route without mixing per-profile state.
The exact file layout is to be confirmed during implementation. Existing files remain usable during migration. The registry maps each client ID to its region, template, screenshot, and verification roots, plus an explicit readiness state. `legacy` is the current ready desktop asset set; `browser` is registered but planned/unavailable until its independent identity and screen assets are verified.

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

Current implementation uses transitional IDs `legacy` (ready desktop assets), `modern` (planned), and `browser` (planned/unavailable). `ui_variants.py` validates selection and constrains resolved paths. `client_router.py` classifies the foreground window and resolves a desktop player name only when it maps uniquely to an existing profile. It reports Chrome as browser but blocks profile routing because no browser-specific player-name region is verified. It is read-only and does not access or execute queues. The manager's one-shot `--profile auto` flow remains separate. Profile/window selection for task execution and browser screen flows are not implemented.

## Selection and Isolation Rules

- Use stable client IDs such as `desktop` and `browser`; do not use release labels as client identity.
- Existing commands and profiles must continue to use the current desktop UI by default.
- Permit explicit CLI client selection for tooling and tests.
- Store the selected client per profile/window when profile configuration is introduced or extended.
- Resolve every screen's regions and templates through the selected client registry.
- If a client or required screen is missing or not ready, fail with a clear error. Never fall back from browser to desktop assets implicitly.
- Keep profile state isolated: the active client, captures, OCR, caches, and recognition results must not leak between windows/accounts.

## Foreground Client and Account Queue Routing (Approved 2026-11-07)

### Goal and scope

When the operator manually switches the foreground game between the desktop client and Chrome, route work only to the queue belonging to the visibly identified player account. Client identity selects the visual asset set; player identity selects the local profile and queue. These are separate values. This first implementation is an observe-only router and must not click, scroll, start tasks, or mutate queues.

### Contract and algorithm

1. Observe the foreground top-level window on the primary monitor. Classify it as the supported desktop client, Chrome with the Total Battle tab active, or `not_game`. Do not infer the browser client merely because Chrome is open in the background. Unknown titles/processes are `unknown`.
2. Resolve a ready client-specific asset set. Desktop remains `legacy` during this migration. Browser recognition is not ready until its independent player-name and army-training regions/templates are registered and verified; never fall back to desktop assets.
3. Capture a fresh 1920x1080 primary-monitor frame and OCR the visible player name using that client's explicitly annotated region. Require the configured independent reads to agree. Preserve the client ID, window evidence, raw OCR candidates, normalized player name, timestamp, and confidence/status.
4. Map the exact normalized player name to one pre-registered profile ID. Do not generate a new profile during the polling loop and do not prompt repeatedly. Zero or multiple mappings return `profile_unresolved`; the router performs no queue read or action. Existing one-shot `--profile auto` creation/selection remains a setup operation, not a continuous dispatcher.
5. Before each future task/action dispatch, recheck foreground client and player identity. A client/profile change suspends dispatch for the previous profile and resolves the newly visible profile before reading its queue. A change during an action blocks subsequent actions; an uncertain result is reconciled only against the profile that owned that action.
6. This phase reports the resolved `{client_id, player_name, profile_id}` and queue path only. Queue execution, click adapters, browser training actions, multi-window parallelism, and automatic recovery are deferred until the observe-only router passes its fixtures and a separately approved supervised test.

### Confirmed evidence and assumptions

- Confirmed: both supplied desktop and browser examples show the player name in the upper HUD; the desktop fixture identifies `xirrus` and `snoweye`, and the browser fixture shows a different name. The browser test fixtures are 1920x1080.
- Confirmed from current code: `profile_identity.py` captures the primary monitor and OCRs the `legacy` `world_map.player_name` region; it does not identify foreground-window client type or run a polling loop. The manager's `--profile auto` resolves a profile once per command. `ui_variants.json` currently has `legacy` ready and `modern` planned, but no `browser` entry. The current profile registry is name-to-profile and can require interactive choice for duplicate names.
- Confirmed from current code: `profile_identity.py` captures the primary monitor and OCRs the `legacy` `world_map.player_name` region. `client_router.py` separately classifies the Windows foreground process/title and polls for changes without prompting. The profile registry can contain duplicate names; the router blocks these because it requires exactly one match. `ui_variants.json` includes `legacy` ready and `browser` planned/unavailable.
- Assumption to verify: foreground executable/window-title detection distinguishes the game client from Chrome with the Total Battle tab active on the target Windows installation. If not, the router stays `unknown` and does not infer a client from screenshot similarity alone.
- Deferred: browser player-name region/template annotation; browser variant readiness; stable mapping for duplicate player names; selected-window capture and coordinate conversion; continuous queue dispatch; any clicks, scrolling, or simultaneous per-window execution.
- Deferred: browser player-name region/template annotation and browser readiness; a manual account binding for duplicate player names; selected-window capture and coordinate conversion; continuous queue dispatch; any clicks, scrolling, or simultaneous per-window execution.

### Implementation status

The first read-only slice is implemented in `client_router.py`. It polls the Windows foreground window, classifies a Total Battle-titled native process as `desktop`, Chrome/Edge/Firefox with a Total Battle title as `browser`, and reports other or incomplete metadata without selecting a queue. Desktop name OCR uses the explicit `legacy` asset set and only routes when one exact registered player-name match exists. Unknown names, duplicate matches, and OCR uncertainty do not return a queue path. The observer never loads or mutates a task queue and never sends game input.

Browser is registered in `ui_variants.json` with status `planned`. Chrome is recognized as the browser client, but browser profile resolution deliberately returns `browser_identity_unconfigured`: `ui/browser/regions.json` does not yet include a verified `world_map.player_name` region. No browser-to-desktop fallback occurs. The existing user-authored `--profile auto` manager changes are preserved; the new router uses a separate non-interactive unique-match lookup so a polling loop cannot prompt or create profiles repeatedly.

Run one observation with `python .\\client_router.py --once`; observe foreground changes with `python .\\client_router.py` (Ctrl+C to stop). These commands report route identity only. Continuous task execution and cross-client queue switching are not implemented until browser identity is annotated and the observer is validated on representative browser and desktop captures.

### Expected tests

- Foreground native Total Battle window maps to `desktop`; Chrome/Edge/Firefox with a Total Battle title maps to `browser`; unrelated foreground window maps to `not_game`; unknown/missing window metadata maps to `unknown`.
- Client/profile routing never silently falls back to another client or profile.
- OCR disagreement, missing client-specific name region, unknown player, and duplicate profile mappings do not return an executable queue target.
- Switching client or player between observations changes the resolved target and leaves each profile's queue path isolated.
- Observe-only mode performs no game input and no queue mutation; tests use injected window, capture, and OCR providers.
- The existing desktop workflow and default `legacy` behavior remain unchanged.

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
