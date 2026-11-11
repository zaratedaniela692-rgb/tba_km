# Project Refactor Log

## Purpose and Scope

This document is a single reviewable summary of the recent organization/refactor work. It records why each change was made, the intended effect, and the validation actually run. It is not a claim that the whole repository has been rewritten or that the full suite is green.

The user's current refactor scope is limited to:

- Speed Up
- Army training
- Task manager / task queue

Legacy flows (Crypt, mines, Watchtower, and other legacy automation) are out of scope for ongoing work unless the user reopens that scope. A small earlier Crypt import-safety change is documented separately as pre-scope work; it is not permission to continue refactoring legacy flows.

## Plan and Remaining Stages

The agreed program has **four named stages**. Some stages are partially complete; the remaining work inside them may still require multiple small, validated slices. This is a scope count, not a promise of four commits.

1. **Speed Up:** the runnable module/test baseline and initial-plan-only MVP policy are complete for the current generic path. The full `tests/test_speedup*.py` suite passes **177 tests**. Per-item quantity confirmation in the checkpoint runner is intentionally omitted for speed. The existing hidden-remainder behavior is left unchanged and its review is deferred from the current MVP. A single generic replan below 20% is a requested future enhancement, not an MVP blocker. Do not revive a live CLI or merge runners while other batch semantics remain unreviewed.
2. **Army training:** complete for the current structural/offline scope on 2026-11-11. Selector consensus and campaign lookup are isolated; the shared action-control reader and test-only E2E finisher are implemented. Manager dispatch delegates test completion/persistence and names its fallback/stock selection decisions; executor start/preflight/marker acceptance is separated from post-start Help coordination. Profile, dry-run, confirmation, stop, no-retry, selection order and resource policies are preserved. All `tests/test_army_*.py` plus task-controller/client-router/E2E tests passed **262 tests**; adjacent Speed Up adapter/core/planner/reader tests passed **54 tests**. This closes the maintainability/testability stage, not live certification or implementation of deferred features.
3. **Task manager / queue:** complete for the agreed contract/offline scope on 2026-11-11. Shared parallelism, automatic/direct-executor retry deadlines, silver-only three-attempt budget, army hold and explicit resume/history are implemented. Global pause blocks manager navigation/direct fallback; silver hold still permits existing-training completion. Retry archives are validated before resume mutations. Final integrated all-army/queue/router/E2E validation: **303 passed**; adjacent Speed Up set: **54 passed**. The queue owns shared state rules while army retains fresh visual evaluation/execution and existing fallback precedence. This is not replacement of both selection paths by one scheduler. Hidden-silver recovery and uncertain-read repair remain passive/deferred.
4. **Per-module and cross-module test runners:** complete for the agreed offline wrapper scope on 2026-11-11. Added no-argument wrappers for Speed Up planning, Army screen recognition and task-queue readiness, plus a separate injected-callback E2E that simulates owned Speed Up completion -> stock-goal reconciliation -> queue selection in memory. All report mode, scenario, evidence inputs and side effects; arguments fail closed. Existing live army runners remain separate, retain their gates, and were not invoked or certified by this stage.

Stages 1-4 are complete for their stated MVP/structural/contract/offline-wrapper scopes. This does not certify live execution. The requested below-20% replan, ordinary owned-training live finish integration, browser readiness, hidden-silver recovery/read repair and new recognition/action features remain explicitly deferred. No live run is part of these stages unless separately authorized.

## Deferred Backlog (Not Scheduled)

These are parking-lot items, not active work or implementation approval. Pick up each item separately when needed and update its owning workflow before changing behavior.

- Implement hidden-silver recovery with its own visual workflow and fresh full preflight after confirmed replenishment. Define the concrete repair actions for uncertain silver reads; never retry uncertain resource use.
- Wire ordinary marker-based training completion to the live Speed Up adapter. Keep the existing test-only finisher separate and preserve no-retry behavior.
- Complete browser Speed Up readiness using browser-specific screen evidence, annotations and callbacks. Keep its gate closed until those checks pass; any live browser run needs separate authorization.
- Implement and test the requested single generic Speed Up replan below 20%. It remains disabled in the current MVP.
- Consider unifying generic and army scheduler selection paths. This is not required for the completed queue contract and must preserve army's fresh visual evaluation and fallback order.
- Supervised live validation of selected wrappers/E2E flows. Request authorization for the exact profile, runner and permitted actions before any live run; offline wrapper results do not authorize game input or resource use.

