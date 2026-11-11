# Desktop and Browser UI Support Plan

## Migration Validation Run

Executed 2026-11-10 in the workspace venv with `--continue-on-collection-errors`: routing/profile/variant/browser group **28 passed, 5 failed**; full repository **345 passed, 19 failed, 8 errors**. All five group failures request a `browser` variant whose registry status is `planned`. This is a test/registry conflict, not browser readiness. Earlier source-review notes remain inspection evidence. No live profile dispatch, browser input, or registry behavior changes were made. Log: operating-system temporary directory, `tba_docs_routing_profiles_ocr_20261110.log`.

## Purpose

Own the current client-selection, profile-identity/registration/routing, and browser-readiness contracts. Keep game behavior and task planning independent from visual assets. Client identity selects assets; player identity selects a local profile. Neither is proof that a task can safely execute.

## Feature Contents

- [Client selection](#client-selection)
- [Profile identity, registration and routing](#profile-identity-registration-and-routing)
- [Browser readiness](#browser-readiness)
- [Current Status and Verification](#current-status-and-verification)
- [Historical Plans](#historical-plans), including the [2026-11-07 routing scope](#foreground-client-and-account-queue-routing-approved-2026-11-07)

## Current Status and Verification

Source-reviewed date: **2026-11-10**. This is the single current status for these features; historical sections below are not competing contracts.

| Feature | Current implementation | Evidence and remaining boundary |
| --- | --- | --- |
| Client selection | Registry resolver defaults to ready `legacy`; `modern` and `browser` are planned and rejected. Foreground classification reports `desktop` or `browser` independently of variant readiness. | Resolver and foreground-classification source/tests inspected. Classification is a title/process heuristic, not verified account or screen recognition. |
| Profile identity, registration and routing | Desktop observer auto-registers unknown names by default and selects the first normalized-name match, including duplicates. Diagnostic opt-out disables creation, not first-match routing. | Router and identity source, router tests, and manager caller inspected. No queue access or game input occurs in the observer. The current manager does not call the identity helper. |
| Browser readiness | Foreground browser classification exists; profile routing is unconditionally blocked before capture. Browser-specific read-only training scanner code and fixture tests exist, but the normal resolver rejects `browser`. Speed Up is the sole approved future feature exception: its adapter has an independent false readiness gate and may not promote global browser readiness. No browser Speed Up assets or reader/input adapter exist. | Browser registry, regions, scanner branch, and fixture test source inspected. Fixture expectations do not establish runnable browser support or live identity/action readiness. Speed Up skeleton tests establish callback/core wiring only, not browser recognition or operation. |

Automated tests were **inspected, not executed in this migration**. No passing result is claimed, including for browser fixtures whose prerequisites conflict with the current planned registry state. No live validation, game input, captures, OCR execution, or asset changes were performed. Documentation validation consists of a scoped executable PowerShell link/heading check and editor diagnostics; its outcome is reported in the migration handoff. The main agent will run tests separately.

## Client Selection

### Purpose and current behavior

Select an explicit visual asset namespace without changing the domain planner or profile identity. Foreground client IDs (`desktop`, `browser`) are distinct from asset variant IDs (`legacy`, `modern`, `browser`); there is no automatic conversion from a profile to a configured client. The desktop observer explicitly requests `legacy`.

### Inputs and defaults

- `resolve_variant(variant_id=None, registry_path=REGISTRY_PATH)` reads the JSON registry on each call; omission uses `default_variant`, currently `legacy`. There is no selected-client cache or per-profile client setting.
- Explicit variant IDs are used by tooling/scanner callers. The foreground observer has no manual variant CLI override.
- `classify_foreground_window(window, game_title_token="total battle")` accepts supplied metadata; otherwise the observer obtains the Windows foreground top-level window. It does not select or activate a window.

### Algorithm and outputs

1. Require a registry `variants` object, a known selected ID, status `ready`, and nonempty paths for `regions`, `templates`, `screenshots`, `tests`, and `verification_output`.
2. Resolve these paths relative to the project root and reject absolute or escaping paths. Return the ID, ready status, and resolved paths. Selection itself does not verify that files exist or screen assets are complete.
3. Template resolution constrains paths to the selected template root; a `templates/` prefix is rebased to that root. Unknown, planned, malformed, or escaping selections raise `UIVariantError`, with no implicit fallback.
4. Foreground classification returns `unknown` for missing window/title/process metadata. Chrome, Edge, or Firefox with a case-insensitive Total Battle title token returns `browser`; those browsers without the token return `not_game`. Any other nonempty process with that title token returns `desktop`; other titles return `not_game`.

### Safety and limitations

Path containment is not screen verification. Callers must use the selected client's regions and templates consistently; explicit scanner region/variant arguments are caller responsibilities, not proof of approved readiness. The native process is not allowlisted: an unrelated process with a matching title can be classified as desktop. Foreground metadata is not evidence that the game occupies the primary monitor. Unsupported operating systems return no foreground window. There is no implicit browser-to-desktop asset fallback.

### Status and verification

See [Current Status and Verification](#current-status-and-verification) for the source-review date and evidence limits. Resolver defaults and failure gates are source-reviewed, not newly executed here.

### Proposed and deferred changes

Stable `desktop` naming for the asset registry, a compatibility migration for `legacy`/`modern`, per-profile/window selection, selected-window capture, and safe initialization of planned annotation targets remain plans. See [Selection and Isolation Rules](#selection-and-isolation-rules) and [Open Decisions for Implementation](#open-decisions-for-implementation); these are not implemented guarantees.

### Implementation and tests

- [ui_variants.py](../../ui_variants.py): `resolve_variant`, `resolve_asset_path`; [ui_variants.json](../../ui_variants.json): configured defaults and roots.
- [client_router.py](../../client_router.py): `classify_foreground_window`, `get_foreground_window`.
- [tests/test_ui_variants.py](../../tests/test_ui_variants.py): default parity, unknown/planned rejection, template-root isolation and escaping paths.
- [tests/test_client_router.py](../../tests/test_client_router.py): foreground classification and browser rejection.

## Profile Identity, Registration and Routing

### Purpose and current behavior

Observe the visible desktop player, resolve a local profile, and report a queue path without opening that queue. User-authorized current behavior creates a missing mapping and chooses the first duplicate match without prompting. The observer is not globally read-only: it can persist the profile registry, but cannot execute tasks or send game input.

### Inputs and defaults

- `observe_foreground_profile` accepts injectable window, capture and name-reader providers, `profiles_dir=PROFILES_DIR` (project `profiles` directory), and `register_missing=True`.
- CLI `--once` prints one JSON observation; otherwise polling uses `--interval 1.0` seconds and prints changes only. Nonpositive intervals are parser errors. Both modes register by default; `--no-register-missing` disables registration.
- Identity reads require a fresh 1920x1080 BGR primary-monitor frame and the `legacy` `world_map.player_name` region with the current fixed 39-pixel vertical offset. No cached identity is used. A supplied Tesseract path is supported by the identity helper, not exposed by the router CLI.
- The registry path is `profiles_dir/profile_registry.json`, schema version 1. A missing file means an empty registry; malformed/unreadable content is an error, not permission to overwrite it.

### Algorithm and outputs

1. Classify the foreground window using [Client Selection](#client-selection). Return `unknown` or `not_game` without a route, or block `browser` before capture with `browser_identity_unconfigured`.
2. For desktop, capture the primary monitor and OCR the name using scales 4 and 7 crossed with Tesseract PSM 8 and 13, with an ASCII letters/digits/underscore/hyphen whitelist. All four nonempty normalized reads must agree case-insensitively. These are four passes on one crop, not independent frames.
3. Normalize names using Unicode NFKC, collapsed whitespace, stripping boundary spaces/underscores/hyphens, and casefold comparison. Preserve the first successful candidate's spelling in `PlayerNameReading`. Reject empty, conflicting, missing-region, outside-frame, or unsupported-size readings.
4. Search the registry in stored order. Reuse its first normalized-name match, even if several exist. Otherwise create a mapping unless registration is disabled. New IDs use an ASCII slug (up to 32 characters, fallback `player`) plus a random five-character lowercase/digit suffix, checked against existing IDs with at most 100 attempts.
5. Persist new mappings with creation/last-seen timestamps using a temporary file and atomic replacement. Observer reuse does not refresh `last_seen_at`. Return the profile ID and the path from `task_queue_path(profile_id, profiles_dir)`, which uses a profile-specific slug/digest directory and `tasks.json`; do not create or open the queue.

`RouteObservation` includes `status`, `client_id`, `player_name`, `profile_id`, `queue_path`, `reason`, window title/process, and UTC observation timestamp. A routed result reports `profile_registered` or `profile_reused`; it is not an execution authorization. It does not contain OCR candidates or a numeric confidence score. The lower-level `PlayerNameReading` retains candidates, status, and reason.

Capture/name-reader exceptions return `blocked` with `capture_failed:` or `player_name_read_failed:`. Non-OK OCR returns a `player_name_<status>:` reason. Identity/registry validation failures return `profile_unresolved:`; registry write errors return `profile_registry_write_failed:`. These blocked results have no profile or queue path. They do not fall back to another profile. The one-shot CLI returns zero after printing an observation even when routing is blocked; consumers must inspect JSON `status`, not just the process exit code.

The separate `resolve_profile` helper is interactive whenever matches exist, including a single match: choose an entry or `N` for a new profile. No match or `new_profile=True` creates immediately. It updates `last_seen_at` and saves on reuse as well as creation, returning action `created`, `reused`, or `selected`. `resolve_registered_profile` never writes, but still takes the first match; `resolve_registered_profile_or_create` is the observer default. Do not confuse these helper modes. `resolve_profile_from_game` captures/resolves once without a foreground-client check. The current manager parser treats `--profile` as a literal ID (default `test`); it does not call this helper or implement special `--profile auto` resolution.

### Safety and limitations

- Observer isolation means no task-queue reads/writes, no clicks/scrolling, and only registry creation as a persistent side effect. Queue scheduling and persistence belong to the [task manager contract](task_manager.md), not this observer.
- A player name is not a unique account identifier. First-match duplicate routing is intentional current behavior and can select the wrong same-name account. OCR consensus can consistently misread a name and create an unintended mapping. Names outside the OCR whitelist are not established as supported.
- Foreground metadata and the subsequent primary-monitor capture are not atomic or window-bound. There is no post-capture identity/window recheck or dispatch guard; switching accounts/windows during observation remains an unresolved risk. Never treat polling alone as an action-time isolation guarantee.
- Atomic replacement reduces partial writes but provides no cross-process locking or merge protection. Concurrent registrations can lose updates. Registry validation checks schema and string fields, not account uniqueness or all profile-ID collisions. No credentials are stored by this feature.
- Watch output deduplicates status/client/player/profile/reason/window/process, not timestamp or queue path; it is a change report, not a complete observation audit or queue dispatcher.

### Status and verification

See [Current Status and Verification](#current-status-and-verification). First-match routing and default registration are the current source-reviewed behavior, superseding historical unique-only/read-only descriptions. No identity correctness, concurrent safety, or live switching success was demonstrated in this migration.

### Proposed and deferred changes

The [approved routing scope](#foreground-client-and-account-queue-routing-approved-2026-11-07) includes future pre-dispatch identity rechecks and reconciliation against the owning profile. These guards, continuous queue dispatch, browser identity, stable same-name account binding, parallel windows, and automatic recovery remain unimplemented/deferred here. This documentation migration grants no new game-action scope.

### Implementation and tests

- [client_router.py](../../client_router.py): `observe_foreground_profile`, `watch_foreground`, `main`.
- [profile_identity.py](../../profile_identity.py): `read_player_name`, registry persistence, the three resolution modes, and `resolve_profile_from_game`.
- [task_controller.py](../../task_controller.py): `PROFILES_DIR`, `task_queue_path`; [army_training_manager.py](../../army_training_manager.py): literal CLI profile selection.
- [tests/test_client_router.py](../../tests/test_client_router.py): registration/reuse, first duplicate selection, opt-out, OCR and write-failure blocks, CLI defaults, and change-only polling. Injected readers do not prove real OCR accuracy or action-time isolation. No dedicated profile-identity test file was present at source review.

## Browser Readiness

### Purpose and current behavior

Separate detecting a browser window from usable browser visual identity, read-only screen recognition, and game execution. A fixture or scanner branch does not make all four ready.

### Inputs and defaults

Browser classification uses foreground Chrome/Edge/Firefox title metadata. Normal scanner entry points accept explicit `variant_id="browser"`; omission still selects `legacy`. Browser roots are configured under `ui/browser`, but the registry status is `planned`. Supplied in-memory variant dictionaries bypass normal selection at some scanner boundaries and are not readiness evidence.

### Algorithm and outputs

- The foreground observer returns `blocked`, client `browser`, reason `browser_identity_unconfigured`, and no profile/queue, before any capture or OCR. Changing registry readiness alone would not remove this explicit router gate.
- `resolve_variant("browser")` currently raises `UIVariantError`. Browser regions contain training assets but no `world_map.player_name`; they cannot support the desktop identity contract.
- The browser training scanner branch compares the portrait crop against an empty-unit template (score at least 0.90) and image detail (standard deviation at least 20). Conflicting/neither evidence stays `unknown`; otherwise it returns `idle` or `active`. It leaves Help/Speedup/button actions unknown and trained-unit count unsupported. This is read-only recognition logic, not a browser action adapter.
- The Speed Up browser channel currently has only the gated adapter boundary in `speedup_browser.py`. It shares the generic planner/orchestrator when feature-test-gated, independently of global browser UI readiness. Production calls remain blocked while its own readiness constant is false. No browser Speed Up screenshot, recognition, or live input support is present; this exception enables no other web feature.

### Safety and limitations

Browser fixture tests expect three detected slots, per-slot numeric readings, uncertain selector levels, active/idle/unknown portrait classification, and browser-root template resolution. Their use of `resolve_variant("browser")` or a scanner that calls it conflicts with the current planned registry: those normal paths are rejected before the fixture assertions. This is a source-visible prerequisite mismatch, not a test result from this migration. The registry also repeats the `browser` JSON key with identical planned entries; Python's JSON parser keeps the last entry. This ambiguity was not repaired in a documentation-only task.

Do not infer browser player-name recognition, supported selector levels, Help/Speedup actions, training execution, or queue dispatch from those tests. Speed Up skeleton tests do not establish browser screen recognition. Historical supplied screenshots are evidence only for their actual resolution/window context, not live support. There was no image inspection or browser live validation in this migration.

### Status and verification

See [Current Status and Verification](#current-status-and-verification). Browser read-only code/fixtures are present; operational browser identity and execution remain unavailable. Readiness is not promoted by this document or by test-file existence.

### Proposed and deferred changes

Verify browser identity assets and capture geometry, reconcile registry/fixture prerequisites, and explicitly approve any readiness change. Retain the [phased browser inventory and incremental support plan](#phased-work); no new assets, registration semantics, browser game flow, or live action are authorized by this migration.

### Implementation and tests

- [client_router.py](../../client_router.py): early browser block; [ui_variants.json](../../ui_variants.json): planned status; [ui/browser/regions.json](../../ui/browser/regions.json): current training-only regions.
- [army_training_scanner.py](../../army_training_scanner.py): `_read_browser_training_snapshot`, normal variant gate and in-memory entry point.
- [tests/test_browser_army_training.py](../../tests/test_browser_army_training.py): read-only fixture expectations, not executed here.
- [tests/test_client_router.py](../../tests/test_client_router.py): planned rejection and browser block before capture.

## Historical Plans

The remaining sections preserve preparation goals, approved/deferred scope, and existing anchors. They are historical design material, not current implementation status. Use [Feature Contents](#feature-contents) for the authoritative contracts and [Current Status and Verification](#current-status-and-verification) for evidence. Proposed steps are not newly approved by their preservation here.

## Goals

- Preserve the existing desktop application interface and workflows unchanged.
- Treat browser and desktop as separate client targets, so regions and templates from one client can never silently be used for the other.
- Add browser-interface recognition screen by screen after its visuals stabilize.
- Reuse logical screen and element identifiers where the underlying game behavior is the same.
- Keep screenshots, regions, templates, and verification fixtures associated with their client.
- Eventually select the client per game profile/window, independently of other profiles.
- Select the foreground client independently from the account profile and report its profile/queue route without mixing per-profile state. This goal does not require unique-name rejection; see the current [first-match contract](#profile-identity-registration-and-routing).

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

This proposed folder layout and naming are not a migration record. See [Client Selection](#client-selection) for actual IDs, defaults, and path guarantees, and [Browser Readiness](#browser-readiness) for the narrower browser fixture/code boundary.

## Selection and Isolation Rules

Historical target rules, not a claim that every tool/profile already enforces them:

- Use stable client IDs such as `desktop` and `browser`; do not use release labels as client identity.
- Existing commands and profiles must continue to use the current desktop UI by default.
- Permit explicit CLI client selection for tooling and tests.
- Store the selected client per profile/window when profile configuration is introduced or extended.
- Resolve every screen's regions and templates through the selected client registry.
- If a client or required screen is missing or not ready, fail with a clear error. Never fall back from browser to desktop assets implicitly.
- Keep profile state isolated: the active client, captures, OCR, caches, and recognition results must not leak between windows/accounts.

## Foreground Client and Account Queue Routing (Approved 2026-11-07)

Historical approval: observe the foreground client and visible player separately, report the local profile/queue route, and preserve per-profile ownership without sending game input. Current registration, duplicate selection, metadata, outputs, and failures are owned by [Profile Identity, Registration and Routing](#profile-identity-registration-and-routing), not this historical outline.

The original scope also described future action-time rechecks: suspend dispatch on a client/profile change, resolve the newly visible profile before queue access, stop subsequent actions after a mid-action change, and reconcile uncertain results only against the original owning profile. These remain deferred, not observer guarantees. Queue reads/execution, browser identity/training actions, click adapters, selected-window capture, multi-window parallelism, and automatic recovery require their own implementation and authorization.

Historical supplied-image notes named desktop players `xirrus` and `snoweye`, a different browser player, and 1920x1080 browser fixtures. These notes were not revalidated through image inspection here and do not establish a browser identity region or accurate OCR. The earlier goal of exposing raw OCR/confidence evidence in route output is not implemented as written; the current contract distinguishes lower-level candidates from route JSON fields.

Historical expected coverage included client/player switches and queue isolation in addition to default parity and failure gates. Current inspected test scope and its limits are recorded in the feature contracts; this historical expectation is not a passing test report.

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

Historical phase note: transitional IDs motivated a deliberate client-ID migration and deferred profile-level configuration. See the [current client contract](#client-selection), rather than treating this phase as a separate status.

### Phase 2: Client-aware read-only tooling

- Add an explicit client option to annotation, verification, and army-training scanning tools.
- Make omitted client selection preserve existing desktop behavior.
- Route reads and writes only through the selected client's configured paths.
- Reject writes to clients or screens that are marked unavailable unless explicitly initialized for annotation.
- Add tests proving desktop defaults remain unchanged and client paths cannot cross-contaminate.

Historical phase note: the initial tooling plan used ready-only selection and left explicit safe initialization open. Annotation behavior was not re-audited in this migration; no claim that all tools meet this phase is made. See [Current Status and Verification](#current-status-and-verification) for the reviewed scope.

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

- Repository workflow and scope rules: [AGENTS.md](../../AGENTS.md)
- Screen-specific recognition: [docs/screens](../screens/)
- Capture and display configuration: [docs/game/konfiguracja.md](konfiguracja.md)
- Game behavior independent of appearance: [docs/game/mechaniki.md](mechaniki.md)
