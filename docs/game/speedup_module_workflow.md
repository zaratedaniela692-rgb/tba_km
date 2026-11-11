# Speedup Module Workflow

## Migration Validation Run

Executed 2026-11-10 in the workspace Python 3.13 venv with installed Tesseract temporarily on PATH, plugin autoload disabled, and `--continue-on-collection-errors`: speedups **129 passed, 2 failed, 3 collection errors**; full repository **345 passed, 19 failed, 8 errors**. The short-initial-plan replan assertion fails; empty `speedup_run.py` lacks `EvidenceCapture`; checkpoint/inventory/live modules cannot collect because `speedup_reader.configure_tesseract` is missing. Existing callable source therefore does not imply a runnable integration in this worktree. Source-review notes below describe inspection only; this paragraph records subsequent execution. No live use or Python fix was performed. Log: operating-system temporary directory, `tba_docs_speedups_ocr_20261110.log`.

**Refactor follow-up (2026-11-11):** restored the shared `configure_tesseract(executable=None)` helper and its optional `read_remaining_time(..., tesseract_cmd=None)` call contract; restored only inert `speedup_run.py` evidence/confirmation symbols, not its historical live CLI. The first focused run exposed one test/code replan conflict; after the user selected initial-plan-only MVP behavior, the generic replan was disabled and the regression updated. The full `tests/test_speedup*.py` set now passes: **177 passed**. Tesseract fallback was exercised on this Windows workspace with `C:\Program Files\Tesseract-OCR\tesseract.exe`. No live game input was performed. `tests/test_device_test.py` separately remains uncollectable/failing because its `repo` fixture and `dt`/scenario definitions are absent; that harness was not changed in this slice.

## Feature contents