Stage 3 closure criteria: queue-owned common lifecycle gates and retry/hold bookkeeping; deadline enforcement before automatic reconciliation and direct executor input; explicit three-attempt silver-only handling with resumable profile-scoped army hold; global pause distinct from resource hold; preserved profile/task/marker history and tested failure handling; stable priority/fallback/manual-read contracts and final integrated offline evidence. The army domain keeps its separate visual evaluation/selection path, rather than forcing generic cached-resource selection onto game execution. Repository-wide tests, live operation, new task-type executors and stage 4 wrappers are not implied by closure.

Stage 2 closure criteria: explicit manager decisions without generic-scheduler unification; isolated executor post-start Help with preserved timestamps and exception boundaries; tested shared-control/test-finisher behavior; queue/marker/profile/no-retry regressions; current full desktop army test evidence and aligned workflow. Remaining executor preflight, selector and Train logic stays local to the owning function rather than introducing a new context abstraction. No claim is made that every module has been rewritten, every project test passes, or live training is reliable.

## Most Important Changes (Assessment)

This is a priority assessment by expected impact, not an additional implementation contract.

1. **Speed Up replanning disabled for the MVP.** Most important for predictable resource use: the generic runner no longer computes replacement item uses after Help/timer changes. The initial plan is the spending ceiling; an incomplete or uncertain outcome stops for review. A future below-20% replan is requested separately.
2. **Speed Up modules made testable again.** Restoring Tesseract configuration and inert test-support symbols removed import/collection blockers; the complete scoped Speed Up suite subsequently passed 177 tests. The historical live CLI was deliberately not restored.
3. **Browser Speed Up isolated from global browser readiness.** The feature-specific adapter shares core mechanics without enabling army training, profile routing, or other web actions. It remains blocked pending its own screen assets and callbacks.
4. **Queue readiness made explicit.** Named predicates make stock-decision freshness, active-task parallelism, and resource availability easier to reason about while preserving the original scheduler order and side effects.
5. **Army selector OCR consensus deduplicated.** One helper owns the repeated token/confidence agreement logic, reducing the chance that masked/raw paths drift while keeping current recognition thresholds and outcomes.

The first three primarily improve safety/testability boundaries; the last two are maintainability improvements. All listed tests are offline and do not establish live behavior.

## Completed Changes

### Stage 4 Closure: Offline Module and E2E Wrappers

**Change:** added four no-argument tools: `test_speedup_module.py` (synthetic inventory through the pure planner), `test_army_training_module.py` (read-only completed-control fixture), `test_task_queue_module.py` (in-memory readiness under army hold), and `test_army_queue_e2e.py` (injected callback simulation of the existing Speed Up core, then stock reconciliation and queue selection). They configure their target via constants, reject CLI arguments, emit structured JSON and cannot import the desktop live adapter. The live `run_army_e2e.py` and navigation wrapper remain separate and unchanged.

**Validation:** all four wrappers returned `PASSED` when run directly without arguments. `tests/test_module_wrappers.py`: **4 passed**; it checks reports, argument rejection before dependencies, injected errors and missing fixture behavior. Combined supporting wrapper/scanner/queue/process/Speed Up core tests: **110 passed**. No live wrapper, game input, queue persistence or resource use occurred. Existing live wrappers were not certified by this stage.

### Stage 3 Closure: Queue Boundaries and Resume Validation

**Change:** validated hold/retry archive container types before any resume mutation. Two invalid-archive tests require byte-for-byte-equivalent in-memory data on refusal; a manager resume write-failure test requires the saved hold and budgets to remain unchanged. Consolidated the authoritative queue status and documented the final split: shared queue rules versus army visual evaluation/execution. No retry timing, spending, priority or fallback semantics changed in this final slice.

