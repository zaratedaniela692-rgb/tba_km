# Legacy Automation Workflow

## Migration Validation Run

Full automated repository suite executed 2026-11-10 in the workspace venv with local Tesseract on PATH and `--continue-on-collection-errors`: **345 passed, 19 failed, 8 errors**. This does not establish legacy action safety; no live command, premium purchase, march, or legacy input path was exercised. Source-review limitations and unaudited branches below still apply.

## Feature Contents

- [Watchtower access and shared live-input boundaries](#watchtower-access-and-shared-live-input-boundaries)
- [Mine discovery and alerts](#mine-discovery-and-alerts)
- [Crypt exploration and march acceleration](#crypt-exploration-and-march-acceleration)

This area records bounded legacy behavior, not a declaration that all legacy branches or the whole project are audited. This documentation-only migration authorizes no game input, purchases, or resource spending. Shared game facts remain in [mechaniki.md](mechaniki.md), and visual Watchtower evidence remains in [world_map.md](../screens/world_map.md).

## Watchtower Access and Shared Live-Input Boundaries

### Purpose and Current Behavior

Legacy mine and crypt flows locate the generic `watchtower` sample and click it. They do **not** implement the documented red/blue premium-access gate. Existing locked/unlocked assets and historical verifier results are recognition evidence, not integration into these action paths.

### Inputs and Defaults

The flows use `Automator` and legacy samples, not the world-map locked/unlocked region contract. Mine CLIs default to `scale=1.0`; Crypt constructs a default `Automator`. Its capture uses `mss.monitors[1]`, not a selected game window. Callers must ensure the intended desktop/client, account, focus, and scale; these entry points supply no profile identity verification or browser-safe routing.

### Algorithm and Outputs

Mine `click_watchtower` waits up to four seconds for `watchtower`, clicks it, then recognizes `mines_selected_PL` or clicks `mines_unselected_PL` (two-second waits). Missing patterns or a stop request return `False`. Crypt uses its own two-second Watchtower/tab path, described below. No premium state result or authorized-purchase result is returned.

The required access policy is: red means unavailable, blue means available, and unknown must stop before Watchtower actions. A gold purchase requires separate explicit authorization and subsequent blue-state verification. **That gate and purchase flow are not implemented in the inspected paths.** No dedicated premium purchase routine was found there; generic clicks are not a spending safeguard.

### Safety and Limitations

- Mine `--click` gates candidate Go clicks only. Opening Watchtower, switching tabs, moving the pointer, and scrolling remain live input without it, including with `--dry-run`. Neither option is an offline safety boundary.
- `Automator.click` directly calls PyAutoGUI without a kill-file check. Its constructor deletes an existing `~/.tba_stop`; polling in `Automator.loop` removes a newly observed kill-file and raises an exception. Legacy outer retry loops can catch exceptions, so this is not a guaranteed process-wide stop latch. Direct scrolling also bypasses that polling.
- Mine modules register SIGINT/SIGTERM handlers, set `stop_event`, and start a force-exit thread after approximately 0.2 seconds. Some waits and action sites check the event, but immediate cancellation of every nested operation is not proven. Crypt has no corresponding local event/handler mechanism.
- Mine scripts attempt full-screen writes after opening the tab and before busy detection, regardless of `--debug`. These ordinary live-path writes conflict with the current failure-only screenshot policy. Conditional ROI diagnostics do not excuse them; see the separate Crypt write conflict below.
- Repeated legacy loops may call `restart_game(True)` after ten failures or 900 seconds, outside candidate `--click` gating. Restart forwards to refresh/start-game behavior; its full input sequence was not audited here.

### Status and Verification

**Source review: 2026-11-10.** Generic opening paths, mine CLI guards/retry loops, Crypt entry/action paths, and the shared capture/click/kill-file boundaries were inspected. No tests or live actions were executed. The premium gate is a documented requirement, not implemented behavior. Emergency-stop latency, correct-account input, purchase avoidance under wrong recognition, and restart completion were not demonstrated.

### Proposed and Deferred Changes

Implement fail-closed premium recognition before any Watchtower input; keep purchase authorization separate. Unify genuinely input-free dry-run behavior, reliable stop propagation, profile/client checks, and failure-only evidence writes in later explicitly authorized changes. No such code change is approved by this migration.

### Implementation and Tests

- [mines.py](../../mines.py) and [watchtower_mines.py](../../watchtower_mines.py): `click_watchtower`, signal handling, and CLI loops.
- [crypt.py](../../crypt.py): `crypt`, `speedup`, and module-level CLI loop.
- [automate.py](../../automate.py): `Automator.__init__`, `click`, `update`, `check_kill_file`, `loop`, and `restart_game` boundaries only.
- [world_map.md](../screens/world_map.md#stan-premium-watchtower): visual states and historical verification; [tests/test_verify_regression.py](../../tests/test_verify_regression.py) is a referenced recognition test, not reviewed or executed here and not proof of an action gate.
- [WATCHTOWER_MINES_PLAN.md](../../WATCHTOWER_MINES_PLAN.md) is a historical stop-handling note. Its proposed dry-run live check is not evidence that dry-run sends no input or that cancellation was verified.

## Mine Discovery and Alerts

### Purpose and Current Behavior

Find candidate mines through Watchtower, inspect occupancy after Go, and sound an alert. `mines.py` supports `dm`, `ws`, and `sm`; `watchtower_mines.py` is the older `dm`-oriented scanner. An alert is a heuristic discovery result, not proof of successful gathering, ownership, or a dispatched march.

### Inputs and Defaults

- Both CLIs default `--click`, `--dry-run`, `--debug`, overlay precheck, and optional post-click confirmation to false. `--post-click-wait=1.0`, Go offsets `(6,2)`, `--dm-busy-threshold=0.08`, and alert duration 15 seconds. Optional occupied-color checking uses tolerance 40 and pixel fraction 0.02. These are legacy template/color thresholds, not OCR confidence percentages.
- `mines.py`: `--type=dm`, loop sleep 30 seconds, six scroll steps, `--cache-ttl=2.0` hours, `--once` off. CLI derives `<type>_list` and `mines/<type>_busy`, overriding the parsed list-pattern value. Tesseract availability is checked before the scan. Mine-presence and territory checks are opt-in, both off by default.
- `watchtower_mines.py`: `--list-pattern=dm_list`, loop sleep 45 seconds (despite help text saying 30), eight scroll steps. No generalized mine-type/cache/private-label contract is established for this older path.
- Both use fixed scroll position `(1216,600)`, maximum 20 downward batches, slider bottom Y 770/top Y 465, and maximum 15 reset attempts. Row/Go pairing uses estimated heights 40/32, bottom-edge Y tolerance 45, and Go-minus-row X range 250-650. These geometry defaults are not newly calibrated coordinates.

### Algorithm and Outputs

1. Open Watchtower/Mines and detect list rows plus Go candidates. For each row, choose the geometrically closest valid Go by bottom-edge Y difference. No mapped pair means no candidate Go click; this does not prove globally unique pairing.
2. In `mines.py`, OCR-filter private labels: at least three cleaned letters/spaces means private; blank/noise means public. **An OCR exception also means public.** Read raw resource/distance labels and skip matching unexpired busy-cache entries. These record strings use separate legacy OCR, not the [shared resource measurement API](resource_reading_workflow.md#offline-resource-measurements).
3. Apply optional overlay/color prechecks. Dry-run logs a would-be Go and skips it; otherwise Go requires `--click`. Optional post-click pattern/confirmation can add clicks. Inspect the busy template for up to two seconds: a match means occupied; no match triggers an alert, subject to the generalized scanner's optional checks.
4. `mines.py` can require mine presence (default timeout 2 seconds, threshold 0.15). Optional territory checking clicks map-field offsets (default `(0,120)`, or a supplied list), then clicks **fixed** `--zbuduj-x/--zbuduj-y` and waits for `mines/territory_check` (default 3 seconds, threshold 0.10). Missing coordinates fail that check. The advertised build-template flags do not replace the fixed-coordinate click in this helper.
5. Reopen Watchtower after occupied/free checks. Scroll until the slider is absent, its Y reaches the configured bottom, or the iteration cap is reached; try resetting to the top. This is not observed-unchanged-view completion. Missing/erroring slider detection can be treated as a fully visible list.

The scan returns whether any post-click path produced a free-mine result. `mines.py --once` maps that to exit 0/1 and caught scan exceptions to 2; 1 does not prove every mine was occupied, and without candidate clicks it is not a verified occupancy scan. Normal mode repeats with failure counts and timed restarts.

The generalized scanner caches busy entries in `cache/<type>_cache.json`. Keys require OCR distance containing digits plus `km`; optional K/M resource text is added when valid, otherwise distance alone is used. Entries contain added/expiry timestamps. Unreadable distance is not cached; expired entries are removed. This is a mine suppression cache, not a balance cache, and is **not profile-scoped**; collisions across accounts or similar labels are possible.

### Safety and Limitations

Absence of a busy match is not positive proof that a mine is free; wrong screens and poor matches can cause false alerts. Private-label OCR fails open. Optional presence/territory checks are not default protections; the fixed build click may change game state and is not authorized by this document. No spending/cost guard was established for that branch. Generalized record resource offsets are marked as needing calibration in source.

Full-screen tab/busy writes are unconditional attempts in ordinary scan paths. Player-label ROIs require `--debug` or `--player-label-debug`; color ROIs require `--debug` or `--dry-run` when color checking is active; click ROIs require `--debug`. Evidence files and suppression caches are not isolated by profile/run. Apply the [shared live-input limitations](#watchtower-access-and-shared-live-input-boundaries) even when only alerts are intended.

### Status and Verification

**Source review: 2026-11-10.** Reviewed generalized opening, private-label filtering, record/cache behavior, mapping, candidate/post-click/territory control, list termination, and CLI paths; reviewed corresponding first-block older scanner paths and its repeated CLI tail. No tests were executed. A filename search and focused test-source import/helper search found no dedicated tests for these scanners; this does not rule out indirect coverage.

`watchtower_mines.py` contains a second near-duplicate program block, including another `__main__` loop. The first CLI loop runs before that second block is reached; importing the file reaches later definitions. Duplicate equivalence, all second-block helpers, module import side effects, audio fallbacks, every exception path, threshold calibration, and actual list completeness remain unaudited. No live verification or syntax/execution check was performed.

### Proposed and Deferred Changes

Defer duplicate-program consolidation, fail-closed OCR/occupancy decisions, profile-scoped suppression, verified unchanged-view termination, calibrated geometry, safe territory interaction, and test coverage. These are gaps/proposals, not implemented guarantees or permission to resume scans.

### Implementation and Tests

- [mines.py](../../mines.py): `is_public_mine_ocr`, `extract_record_info`, cache helpers, `detect_list_and_go`, `iterate_go_sequence`, `_post_click_handle`, territory helpers, `mines`, and CLI.
- [watchtower_mines.py](../../watchtower_mines.py): older mapping/scanning/alert path and duplicate-program caveat above.
- [WATCHTOWER_MINES_PLAN.md](../../WATCHTOWER_MINES_PLAN.md): historical cancellation follow-up only; no dedicated scanner test result is available from this migration.

## Crypt Exploration and March Acceleration

### Purpose and Current Behavior

The CLI continuously selects/explores crypts and attempts march acceleration. Unlike the mine candidate path, Crypt has **no `--click` opt-in and no dry-run**: starting it may immediately send game input. Importing the module must remain passive: argument parsing, `Automator` construction, and the live loop belong inside `main()` and under a `__main__` guard. Direct script execution preserves the existing CLI and live behavior; import must never start game input.

### Inputs and Defaults

`--type`/`-t` defaults to `common`; recognized values are `common`, `rare`, and `epic`, selecting hard-coded sample lists. Unknown types exit 1. `--min-progress`/`-p` is an integer defaulting to 0; positive values enable the progress gate. No 0-100 range validation is present. No profile, balance, premium, or acceleration-budget input is supplied.

### Algorithm and Outputs

1. Each outer iteration first calls `speedup`. If `carter_march` matches, click offset `(190,8)`; when `speedup` matches, click offset `(360,36)` six times and wait 1.5 seconds. A march match returns `True` even if the speedup panel fails to match, suppressing crypt selection for that iteration.
2. Otherwise locate/click Watchtower, locate/click a crypt tab, randomly choose a Watchtower Go, then detect configured map crypt samples. Each prerequisite has a short two/four-second template wait and returns `False` on missing evidence.
3. OCR a progress crop for every detected crypt using grayscale/Otsu, 2x scaling, PSM 7, and a digit/percent whitelist. Collect digits as an integer, without confidence or percentage-range validation. Positive thresholds with no candidates call `exit(0)`; zero disables the required OCR gate, so unreadable progress need not stop selection.
4. Narrow candidates when available, apply two hard-coded color exclusions, choose a central crypt, and click it. Re-associate the selection to the nearest readable OCR location within 40 pixels; with a positive threshold, unknown/low progress aborts before further exploration clicks, but selection already occurred.
5. Require `carter_selected` and `selected`; rare crypts additionally require/click `rare_open`. Require/click `explore` at offset `(0,10)`, then require `carter_march`. A `True` result confirms only that final template match, not completion or validated resource consumption.

Failures increment the outer counter; successful exploration resets it. Ten failures or 900 seconds trigger `restart_game(True)`. There is no explicit outer loop sleep beyond nested operations and no mine-style catch around the whole loop.

### Safety and Limitations

Crypt OCR is called with `debug=True` unconditionally and attempts thresholded ROI writes to `ocr_debug` for each readable crop, without a CLI diagnostic switch. This conflicts with the current failure-only evidence policy and with the legacy note describing Crypt ROI writes as opt-in. The source review takes precedence for reporting current behavior; neither shared document was edited here.

March acceleration is automatic and offset-based, with six clicks and no owned-item inventory, gold exclusion, cost confirmation, or completion check in this routine. Do not equate it with the newer guarded speedup workflow. Resource/item use, incorrect-screen clicks, and premium access are not protected by an explicit contract in this path. Progress OCR has no confidence gate; color exclusions are heuristics, not validated ownership checks. Shared monitor/stop limitations apply.

### Status and Verification

**Source review: 2026-11-10.** Crypt CLI, exploration selection/progress gates, evidence writes, acceleration helper, and outer loop were inspected. The import-safe entrypoint is the first structural refactor slice; an automated import test is added in the same change. No live actions are authorized or performed by this refactor. Crypt sample correctness, excluded-color meaning, rare-open costs, actual item/gold effects of acceleration, restart internals, and reliable cancellation remain unverified. This is not approval of these unsafe legacy defaults.

### Proposed and Deferred Changes

Defer explicit input opt-in/dry-run, import-safe entry point, premium/profile gates, confidence-aware progress validation, opt-in/failure-only diagnostics, and acceleration inventory/currency/postcondition safeguards to separately approved implementation work. No attempt to validate a risky action by repeating it is authorized.

### Implementation and Tests

- [crypt.py](../../crypt.py): `crypt`, nested `read_progress`, `speedup`, and guarded `main`; [tests/test_crypt.py](../../tests/test_crypt.py) verifies import is passive even with unrelated CLI arguments, module definitions import, and `--help` runs without live input dependencies. Focused result: **3 passed** on 2026-11-10. No game input or live loop was run; this test does not certify crypt action safety.
- [automate.py](../../automate.py): shared live-input boundaries described above; crypt-specific template selection internals were not comprehensively audited.
- [mechaniki.md](mechaniki.md): the legacy evidence-policy section requires main-agent correction of the Crypt opt-in claim; the current source unconditionally requests progress ROI writes.