- [Scope and entry points](#scope-and-entry-points)
- [Timer and checkpoint inventory reading](#timer-and-checkpoint-inventory-reading)
- [Owned-item planning](#owned-item-planning)
- [Use verification and result semantics](#use-verification-and-result-semantics)
- [Calibration, mapping and evidence](#calibration-mapping-and-evidence)
- [Historical decisions and retained anchors](#historical-decisions-and-retained-anchors)

**Current evidence baseline: 2026-11-10 source inspection.** This documentation-only migration inspected implementations and focused test sources. Automated tests were **not run here**; no live game actions were performed. Existing test cases are intended checks, not passing-test evidence. Historical calibration/review reports below were not repeated or independently revalidated here.

## Scope and entry points

### Purpose and current behavior

Finish the task in an already-open speedup dialog using owned items only. The caller opens the dialog, selects the task/account and confirms completion on its own task screen. The speedup components do not manage queues, markers, credentials or profile selection. Army training is the first integration scope; Academy/building entry-button screenshots do not establish support for those flows.

| Entry point | Current route |
| --- | --- |
| `speedup.finish_with_speedups(...)` | Generic injected screen orchestrator; no desktop input by itself |
| `speedup_live.finish_open_dialog(...)` | Desktop callbacks feeding that generic orchestrator |
| `speedup_live.run_desktop_speedups(...)` | Primary-monitor capture/input plus the preceding adapter and failure evidence |
| `speedup_checkpoint_runner.run_checkpoint_speedups(...)` | Separate injected checkpoint scan and batch-use implementation; not called by `speedup_live` |
| `speedup_browser.finish_browser_dialog(...)` | Browser callback boundary feeding the same generic orchestrator; blocked until browser Speed Up assets and adapter are verified |

### Browser Invocation Channel (Skeleton)

Keep `speedup.py` as the single owner of timer-driven planning, the initially selected item list, and result semantics. The browser channel is a separate adapter boundary, not a copied planner or a desktop fallback. `speedup_browser.py` defines browser-scoped callbacks and routes them into `finish_with_speedups`; browser capture, dialog recognition, inventory OCR, navigation, and input callbacks are not implemented until a representative Speed Up browser screen is supplied and annotated.

Browser Speed Up readiness is independent of browser army-training fixtures and of the generic browser client label. The global browser UI variant stays `planned`; no desktop regions, templates, coordinates, or button maps may be used for this channel. Until the browser-specific Speed Up adapter has verified assets, the entry point returns `BLOCKED` before calling any callback, including in execute mode. Tests may inject fake browser callbacks behind the Speed Up-specific test gate to verify forwarding into the shared core; this neither promotes global browser readiness nor establishes live support.

User decision (2026-11-11): permit Speed Up as the sole web feature exception. Its readiness must be feature-scoped and must not require changing the global `browser` UI variant to `ready`; no army-training, profile routing, or other browser action becomes enabled by this exception. The feature gate remains false until its own screen evidence, annotations, and browser callbacks are verified.

User-reported visual parity (same icons and analogous layout) is a hypothesis for future asset review, not current implementation evidence. After screenshots arrive, verify the dialog anchor, timer, viewport, owned-item rows/quantities, Use controls, Buy exclusion, scroll endpoints, and coordinate origin independently for browser. Then implement only the browser callbacks and keep planning/use/result mechanics shared. Live browser use requires separate authorization after those checks pass.

Implementation status: skeleton implemented and offline-tested 2026-11-10/11. `speedup_browser.finish_browser_dialog` is gated only by the Speed Up-specific `BROWSER_SPEEDUP_ASSETS_READY=False`; it neither promotes nor depends on global browser UI readiness. It returns `BLOCKED` before any callback while Speed Up assets are unverified. With the feature gate enabled in tests and a callback bundle marked `client_id="browser"`, it forwards to the shared orchestrator. Five adapter tests pass. No browser Speed Up screenshot or live validation is available; production readiness remains blocked.

### Inputs and defaults

- Generic function: injected capture, dialog reader, click and scroll callbacks; no-op default `stop_fn`, `sleep_fn=time.sleep`, `dry_run=True`, `max_scrolls=12`. Its caller must supply a real stop guard for live use.
- Desktop function: `execute=False`, `max_scroll_steps=20`, optional `evidence_dir` and sleep callback. Loads checked-in button map, annotated regions and Use template. Its injected adapter supports reader/asset overrides for tests.
- Checkpoint function: injected capture/move/scroll/click callbacks, map and template; `dry_run=True`, no-op default stop callback, expected frame 1920x1080. The caller starts the list at the top and supplies live safety/evidence adapters if used live.
- Quantities come from fresh frames. The static button map is calibration data, not cached quantities or permission to click. These paths do not use a persistent inventory cache.

### Algorithm and outputs

The generic path establishes the top from an unchanged upward view, scans down until an unchanged signature, reconciles duplicate quantities, plans from the last scan timer and optionally uses items. Desktop callbacks expose rows only at cumulative checkpoints 3/11/16, track position from viewport changes and reject a changed view past checkpoint 16 or an early endpoint. They position the pointer at viewport center before each wheel event.

The separate checkpoint path assumes the top rather than establishing it, sends exactly 16 downward steps, checks every transition, reads checkpoint rows and plans from a fresh post-scan timer. An unchanged view is an error (`viewport_unchanged`), not successful inventory-end detection in this path.

Generic output is `SpeedupResult`; the desktop adapter returns `(result, state)`. The checkpoint path returns `CheckpointRunResult` with inventory, plan, submitted uses, timers, diagnostics and event trace. Both use `PLANNED`, `FINISHED`, `NOT_ENOUGH`, `BLOCKED` and `UNCERTAIN`, but their verification strength differs; see [verification](#use-verification-and-result-semantics).

### Safety and limitations

Dry-run may scroll; it never clicks Use or Buy. There is no purchase path. Desktop capture uses `mss.monitors[1]`, not a selected or activated game window. The adapter requires capture/display size agreement at 1920x1080, adds monitor origin to input coordinates and checks the home `.tba_stop` file before input. Correct foreground game/account, UI scale and dialog/task selection remain caller responsibilities; matching geometry alone does not establish them.

There is **no standalone finishing CLI** in `speedup.py` or `speedup_live.py`; `speedup_run.py` currently provides only inert compatibility/test-support symbols (`SCAN_CONFIRMATION`, `USE_CONFIRMATION`, `EvidenceCapture`) and does not launch a runner. Do not restore a historical live CLI until the checkpoint batch item's missing per-use verification and unreadable-timer tail behavior have an agreed contract. Old `speedup.py --execute --confirm ...` and scan commands do not implement an interface. The callable API enforces no exact confirmation phrase: `execute=True` enables desktop use. Documentation approval is not authorization for a live run. Generic/checkpoint injected APIs require caller-supplied safety callbacks.

### Status and verification

Callable paths implemented and inspected 2026-11-10; no test execution or supervised live item-use validation here. Existing documents reported reviewed checkpoint calibration on 2026-11-07 and a later dry-run recognition failure; neither proves live item-use completion. Source inspection does not establish end-to-end army adapter wiring. `army_training_finish.finish_open_training` accepts `speedup_fn`, but that hook alone is not evidence that a specific runner is wired.

### Proposed and deferred changes

Finishing CLI, selected-window capture/window-relative coordinates, browser assets, Academy/building integration and independent task recognition remain outside this current contract. Navigation by 3-4 clicks or item-row clicks is not verified by these captures; do not replace bounded wheel navigation with it. Caller queue/profile ownership remains unchanged.

### Implementation and tests

[speedup.py](../../speedup.py), [speedup_live.py](../../speedup_live.py), [speedup_browser.py](../../speedup_browser.py), [speedup_run.py](../../speedup_run.py), [speedup_checkpoint_runner.py](../../speedup_checkpoint_runner.py), caller hook in [army_training_finish.py](../../army_training_finish.py). Test sources: [tests/test_speedup.py](../../tests/test_speedup.py), [tests/test_speedup_live.py](../../tests/test_speedup_live.py), [tests/test_speedup_browser.py](../../tests/test_speedup_browser.py), [tests/test_speedup_checkpoint_runner.py](../../tests/test_speedup_checkpoint_runner.py). The browser skeleton's five tests pass; the combined browser/core/planner run had 46 passes and one existing `test_short_initial_plan_does_not_rebuild_below_twenty_percent` failure. No supervised browser run occurred.

## Timer and checkpoint inventory reading

### Purpose and current behavior

Read remaining time and quantities of nine mapped owned durations (15m through 30d). The 1m item is intentionally omitted. Duration identity comes from reviewed checkpoint labels and sorted complete Use matches, **not general duration-label OCR**. Complete means complete within this mapped layout, not arbitrary inventory coverage or task identity. Visual regions and reference evidence belong to the [screen card](../screens/speedup.md).

### Inputs and defaults

`read_remaining_time(image, variant=None)` uses the configured variant's timer region. `read_checkpoint_viewport` takes a viewport crop, checkpoint, button template and quantity/Use reference regions; expected crop is 562x418. Optional `duration_seconds` limits quantity OCR to one duration; `verify_only=True` verifies button layout without OCR and returns no items. `combine_checkpoint_readings` combines supplied readings; the caller owns supplying all required checkpoints. It does not independently require the 3/11/16 set.

Pure parsers accept raw text and confidence, default minimum 70.0, and preserve explicit failure status with `value=None`; quantities never default to zero. Polish `g` and `h` hour forms are accepted by the parsing foundation. Image reading is narrower than parser syntax.

### Algorithm and outputs

1. Segment timer glyphs, remove the taller hourglass and read individual digits at 6x/10x. Both reads must agree and use only verified digits `1,3,4,6,7`. The image reader recognizes a day/hour layout; arbitrary minute/second or zero-timer formats are not established.
2. Detect complete Use buttons at threshold 0.95 and require mapped counts: step 3 has 15m/1h/3h/8h; step 11 has 15h/1d/3d; step 16 has 3d/7d/30d. Clipped step-11 7d is omitted; the lower shop Buy row is excluded.
3. Pair sorted matches with checkpoint labels. Require in-viewport rectangles and common offsets consistent within 1 px across rows. Uniform translation is accepted, not restricted to the old absolute 2 px limit. Use fresh detected rectangles/centers for crops and click points.
4. Crop quantities relative to the detected button, with 5 px left and 3 px right insets. OCR at 4x/6x using PSM 8; on empty/disagreeing normalized reads, retry OCR using PSM 7. Both fallback reads must agree. This is a read retry, never a repeated game action.
5. Return raw OCR, confidence/status, item geometry and match/quantity diagnostics. Combine only complete readings; repeated 3d quantities must agree and the earliest complete location is retained. An incomplete reading exposes `inventory=None`.

### Safety and limitations

Unreadable/conflicting quantities, missing/extra buttons, inconsistent offsets, invalid mapped durations and wrong crop geometry return incomplete readings. Fixed labels do not detect a new inventory layout merely because button counts match. `verify_only` is not quantity verification. OCR agreement is the reader's gate, not independent proof of correctness. Image timer limitations can block values accepted by pure parsers and prevent reaching the zero-timer completion branch.

### Status and verification

Implemented checkpoint quantity reader and pure parsers, inspected 2026-11-10. Fixture assertions and synthetic-shift tests exist; tests were not run here. The prior claim that fixture-backed inventory reading was wholly pending is superseded. General duration OCR, arbitrary list coverage and all-format timer recognition are not established.

### Proposed and deferred changes

General row classification, new durations/layouts, expanded timer digits/formats, full scrollbar recognition and browser fixtures need separate evidence and implementation. Do not silently widen the mapped scan or reinterpret unknown readings as empty inventory.

### Implementation and tests

[speedup_readings.py](../../speedup_readings.py), [speedup_reader.py](../../speedup_reader.py), [speedup_inventory_reader.py](../../speedup_inventory_reader.py), [speedup_button_map.json](../../speedup_button_map.json). Test sources: [tests/test_speedup_readings.py](../../tests/test_speedup_readings.py), [tests/test_speedup_reader.py](../../tests/test_speedup_reader.py), [tests/test_speedup_inventory_reader.py](../../tests/test_speedup_inventory_reader.py). Named checks include `test_unverified_digit_is_rejected_not_guessed`, `test_small_uniform_viewport_shift_uses_live_button_positions_for_ocr_and_clicks`, `test_falls_back_to_single_line_psm_only_after_primary_scale_disagreement`, `test_verify_only_matches_buttons_without_running_quantity_ocr`, and `test_repeated_duration_conflict_blocks_complete_inventory`.

## Owned-item planning

### Purpose and current behavior

`plan_speedups` is a pure recommendation for covering remaining time from owned inventory. Soft duration preferences and preserve-stock floors are implemented, not deferred. It neither reads screens nor clicks, buys or verifies completion.

### Inputs and defaults

Required `remaining_seconds`: non-negative integer; required inventory dictionary: positive integer duration seconds to non-negative integer quantities. Booleans and invalid input types raise `SpeedupPlanError`. Zero quantities are ignored. No automatic inventory lookup, cache or manual override of detected stock is supplied.

| Remaining time | Soft preferred durations |
| --- | --- |
| Up to and including 5 days | 1h, 3h, 8h |
| More than 5, up to 15 days | 8h, 15h |
| More than 15, up to 100 days | 15h, 1d, 3d |
| More than 100 days | 3d, 7d, 30d |

Floors: retain 3 each of 3d/7d/30d and 10 of every other duration. Preferences/floors are soft, not an allowlist or hard spending cap.

### Algorithm and outputs

If remaining time is zero, return `nothing_to_do`. If all stock cannot cover it, return `shortfall` with no uses and missing seconds. Otherwise re-evaluate the preference bucket for each selection. Among stock above its floor choose, in order: largest preferred fit; largest other fit; smallest preferred overshoot; smallest other overshoot. Only when no above-floor stock remains, choose a floor-breaking largest fit or smallest overshoot. Floors outrank reducing overshoot: a large above-floor item can be selected for a small remainder.

Return `SpeedupPlan(status, uses, breached_floors, shortfall_seconds, decisions)`. `uses` aggregates quantities in first-use order; `decisions` records individual selections. Report a breached floor only for a used duration ending below its floor. This is a greedy policy, not an optimal minimum-waste solver. The older phrase "favor 1d/3d more as remaining time grows" is realized only by bucket membership and selection order, not extra continuous weighting.

### Safety and limitations

Initial shortfall spends nothing. Reserve-breaking can be recommended only when total stock covers the task and is explicitly reported. A plan uses a supplied timer/stock snapshot; clan Help and timer rounding may make it stale. In the current MVP, the generic runner does not replan after Help or timer changes: it follows only the initial item plan and returns `UNCERTAIN` if that plan is exhausted while the timer remains positive. This avoids additional item use beyond the user's reviewed initial plan.

### Status and verification

Implemented policy inspected 2026-11-10; focused test source inspected, tests not run here. A plan is not evidence of in-game completion.

### Proposed and deferred changes

No additional planner policy is enabled by the current MVP. A single generic replan below 20% is user-requested for a future change; it requires implementation and regression tests before use. The old 50% timer milestone/polling proposal remains deferred and is distinct from checkpoint residual batching.

### Implementation and tests

[speedup_planner.py](../../speedup_planner.py), [tests/test_speedup_planner.py](../../tests/test_speedup_planner.py): shortfall, bucket selection, overshoot, floor preservation/breach reporting and invalid inputs.

## Use verification and result semantics

### Purpose and current behavior

Distinguish confirmed inventory uses in the generic orchestrator from submitted clicks in the separate batch runner. Both leave final task-screen confirmation to the caller. A shared result label does not make their evidence equivalent.

### Inputs and defaults

The generic path uses scanned stock, fresh `DialogReading` rows/signatures and `dry_run=True` by default. The checkpoint path uses combined initial inventory and mapped locations with `dry_run=True` by default. Explicit live authorization and real emergency-stop callbacks remain caller requirements for injected execution.

### Algorithm and outputs

**Generic `finish_with_speedups` (also used by the desktop adapter):** navigate to a recognized view, check stop, issue one Use click and capture again. Require the selected count to decrease exactly by one; a vanished row is acceptable only when the expected count is zero. Count-confirmed uses populate `used`. A missing dialog after the last planned click is accepted as `FINISHED` and counted without quantity evidence; missing earlier returns `UNCERTAIN` (`dialog_closed_before_plan_end`). Dialog non-recognition is not independently proven completion.

A readable zero timer after a confirmed use stops the initial plan. Replanning is disabled in the MVP: clan Help or timer changes never extend or replace the originally approved list of uses. If the planned uses are exhausted and the timer is still positive, return `UNCERTAIN` (`timer_not_zero_after_plan`) for manual review. A changed list signature, missing row or uncertain count stops rather than guessing or retrying the click. The prior below-20% replan design is retained as a commented future option in code and is not executed.

**Separate `run_checkpoint_speedups`:** navigate to the duration's earliest mapped checkpoint and verify fresh Use-button layout with `verify_only=True`. Click at its detected center and capture. It deliberately disables post-click quantity OCR and does not reread the timer after each click. It decrements estimated stock and records submitted clicks in `used`; these are not count-confirmed uses. The initial batch continues despite possible clan Help.

After the batch it reads the timer up to 6 times, with fresh captures and 1-second waits after the first attempt. Dialog non-recognition can return `FINISHED`; zero timer also returns `FINISHED`. A readable decreased but positive timer produces another residual plan from estimated stock. If the final timer remains unreadable, one hidden-remainder batch is possible when the last raw timer's smaller unit implies a bound from 60 seconds through 1 hour; it plans for that bound without a readable current timer. A second such blind tail is disallowed. Stock for residual batches is initial inventory minus submitted clicks, not fresh quantities. Other final-timer failures return `UNCERTAIN`; a residual shortfall returns `NOT_ENOUGH`. It has no generic below-20% mid-batch replan.

### Safety and limitations

Approved generic safety intent remains: owned items only; no repeated uncertain action; stop checks before navigation/clicks; unknown recognition is not zero or permission to act. Before any click, handled aborts are `BLOCKED`; after a click they are `UNCERTAIN`. Not every arbitrary exception in injected callbacks is normalized to a result; the desktop wrapper records and rethrows exceptions.

The checkpoint path intentionally does not confirm quantity after each individual click; the user chose this performance tradeoff on 2026-11-11. It verifies the Use-button layout before a batch and rereads the timer after the batch. Per-item OCR confirmation is not an MVP requirement.

**Deferred from current MVP review (user decision, 2026-11-11):** leave the existing one-time hidden-remainder behavior unchanged for now. It is separate from the intentional per-item confirmation tradeoff; no new tests or code changes are required for this decision. The default day/hour image reader's restricted digits/formats remain a limitation.

The generic below-20% replan is disabled for the MVP. The user wants a single replan below 20% in a future change; it may partially reconcile Help/timer drift, but is not current behavior and requires its own tests. The checkpoint runner has its own residual batch path and must not be changed under this name without aligning the contract.

### Status and verification

Both implementations inspected 2026-11-10. Tests not run here; no live use attempted. No supervised live item-use completion evidence was established here. The old blanket claim that every runner checks each count after every click is removed. Final task-screen confirmation, profile isolation and any game confirmation/quantity dialog after Use are not independently validated by fake adapters.

### Proposed and deferred changes

Implement the requested single below-20% replan as a future feature when scheduled; do not add per-item quantity confirmation to the checkpoint path. Hidden-remainder behavior is left unchanged and its review is deferred from the current MVP. Confirmation prompts, shortened lists after depletion and finished-dialog appearance need verified evidence; do not retry an uncertain use to obtain it. The 50% milestone remains deferred.

### Implementation and tests

[speedup.py](../../speedup.py): `_Run.use_once`, `_Run.execute`; [tests/test_speedup.py](../../tests/test_speedup.py): `test_use_without_effect_is_uncertain_and_not_retried`, `test_plan_is_not_rebuilt_when_the_timer_falls_below_twenty_percent`, stop and early-dialog-close checks.

[speedup_checkpoint_runner.py](../../speedup_checkpoint_runner.py): `_click_item`, `settle_final_timer`, `execute`; [tests/test_speedup_checkpoint_runner.py](../../tests/test_speedup_checkpoint_runner.py): `test_execution_uses_the_single_initial_plan_after_timer_changes` and `test_live_run_uses_initial_quantity_and_reads_timer_only_after_the_plan` explicitly distinguish batch behavior. These are source references, not results from this migration.

## Calibration, mapping and evidence

### Purpose and current behavior

Calibration is an explicitly selected non-finishing mode; offline mapping consumes reviewed captures. Neither invokes the planner/use loop or buys items. Finishing runs retain structured diagnostics with failure-only images. Calibration/annotation captures are intentional outputs, not permission to save every successful live-use frame.

### Inputs and defaults

Calibration requires an already-open desktop dialog. Step-by-step mode defaults to 20 steps, accepts 1-20 and stops early on an unchanged viewport. Checkpoint mode starts with the list manually at the top and uses fixed cumulative steps 3/11/16; `--steps` is not accepted with that mode. Both live calibration commands require exact phrase `SCROLL SPEEDUP LIST`.

Existing interfaces, documented only and **not executed in this migration**:

```powershell
python .\speedup_calibration.py --calibrate-scroll --confirm "SCROLL SPEEDUP LIST"
python .\speedup_calibration.py --checkpoint-scan --confirm "SCROLL SPEEDUP LIST"
python .\speedup_button_map.py --input-dir .\debug\speedup\calibration_20261107_010155_371887 --output .\speedup_button_map.json
```

Check `--help` and obtain authorization for any later live operation. The map command is offline and requires those existing calibration files.

### Algorithm and outputs

Recognize the dialog within an 8 px anchor margin at threshold 0.95. Current recognition also accepts a first-16-template-row fallback only when it meets threshold and its best location equals the full-template best location; see the [visual card](../screens/speedup.md).

Before each wheel notch, check stop, move to viewport center (frame point 959,585 in these annotations), check stop again, scroll and capture after 0.35 seconds. Add monitor origin to input coordinates. Reject size/display mismatch or changed capture geometry. Compare only the viewport: pixels above channel difference 12 count as changed; changed-pixel fraction at or below 0.003 means unchanged.

Step-by-step output includes initial image, every resulting image including the first unchanged view, and timestamped manifest in a unique calibration directory. `COMPLETE` means unchanged view; `STEP_LIMIT` does not prove inventory end. Checkpoint output saves only images at 3/11/16 plus manifest; intermediate frames remain in memory. An unchanged view gives `LANDMARK_MISMATCH`; successful `CHECKPOINTS_CAPTURED` sends no 17th scroll. It proves checkpoint capture, not generalized end detection.

Offline mapping validates 4/3/3 complete matches, excludes clipped 7d/Buy, preserves repeated 3d and writes viewport-relative rectangles/centers, duration seconds, confidence and earliest preferred locations. It does not OCR quantities or interact with the game.

### Safety and limitations

For finishing runs, save screenshots only on recognition/action/postcondition failure, `BLOCKED`, `UNCERTAIN` or exception. Never repeat an uncertain action to collect evidence. Significant decisions/actions need timestamps; do not include secrets or mix account evidence. Explicit calibration and annotation outputs are exceptions to failure-only images.

`run_desktop_speedups` creates a unique `debug/speedup/run_<timestamp>/` (or supplied new directory), keeps latest frame in memory and writes `manifest.json` with capture timestamps/geometry, reader summaries, result/error and optional `failure.png` on blocked/uncertain result or exception. A failed image write can leave no image. It does **not** implement the checkpoint runner's detailed `event_trace`, nor persist `event_trace.jsonl`. The checkpoint function returns elapsed-time trace/diagnostics; it does not persist images or JSONL itself. Its caller owns durable timestamps/evidence. The generic finisher has no screenshot writer. These are implementation limits, not relaxation of evidence policy.

### Status and verification

Implemented calibration CLI, map CLI and callable failure-evidence wrapper inspected 2026-11-10. Test sources cover calibration order/geometry/stop/limits and map geometry/count exclusions, but tests were not run here. Historical documentation reports `CHECKPOINTS_CAPTURED` on 2026-11-07 with reviewed 3/11/16 images; those assets were not regenerated or re-reviewed here. No live operation was performed.

### Proposed and deferred changes

Do not add per-success images, automatic uncertain-action retry or unverified navigation controls. Durable event traces for any new caller, richer wrapper diagnostics and generalized endpoint scanning require scoped work; this migration does not claim they exist.

### Implementation and tests

[speedup_calibration.py](../../speedup_calibration.py), [speedup_button_map.py](../../speedup_button_map.py), [speedup_live.py](../../speedup_live.py). Test sources: [tests/test_speedup_calibration.py](../../tests/test_speedup_calibration.py), [tests/test_speedup_button_map.py](../../tests/test_speedup_button_map.py), [tests/test_speedup_checkpoint_runner.py](../../tests/test_speedup_checkpoint_runner.py). Named checks include `test_checkpoint_mode_saves_only_three_landmarks_and_stops_at_sixteen`, `test_saves_first_unchanged_view_then_stops`, `test_shop_buy_and_clipped_step_eleven_button_are_not_mapped` and the anchor fallback fixture test. The no-argument [test_speedup_module.py](../../tools/test_speedup_module.py) runs the pure planner against a source-configured synthetic inventory; it cannot open a dialog or consume items.

Run the offline wrapper with `python tools/test_speedup_module.py`; pytest wrapper contract tests are in `tests/test_module_wrappers.py`. The mocked multi-module [Army queue E2E](../../tools/test_army_queue_e2e.py) invokes the shared core with in-memory callbacks; it does not certify the desktop adapter.

## Historical decisions and retained anchors

These headings retain earlier link targets. They are historical summaries or redirects, **not a second current contract**. Current behavior/evidence is owned by features above. Historical approval is not new authorization for live actions.

## Goal and scope

Original scope: finish an open dialog without purchases or queue changes. See [current scope](#scope-and-entry-points).

## Standalone speedup module (approved 2026-11-06)

The approved injected-function design separated caller-owned entry/completion from pure planning and had no `quick_finish` permission flag inside the speedup API. Generic count verification remains distinct from checkpoint batch verification; per-item confirmation is intentionally omitted in the checkpoint path for speed. The user requested a generic below-20% replan as a future feature, but it is disabled in the current MVP by the 2026-11-11 decision.

## Scroll calibration workflow (approved 2026-11-06)

Approved non-finishing wheel calibration, no purchases/item clicks, safe pointer placement and first-unchanged-view stop are retained under [calibration](#calibration-mapping-and-evidence).

### User-reported list landmarks and approved checkpoint test

Reported landmarks: 3: 15m/1h/3h/8h; 11: 15h/1d/3d/7d; 16: 3d/7d/30d and reported end. Historical review established 4/3/3 complete Use buttons: step-11 7d was clipped and step-16 supplied its full location. 1m could be omitted. Old duplicate text claiming repeated complete 7d at both checkpoints is superseded by this distinction. See [reading](#timer-and-checkpoint-inventory-reading) and [calibration evidence](#calibration-mapping-and-evidence).

## Desktop runner and direct CLI status

See [current entry points](#scope-and-entry-points). Callable desktop adapter exists; finishing CLI examples were a design, not an implemented parser.

## Direct-run finishing workflow (deferred)

Original command-line design anchor. Historical notes dated 2026-11-07 record approval of the default planner strategy for a direct supervised finish, mapped checkpoint inventory and soft floors/preferences. They described separate exact scan/use confirmation phrases (`SCAN SPEEDUP LIST FROM TOP` and `USE OWNED SPEEDUPS FROM TOP`). Those strings were interface intent, not implemented CLI guards or authorization for later live runs. The current [callable desktop route](#scope-and-entry-points) and separate [batch verification divergence](#use-verification-and-result-semantics) must not be inferred from that approval.

### Confirmed facts, assumptions, and deferred cases

Primary-monitor geometry is implemented; selected-window capture is not. See [scope](#scope-and-entry-points).

### Calibration implementation and validation

Earlier "pending calibration" notes preceded reported 2026-11-07 capture/review. See [dated evidence and actual validation scope](#calibration-mapping-and-evidence).

### Rules

Approved single-click/count-verification rules remain under [verification](#use-verification-and-result-semantics), including the explicit batch conflict. Old per-action screenshot requirements are superseded by [failure-only evidence](#calibration-mapping-and-evidence).

### Planning algorithm (`plan_speedups`)

See [current planning contract](#owned-item-planning).

### Flow

Current routing: recognized dialog and reliable mapped stock -> pure plan -> shortfall, dry-run plan or selected runner's use/verification loop -> caller task-screen confirmation. The old diagram's "timer or count dropped" does not replace generic count verification; see [runner-specific results](#use-verification-and-result-semantics).

### Caller integration (army training)

Original thin manager adapter was a design. The `speedup_fn` finish hook exists; migration does not assert end-to-end wiring. Ownership/completion remains with the [army workflow](army_training_slot_workflow.md).

### Open questions

Game confirmation/quantity prompts after Use and independently verified finished-dialog appearance remain evidence gaps; see [verification limits](#use-verification-and-result-semantics).

### Required evidence and tests

Use annotated regions/templates, explicit unreadable states, fake input adapters and focused fixture checks. Current [reading](#timer-and-checkpoint-inventory-reading), [verification](#use-verification-and-result-semantics) and [evidence](#calibration-mapping-and-evidence) sections link sources without claiming a test run.

## Confirmed facts

Desktop reference images show timer, owned rows, Use buttons and a separate Buy offer. See [screen card](../screens/speedup.md); visual evidence does not establish other task types/browser support.

## User-agreed preferences

Soft duration buckets/floors are retained in [planning](#owned-item-planning). Old `--execute` wording described a deferred CLI; current callables use `execute=True` or `dry_run=False`.

## Screen reader contract

See [current reader inputs, outputs and limits](#timer-and-checkpoint-inventory-reading). Automatic task classification, arbitrary duration OCR and generalized full-list reading were desired fields, not implemented facts.

### Implemented parsing foundation

Pure parsing remains separate from image recognition; see [reading](#timer-and-checkpoint-inventory-reading).

### Offline fixture scan

Offline reading performs no input. Supplied checkpoint identity/map is an input, not automatically inferred context; see [reading](#timer-and-checkpoint-inventory-reading).

### Optional live list scan — implementation approval pending

Historical pre-calibration design: selected-window capture, thumb recognition and generalized no-change scanning were proposed prerequisites. Later approved calibration/callable desktop scope instead uses checked primary-monitor geometry and annotated wheel input. Selected-window capture/generalized scanning remain deferred; see [entry points](#scope-and-entry-points) and [calibration](#calibration-mapping-and-evidence). This old heading neither denies existing callables nor authorizes a live run.

## Deferred recommendation and execution policy

Planner is implemented. Generic replan is disabled for the MVP; 50% checkpoint/polling remains deferred. Separate checkpoint batch behavior differs; see [verification](#use-verification-and-result-semantics).

## Reader state and failure handling

See [incomplete readings](#timer-and-checkpoint-inventory-reading) and [results](#use-verification-and-result-semantics). No-change endpoint applies to generic scanning/calibration, not fixed checkpoint scanning, where it is a mismatch.

## Confirmed facts, assumptions, and deferred work

Deferred scope is listed per feature: new task/client integration, timer formats/digits, arbitrary layouts, selected-window capture, finishing CLI and 50% polling. Purchases/gold remain out of scope. Old claims that planner/checkpoint quantity reading were pending are superseded by inspected implementations, not an unperformed test run.

### Assumptions to verify

Caller must supply correct visible account/task/dialog and matching desktop scale. Reliable new timer/layout formats and equivalent dialogs across task types are not established. See [scope](#scope-and-entry-points).

### Deferred

See each feature's proposed/deferred subsection; consolidation implies no new implementation approval.

## Current implementation status

Retained redirect to the single [current evidence baseline](#feature-contents) and feature-specific status subsections. Old snapshots claiming inventory reading or planner were wholly absent are historical, not current status.

## Expected tests before implementation is considered complete

Focused source references are listed per feature. Automated tests are delegated to the coordinating agent after migration; **none were run here**. Fixture sources do not establish supervised live use, all-format timer support, profile-isolation guarantees or resolution of batch/count-verification conflict. No regions, assets or Python behavior changed in this task.