**Validation:** all `tests/test_army_*.py` plus queue/client-router/E2E **303 passed**, adjacent Speed Up live/core/planner/reader **54 passed**, focused queue/manager/executor/finish/process/lifecycle/E2E **181 passed** on 2026-11-11. Tesseract was temporarily available on PATH for the integrated OCR run. No live game, commit or push occurred. Full scheduler replacement and hidden-silver/OCR recovery remain deferred; stage 4 is next.

### Stage 3: Global Pause Covers Fallback Finishing

**Change:** global queue pause now returns `BLOCKED_PAUSED_QUEUE` with the pause reason before army manager navigation/expiry bookkeeping, including navigation-only and test-only finishing. Direct `execute_finish_task(execute=True)` rejects pause before marker reads, no-op task completion, capture or speedup adapter calls. Preview remains available; the narrower silver hold still permits finishing existing training. No retry/priority/resource-spend rules were altered.

**Validation:** manager/finish/E2E/queue/executor/lifecycle/process: **178 passed** on 2026-11-11. Six new cases cover three live manager modes, preview and direct fallback with/without a marker, asserting no input and retained queue/marker data. Editor diagnostics report no errors. No live operation, commit or push occurred. Global pause policy is resolved; generic/army scheduler replacement is not claimed.

### Stage 3: Direct Executor Deadline Guard

**Change:** `execute_training_goal` now rejects a future `next_check_at` before capture, selector or quantity input, closing the direct-call bypass of manager deadline filtering. The exact deadline is due; preview/manual image reconciliation is unchanged. No attempt is consumed and no queue mutation occurs on rejection.

**Validation:** three before/at/after-deadline regressions; focused executor/queue **69 passed** and integrated all-army/queue/router/E2E **294 passed** on 2026-11-11 with temporary Tesseract PATH. No live action occurred. This was an intermediate slice before the global-pause/fallback decision was implemented; the distinct army-resource hold still permits completing existing training.

### Stage 3: Silver Retry Budget and Resumable Army Hold

**Change:** a confirmed final silver-only preflight failure passes through the passive hidden-silver recovery extension (`not_implemented`) and records a failed attempt. Default budget is three total attempts: defer twice using the configured resource retry interval, then hold all new training for that profile without cancelling tasks. Other task types and existing-training fallback completion remain available. Queue, executor and automatic manager enforce the hold; list reports reason/history. Confirmed local `resume-army` archives previous attempts, resets pending budgets/decisions and clears only the army hold. Global pause, active tasks and markers are unchanged.

**Validation:** **180 tests passed** across queue/executor/manager/process/finish/campaign/lifecycle/E2E on 2026-11-11. Coverage includes persistence, deadline/count boundary, unknown OCR/food exclusions, no Train, other tasks/fallbacks, explicit resume/profile gates, archived history and active-marker preservation. The intermediate cancellation implementation was replaced before any live use. Hidden-resource use and silver OCR repair remain unimplemented pending their own visual workflows; no live action or purchase occurred. Stage 3 is still not a claim of complete generic/army scheduler unification.

### Stage 3: Automatic Army Retry Deadlines

**Change:** automatic army execution filters category candidates by retry deadline and enables `respect_next_check` in goal evaluation. Future-dated goals return a deferred report before slot resolution/OCR, without mutating their task/process or clearing `next_check_at`. Deadlines are inclusive: a task is due exactly at its recorded time. Other due goals may proceed; pinned E2E goals are never substituted. Manual `run --image` retains early observation and only persists with `--save`. Fallback precedence, retry intervals and live resource guards remain unchanged.

**Validation:** manager/E2E/queue/process/executor/finish/lifecycle: **161 passed** on 2026-11-11. Cases verify task/process preservation, before/at/after deadlines, manual preview/save, due-category selection, bypass of a deferred higher-priority goal, E2E pinning and fallback precedence. Pylance reports all eight evaluation call sites compatible; no code/test diagnostics found. No live operation, commit or push was performed. Stage 3 remains in progress; this is deadline integration, not full scheduler unification.

### Stage 3: Shared Start Parallelism Rule

**Change:** added pure `task_parallelism_blocker` in the queue module and routed the existing generic selection predicate, `mark_task_started` and army executor through it. The helper gives same-type active work precedence, otherwise requires every cross-type task to be waiting for completion with known remaining time strictly above the configured threshold. No task data is mutated by the helper; callers preserve existing gates, error messages, priorities and retry behavior.

**Validation:** queue/executor/manager/finish/process/lifecycle/E2E: **151 passed** on 2026-11-11. Direct and integration checks cover 60/61 boundaries, unknown time, multiple active tasks, rejection without mutation, and executor rejection before capture or click. Editor diagnostics show no errors in the modified code/tests. No live operation occurred. Stage 3 remains in progress; `next_check_at`, resource retry and fallback selection policies were not unified.

### Stage 2 Closure: Manager Decisions and Post-Start Help

**Change:** extracted `_next_due_finish_task` and `_select_executable_goal` in the manager, preserving fallback list order, priority/creation/report tie ordering, report eligibility and pinned test-task filtering. Extracted `_request_help_after_confirmed_start` in the executor, leaving Train confirmation and marker acceptance in `execute_training_goal`. The Help helper preserves delays, timestamps, emergency-stop behavior, uncertainty pauses, checkpoints and one-shot input. It neither selects tasks nor persists state nor consumes Speed Ups.

**Validation:** **262 passed** for every `tests/test_army_*.py` plus task-controller/client-router/E2E tests; **54 passed** for Speed Up live adapter/core/planner/reader tests, on 2026-11-11. Four old planner fixture assertions were updated from portrait-detail expectations to the already approved shared-control contract; their active/idle checks remain. New tests cover ordering/no mutation, before/after-Help capture/geometry failures, retained marker/started task, exact lifecycle times and quick-finish readiness without acceleration. No regions/templates were changed and no live game actions, commit or push occurred.

**Limits:** browser fixture readiness, ordinary live finish-adapter wiring, generic/army scheduling unification and complete per-module wrappers are not stage 2 closure claims. The repository-wide suite was not run; live dependencies and account/occlusion limitations remain as documented in the area workflows.

### Army Manager: Test Completion Stage Boundary

**Change:** extracted the existing test-only completion block from `_command_execute` into `_finish_test_training`, with an explicit capture callback. Command-level profile/mode/pause gates remain in place; the helper retains Barracks confirmation, executor invocation, error reports and queue-before-marker reconciliation.

**Why:** separate CLI dispatch and gates from the executor completion result and persistence steps without enabling ordinary live finishing or changing task selection.

**Validation:** manager/E2E/executor/marker-finish tests: **84 passed** on 2026-11-11. Existing file-preservation tests pass; two direct helper cases verify no capture on unconfirmed Barracks and no marker reconciliation or queue save on an unconfirmed finish result. Editor diagnostics report no errors in the changed code/tests. No live game action was performed. This was an intermediate stage 2 slice; current closure is recorded above.

### Army E2E: Finish Existing Training Safely

**Change:** unified desktop Help/Speed Up/idle/completed classification in the scanner; completed the existing test-only Help -> Speed Up adapter -> optional one-shot Finish -> fresh idle helper with geometry, emergency-stop and no-retry gates. Manager rejects other profiles before navigation, loads preflight queues without migration writes, saves reconciled marker-owned task/fallback before clearing the marker, and preserves unrelated tasks. Runner keeps preflight evidence, prepares/re-arms only after success without clearing history, and pins its task ID so another goal cannot be substituted.

**Why:** partial session changes could misclassify completed as idle, fail in exception handling, discard unrelated queued work, or train a different existing goal. The existing `configure_tesseract` import was verified working and did not require repair.

**Validation:** final focused desktop scanner/executor/manager/E2E/finish/live-helper/queue/router/navigation and Speed Up live/reader/core/planner set: **193 passed** on 2026-11-11, with Windows Tesseract temporarily on PATH. Fixed the obsolete category-hook test to assert the existing Guardsmen-only gate and updated one shared finish-test preflight mock. Offline template verification matched Finish at 100% on the completion fixture; other screen elements include below-threshold results. Five browser fixture tests remain blocked by the existing `planned` gate. Live dependencies `mss`/`pyautogui` are unresolved by Pylance. No game launch, clicks, item use, commit or push was performed. Ordinary marker-based finish-adapter integration remains deferred.

### Passive Crypt Import (Pre-Scope Work)

**Change:** moved Crypt argument parsing, `Automator` construction and the infinite execution loop into `main()` behind `if __name__ == "__main__"`; deferred the live `Automator` import until CLI execution. Added `tests/test_crypt.py` and recorded the contract in the legacy workflow.

**Why:** importing a Python module unexpectedly parsed the host process arguments, loaded live input dependencies and started automation. That made imports unsafe for tests and tooling.

**Expected effect:** `import crypt` is passive; direct `crypt.py` execution retains its command-line flow. `--help` works without initializing the live input layer.

**Validation:** `tests/test_crypt.py`: **3 passed** on 2026-11-10. No live Crypt loop was run. This work happened before the user later restricted refactoring to Speed Up, Army training and Task manager; do not extend it to other legacy flows without renewed scope.

### Speed Up: Tesseract Setup and Inert Test Support

**Change:** restored `configure_tesseract(executable=None)` in `speedup_reader.py`, including explicit executable, `TESSERACT_CMD`, PATH and standard Windows installation lookup. Restored optional `tesseract_cmd` on `read_remaining_time`. Restored only passive compatibility/test helpers in `speedup_run.py` (`EvidenceCapture`, `SCAN_CONFIRMATION`, `USE_CONFIRMATION`); no live CLI was added. Added focused helper tests.

**Why:** `speedup_inventory_reader.py` and `speedup_live.py` imported a missing helper, preventing Speed Up tests and adapters from collecting. A test and device harness also import the evidence/confirmation symbols from an empty `speedup_run.py`.

**Expected effect:** the Speed Up reader/inventory/desktop modules import and tests can run; Tesseract resolution has one shared helper. Evidence capture saves only configured checkpoint frames and retains the latest frame/error list. The legacy live runner remains absent because its item-use policy is not yet resolved.

**Validation:** reader plus passive-runner tests: **12 passed**. Full `tests/test_speedup*.py` run after restoring these symbols: **176 passed, 1 failed** before the no-replan decision below. Later full result is recorded in the next item. No game input was performed.

### Speed Up: Initial-Plan-Only MVP

**Change:** disabled the generic orchestrator's automatic below-20% replan. The initial planner result is now the only list of items eligible for use. Kept the possible replan code commented as a deferred option. Updated the Help/clan-Help regression and workflow.

**Why:** the user explicitly chose not to have replanning in the MVP, preferring the runner not to generate additional item use after timer changes.

**Expected effect:** after each verified use, the runner may observe the timer but never creates or executes a replacement plan. If the dialog closes before all original planned uses are confirmed, return `UNCERTAIN` and do not retry. If the initial plan is exhausted while time remains, the existing uncertain terminal result is preserved.

**Validation:** Speed Up core: **21 passed**. Full `tests/test_speedup*.py`: **177 passed**. No live item use was performed.

### Speed Up: Web-Only Adapter Boundary

**Change:** added `speedup_browser.py` and mocked tests. Browser adapter uses the shared `speedup.finish_with_speedups` core but has its own `BROWSER_SPEEDUP_ASSETS_READY=False` gate. It does not depend on global browser UI readiness and identifies callbacks by browser client ID. Updated Speed Up and UI readiness workflows.

**Why:** user wants Speed Up to be the sole web feature exception eventually, without enabling other browser game flows or duplicating planner logic.

**Expected effect:** a future browser reader/input adapter can feed the shared planning/use engine. Today, production entry remains blocked before callbacks; no desktop coordinates/assets are borrowed. Global browser readiness remains `planned`.

**Validation:** final browser adapter + core/planner run after making the feature readiness independent of global browser UI readiness: **47 passed**. The full Speed Up suite later passed **177 tests** with initial-plan-only behavior. No web screenshot or live browser action has been tested. Web execution is not ready.

### Army Training: Selector OCR Consensus

**Change:** extracted the repeated per-PSM Roman numeral OCR acceptance into `_read_consensus_roman_label` in `army_training_levels.py`. Added synthetic tests for confidence selection and disagreement rejection.

**Why:** masked and raw OCR preparations duplicated token filtering, threshold validation and agreement handling, making future adjustments easy to apply inconsistently.

**Expected effect:** one implementation owns the consensus contract; OCR thresholds, PSMs, token mapping and caller behavior remain unchanged.

**Validation:** `tests/test_army_training_levels.py`: **10 passed** with the Windows Tesseract executable temporarily added to PATH. No live input was performed.

### Army Campaign: Existing Goal Lookup

**Change:** extracted current/legacy slot matching from the `expand_goals` loop into `_find_existing_goal` and added a regression for an existing untyped legacy goal.

**Why:** compatibility matching was embedded in campaign expansion and harder to review separately from the creation/re-arm decision.

**Expected effect:** keep matching order, old task identity, and `created`/`rearmed`/`kept` results unchanged while making the lookup contract explicit.

**Validation:** campaign tests **11 passed**; combined campaign/process/task-queue tests **50 passed**. No live action was performed.

### Task Manager: Queue Readiness Predicates

**Change:** extracted `_stock_goal_decision_is_current`, `_parallel_task_gate_allows` and `_has_required_resources` from `get_next_task` in `task_controller.py`.

**Why:** readiness logic was embedded in candidate iteration and mixed stock authorization, active-task constraints and inventory checks, making the selection order harder to inspect.

**Expected effect:** named, locally testable decisions while preserving candidate order, `next_check_at` behavior, resource-wait mutation/retry and return-copy behavior. The army manager's separate scheduler was intentionally not unified.

**Validation:** combined selector/process/queue/manager tests: **74 passed**. This is offline fixture coverage, not live queue dispatch evidence.

### Army Process Test Collection Cleanup

**Change:** removed one orphaned syntax fragment and duplicate test function definitions from `tests/test_army_training_process.py`.

**Why:** the orphan prevented collection with a SyntaxError; duplicate top-level names silently replaced earlier tests during Python module execution.

**Expected effect:** intended process tests are collectable and each same-named scenario is registered once.

**Validation:** `tests/test_army_training_process.py` + `tests/test_task_controller.py`: **39 passed** after syntax cleanup; later combined suite: **74 passed** after all scoped changes.

## Deliberately Not Changed

- Did not replace `army_training_manager._command_execute` with `task_controller.get_next_task`. Automatic army retry deadlines are now respected before reconciliation, but resource/decision-freshness handling and fallback ordering still differ. Manual image reconciliation intentionally retains its early-read behavior.
- Did not change Speed Up checkpoint batch spending, hidden-tail behavior, per-use confirmation guarantees or add a live CLI. Those behaviors need a separate explicit contract.
- Earlier structural slices left executor/scanner/manager local edits untouched. The later approved E2E completion slice builds on those existing changes without reverting them; unrelated live navigation changes remain preserved.
- Did not refactor legacy Mines, Watchtower or Crypt further after the scope was narrowed.
- Did not run any live game/browser actions as part of this refactor log.

## Known Validation Limits

The repository had a recorded full-suite baseline on 2026-11-10 of **345 passed, 19 failed, 8 errors** under its then-current worktree/options. This is historical and not a fresh run. Several army/queue tests were subsequently repaired and focused groups passed, but the full repository suite has not been rerun as a final gate. `tests/test_device_test.py` also has reported missing `repo` fixture / undefined names in the current worktree. Individual area results above are the actual scoped runs, not proof that unrelated failures are fixed.

## Source References

- [Speed Up workflow](speedup_module_workflow.md)
- [Army training workflow](army_training_slot_workflow.md)
- [Task manager contract](task_manager.md)
- [UI variants and browser readiness](ui_variants_plan.md)
- [Game-test instructions](../../.github/instructions/game-tests.instructions.md)
