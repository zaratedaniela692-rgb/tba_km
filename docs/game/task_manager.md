# Task Manager: Priorities Contract

## Migration Validation Run

Executed 2026-11-10 in the workspace venv with local Tesseract on PATH and `--continue-on-collection-errors`: combined army/queue group **161 passed, 8 failed, 1 collection error**; full repository **345 passed, 19 failed, 8 errors**. These aggregates are not an isolated queue pass claim. The training-process test cannot collect due to an unterminated string, and army integration assertions fail. Earlier source-review notes retain their narrower scope. No live actions or queue behavior changes were made by this documentation migration.

**Refactor and test follow-up (2026-11-11):** extracted stock-decision freshness, active-task parallelism, and resource-availability predicates from `get_next_task` without changing their order or mutations. Removed the stray syntax fragment from `tests/test_army_training_process.py`. The combined manager/process/queue tests pass: **64 passed**. This is offline fixture coverage, not live queue dispatch evidence.

This workflow owns queue scheduling and persistence, not OCR or game input. The contracts below describe the reviewed implementation and integration limits; the retained priorities snapshot is history, not a second current status.

## Feature Contents

- [Selection and priority](#selection-and-priority) - defaults, readiness gates, resource waits, and the army-manager integration boundary.
- [Lifecycle and isolation](#lifecycle-and-isolation) - confirmed transitions, pauses, expiry, profile identity, and atomic persistence.
- [Historical priorities snapshot](#purpose) - preserved original anchors and decisions.

## Selection and Priority

### Purpose and Current Behavior

`get_next_task` selects the best eligible pending task from one profile queue without preempting active work. It returns a copy and mutates resource-wait bookkeeping, but does not start a task, reserve resources, read the screen, or send input. Army training is the current game-integration scope; building upgrades and academy research remain queue data types, not implemented game flows.

### Inputs and Defaults

- Caller supplies a validated queue, nonnegative integer resource amounts, and timezone-aware `now` (default current UTC). Missing named resources count as zero. Supported types are `army_training`, `building_upgrade`, `academy_research`.
- Priority is integer 1-5, with 1 highest. Task override wins over `settings.task_type_priorities`, then built-in army 1 / other types 3. Missing legacy priority fields use these defaults. Bools, non-integers, out-of-range values and unknown configured types are rejected.
- Resource retry defaults to 2700 s; parallel-wait threshold to 60 s. Generic tasks default to no resource requirements and `quick_finish=false`. Stock goals additionally require persisted process state `needs_preflight` and a decision-valid-until timestamp.

### Algorithm and Outputs

1. Validate queue; paused queues return `None`. Otherwise validate supplied resource amounts, gather active tasks, and stably sort pending `queued`/`waiting_resources` by effective priority then parsed creation time. Equal keys preserve list order.
2. Skip stock goals unless their process is `needs_preflight` and `now < decision_valid_until`. Missing/stale authorization does not complete or delete them. Skip candidates before `next_check_at`.
3. Skip when any task of the same type is active. Cross-type work is eligible only when every active task is `waiting_completion` with a known stored remaining time strictly greater than the threshold. The pure `task_parallelism_blocker` owns this rule for scheduler selection, confirmed-start persistence and army execution. It returns `same_type_active` first, otherwise `parallel_wait_not_ready`, or `None`. No preemption occurs.
4. Insufficient resources set `waiting_resources` and `next_check_at = now + resource_retry_seconds`, then continue to lower-priority candidates. A not-ready high-priority task does not block a lower ready one.
5. First eligible task is normalized to `queued`, its next check cleared, and a deep copy returned. No eligible task returns `None`; caller persists mutations explicitly.
6. The army manager has a separate execution selection path: housekeeping, startup, first due fallback in list order, otherwise frame evaluation of due pending stock goals and priority/creation sorting of `needs_preflight` or `selection_unverified` reports. Automatic execution respects `next_check_at` before category selection and reconciliation: a future-dated goal is reported as deferred, without reading its slot, updating its process or clearing its retry time. At the exact deadline it becomes due. Other ready goals may proceed, but a pinned E2E goal is never replaced. Manual `run --image` retains explicit early observation; only `--save` persists its reconciliation. The executor separately enforces pause/pending/active-type/parallelism and live preflight gates.

### Safety and Limitations

- Hold/resume archive containers (`army_training_hold_history`, per-task `resource_retry_history`) must be lists when present. Validate them before resume mutates pending tasks, so malformed persisted archive data fails without partially resetting retry budgets or clearing the hold. Legacy queues without archive fields remain valid.
- Implemented 2026-11-11: global `paused` blocks every automatic action dispatched by the army manager, including navigation, test-only finishing and fallback finishing. The manager returns `BLOCKED_PAUSED_QUEUE` before navigation/expiry bookkeeping; direct `execute_finish_task(execute=True)` also returns that status before marker reads, task mutation or capture. Reports retain `pause_reason`; preview remains available. This does not change the narrower silver `army_training_hold`, which permits existing-training completion. Queue loading may retain its existing legacy migration behavior; no cross-file transaction is promised.
- Implemented revision 2026-11-11: confirmed silver-only preflight failures use a per-task `resource_retry` budget of three total attempts (optional positive `max_attempts` in that task's retry record). Attempts one/two set `waiting_resources` and the configured retry deadline, default 2700 seconds. Attempt three retains the task and creates a profile-scoped `army_training_hold` with reason/time/source task. This blocks new army starts only, including other army goals; other task types and `finish_training_v1` fallback completion remain unaffected. Waiting, manual reads, uncertainty and unrelated blockers do not count. No smaller-than-half-limit heuristic or cancellation is introduced.
- Explicit `resume-army --confirm "RESUME ARMY TRAINING"` clears only this hold, archives retry history in `resource_retry_history`, resets retry counts for pending training tasks, invalidates their launch decisions and makes them eligible for fresh observation. It does not clear a global queue pause, change active/completed tasks, assume resources were added or send game input. Previous attempts and hold/resume events remain in `army_training_hold_history`. Manual reconciliation cannot remove the hold or authorize a new start. Selection, executor and confirmed-start persistence enforce the hold. `list` reports the hold reason, whether a task's start is held, and retry history.
- The hidden-silver recovery extension is initially passive and returns `not_implemented`; this is not proof that hidden inventory is exhausted. The hold reason names both insufficient silver and the actual recovery outcome. Future recovery actions require a separately approved visual workflow and fresh full preflight after any confirmed replenishment. Uncertain silver recovery/read repair is deferred until its actions are supplied; no retry of uncertain resource use is permitted.
- Priority changes candidate order only. A low-priority active task still blocks higher work until the parallel gate allows it; no aging, reservation or starvation protection is implemented. Stored remaining seconds are not decremented automatically from elapsed wall time.
- Generic scheduler checks supplied resource data, not fresh OCR. Live resource sufficiency belongs to the [army preflight contract](army_training_slot_workflow.md#resource-preflight-and-quantity).
- `task_parallelism_blocker` expects validated task data and a caller-filtered list of active tasks (excluding the candidate itself). It does not check pause, pending status, resource availability, decision freshness or retry timing; it does not mutate or start tasks. Each caller retains those checks and its existing error/report behavior. Sharing this rule does not authorize building/research actions or ordinary live Speed Up integration.
- Do not claim generic readiness semantics are fully integrated in the army CLI: automatic execution respects retry deadlines before reconciliation, but does not call the generic resource/decision-expiry loop. Explicit manual reconciliation may still clear a retry time. Due fallback precedence is retained; global pause now blocks manager and direct fallback execution, while new-start parallelism gates are not applied to completion of existing training. Resource retry intervals are unchanged.
- Campaign priority is already accepted by army goal creation; the historical deferred-priority-per-campaign sentence below is stale. No building/research game actions are authorized by scheduling support.

### Status and Verification

Stage 3 is complete for the agreed queue/army contract and offline scope as of 2026-11-11. The queue owns shared parallelism, retry budgets/deadlines, the army resource hold and explicit resume/history. Army manager/executor retain screen observation, stock-goal evaluation, fresh resource preflight and single-order execution. Automatic manager and direct executor respect retry deadlines; global pause blocks manager input and direct fallback execution, while silver hold permits existing-training completion. Manual image observation, fallback precedence and task priority ordering remain intact. No forced replacement of army selection by `get_next_task` was performed: fresh visual eligibility and completion tasks intentionally retain their separate domain path.

Final validation: **303 tests passed** across all `tests/test_army_*.py` plus queue/client-router/E2E tests, with Windows Tesseract temporarily on PATH; adjacent Speed Up live/core/planner/reader tests: **54 passed**. The focused queue/manager/executor/finish/process/lifecycle/E2E set passed **181 tests**. Coverage includes priority and 60/61 boundaries, deadlines before input, no mutation on refusal, three silver failures and hold, explicit resume with history/profile isolation, preserved global pause and active markers, fallback availability, uncertain-read exclusions, malformed archive refusal before mutation, and persisted hold/budget retention on resume write failure. No live input, purchase, replenishment or OCR recovery occurred. The repository-wide suite and heading anchors were not certified.

Legacy queues remain valid without retry/hold fields. The intermediate cancellation proposal was replaced by resumable hold. Detailed earlier test runs are retained as history in the [project refactor log](project_refactor_log.md), not additional current statuses. Full generic/army scheduler replacement, hidden-resource recovery, uncertain-read repair and complete operator wrappers are explicitly not stage 3 completion claims.

### Proposed and Deferred Changes

Aging, preemption, reservations and any future replacement of the separate generic/army selection paths remain separate behavior changes. Hidden-silver recovery and uncertain-read repair await approved visual workflows. Stage 4 owns complete per-module and selected cross-module wrappers. No building/research executors or new live action permissions are introduced.

### Implementation and Tests

- [Queue](../../task_controller.py): `effective_priority`, `_stock_goal_decision_is_current`, `task_parallelism_blocker`, `army_training_start_is_held`, `record_resource_retry_failure`, `resume_army_training`, `get_next_task`, `mark_task_started`.
- [Army manager](../../army_training_manager.py): `_next_pending_goal_unit_type`, `_command_execute`; [process](../../army_training_process.py): `reconcile_training_goal`; [executor](../../army_training_executor.py): execution gates.
- [Queue tests](../../tests/test_task_controller.py): priority/default/FIFO/bypass tests, `test_insufficient_silver_keeps_task_pending_and_other_type_can_run`, `test_training_wait_allows_other_task_only_when_more_than_one_minute_remains`, legacy priorities. [Manager tests](../../tests/test_army_training_manager.py): saved decisions and manager routes; [finish tests](../../tests/test_army_training_finish.py): generic selection at retry boundaries.
- No-argument offline entrypoints: [test_task_queue_module.py](../../tools/test_task_queue_module.py) exercises ready-task selection with an in-memory army hold; [test_army_queue_e2e.py](../../tools/test_army_queue_e2e.py) composes synthetic stock reconciliation and queue dispatch. Wrapper fail-closed/report tests: [test_module_wrappers.py](../../tests/test_module_wrappers.py).

## Lifecycle and Isolation

### Purpose and Current Behavior

Keep one profile's queue, task lifecycle and settings persistent without treating scheduler timeouts as game-completion evidence. The queue module is data/state logic only. Army ownership markers and visual completion are governed by [Start, Help, finish and evidence](army_training_slot_workflow.md#start-help-finish-and-evidence).

### Inputs and Defaults

- Schema version 1 stores profile ID, creation time, pause state/reason, settings and typed tasks. All timestamps used by transitions must be timezone-aware and are normalized to UTC. Validation rejects duplicate/empty task IDs, unknown types/statuses, invalid resource amounts and inconsistent pause/reason.
- Active statuses are `waiting_help_delay`, `waiting_speedup`, `ready_to_accelerate`, `waiting_completion`, `waiting_speedups`; `queued`, `waiting_resources`, `completed` are inactive.
- Defaults: post-order delay 2 s (range 1-3), settle delay 0.2 s, Help window 1800 s. Per-task window overrides queue window/default. Old tasks may omit expiry fields; missing expiry does not time out.
- Default manager profile is `test`. Queue path is `profiles/<normalized-slug>_<10-character-hash>/tasks.json`; campaign/army state use the same profile directory. Labels isolate bot files, not foreground game accounts or resources.

### Algorithm and Outputs

1. Enqueue copies payload/resources and creates a pending task. `mark_task_started` accepts only pending work after same-type and parallel gates, records game-confirmed initial duration, enters `waiting_help_delay`, and sets Help due and expiry at start plus delay plus window.
2. Caller-confirmed Help after due enters `waiting_speedup`; confirmed Speed Up after settle enters `ready_to_accelerate` for quick-finish, otherwise `waiting_completion`. Remaining-time updates are explicit and allowed only in relevant active states. The queue does not click or recognize these transitions itself.
3. `confirm_task_completed` closes only `ready_to_accelerate`/`waiting_completion`. `complete_task` closes pending work for a supplied reason. `expire_tasks` closes any active task at/past non-null expiry with `window_expired`, even while paused; it is an explicit caller operation, not a background timer or automatic part of `get_next_task`.
4. Generic `record_acceleration_unavailable` changes `ready_to_accelerate` to `waiting_speedups` and pauses the profile with `insufficient_speedups:<task>`. `resume_task_queue` returns those tasks to `waiting_speedup`, resets their speedup check to now, and clears pause/reason. It does not observe game state or reconcile uncertain Train/Help effects.
5. Stock-goal process history/decisions are separate from task lifecycle. Satisfaction completes the goal; campaign re-arm reopens only completed goals and retains history. Resume of a stock process invalidates old decisions and requires fresh observation; it is not proof of game completion. Help-window expiry leaves army ownership open until finish confirmation.
6. Load parses JSON and validates against `expected_profile_id` when supplied. Save validates, writes a UTF-8 temporary file in the destination directory, then replaces the target; failures clean up the temporary file and raise. Mutators do not automatically save. Army marker saves are separate, not an atomic transaction with the queue.
7. Manager `list` loads with expected profile, reports missing file as empty, and never saves/migrates. Other load-or-create commands can persist legacy untyped-goal migration while preserving IDs. Remove protects active tasks; clear requires exact `CLEAR ARMY QUEUE`, unpaused queue and no active tasks, preserving settings/profile metadata. No force/unpause side effect is provided by clear.

### Safety and Limitations

- Ordinary failed owned-training finish schedules retry without pausing, unlike generic quick-finish exhaustion and uncertain Train/Help. Do not merge these pause policies or describe expiry as confirmed idle. A paused queue blocks generic selection; it does not prevent every explicit bookkeeping function or every manager branch.
- `load_task_queue(..., expected_profile_id=...)` enforces profile identity only when the caller provides it. `save_task_queue(..., path=...)` accepts an explicit path; callers must preserve the correct profile/path pairing. Filename slug/hash alone is not account authentication.
- Atomic replacement protects one file from partial writes, not concurrent-writer lost updates, multi-file consistency, or game-account mismatch. No locking or cross-profile parallel live execution is established by this persistence API.
- Generic validation checks the queue envelope, not every nested army process invariant; army helpers perform their own typed validation. Legacy priority/expiry compatibility is not blanket compatibility with arbitrary malformed records.
- Manager preview can still run load-helper migration; `queue_modified=false` reports must not be interpreted as a filesystem-wide no-write guarantee for legacy input. Category/identity assumptions are documented in the [army observation contract](army_training_slot_workflow.md#training-observation-and-stock-reconciliation).

### Status and Verification

Implemented: queue schema validation, lifecycle gates, explicit expiry, pause/resume, per-profile paths, expected-profile load checks, atomic single-file persistence and manager maintenance commands. Source-reviewed 2026-11-10 against queue, manager, process, state and finish source; task-controller/manager/finish tests inspected, not executed by this documentation agent. Test assertions cover round-trip persistence, timed Help transitions, generic pause/resume, resource retry, legacy expiry fields, fallback/marker distinction, and guarded list/remove/clear. No fresh test PASS, crash-consistency/concurrent-writer test, or supervised account-isolation result is claimed.

### Proposed and Deferred Changes

Transactional queue/marker updates, concurrent-writer locking, independent game-account identity, generic building/research executors and safe reconciliation tooling remain separate work. No new retry, unpause, deletion or expiry semantics are implemented here.

### Implementation and Tests

- [Queue](../../task_controller.py): `task_queue_path`, `validate_task_queue`, lifecycle mutators, `load_task_queue`, `save_task_queue`.
- [Manager](../../army_training_manager.py): `_load_or_create_queue`, `_command_list`, `_command_remove`, `_command_clear`; [process](../../army_training_process.py): migration/re-arm/resume.
- [Army state](../../army_state.py), [finish](../../army_training_finish.py): separate ownership/expiration handling.
- [Queue tests](../../tests/test_task_controller.py): profile envelope, persistence, Help timing, pause/resume, parallel-start checks. [Finish tests](../../tests/test_army_training_finish.py): expiry/legacy fields/marker/fallback/retry. [Manager tests](../../tests/test_army_training_manager.py): list without mutation, legacy display, remove/clear protection and preservation of settings.

The original sections below are a **historical priorities snapshot**. Existing anchors and decisions are preserved. For current behavior/status use [Selection and priority](#selection-and-priority) and [Lifecycle and isolation](#lifecycle-and-isolation); in particular campaign priority is implemented, and the army CLI does not simply delegate selection to `get_next_task`.

## Purpose
Let the per-profile task queue choose the next task by priority, so future task types (building upgrades, academy research, ...) can coexist with army training without changing the selection code.

## Terms
- **Priority**: integer 1-5, where 1 is the highest.
- **Type default priority**: priority of every task of a `task_type`. Built-in: `army_training` = 1, any other type = 3. A profile can override it in `settings.task_type_priorities`.
- **Effective priority**: the task's own `priority` if set, otherwise the type default.
- **Ready task**: a `queued` or `waiting_resources` task that passes all gates (stock-goal decision validity, `next_check_at`, one active task per type, parallelism threshold, resources).
- **Active task**: a task in an active status. Active tasks are never preempted.

## Agreed Rules
1. Scale is 1-5, 1 = highest.
2. Priority comes from the type default; an optional per-task `priority` overrides it.
3. Candidates are ordered by (effective priority, `created_at`); equal keys keep list order.
4. A higher-priority task that is not ready (resources, expired or missing stock decision, `next_check_at` in the future) does not block lower-priority tasks; the best ready task is returned.
5. Gates are unchanged; priority only changes the order in which candidates are examined.
6. Queues without `priority` or `task_type_priorities` stay valid and use the built-in defaults.
7. Invalid values (outside 1-5, booleans, non-integers, unknown task types in the map) are rejected.

## Selection Algorithm
1. Return nothing if the queue is paused.
2. Take tasks in `queued` or `waiting_resources`.
3. Sort by effective priority, then `created_at`.
4. Walk the list applying the existing gates; return the first task that passes.

## Confirmed vs Assumed
- Confirmed: scale direction, type default plus per-task override, bypass of not-ready higher-priority tasks, FIFO tie-break, no preemption.
- Assumed: global default 3 for unconfigured types; no aging of waiting tasks.

## Known Limitation (Accepted)
A lower-priority task that starts blocks higher-priority ones until it reaches `waiting_completion` with remaining time above `parallel_wait_threshold_seconds`, because of the existing parallelism rule. With a single task type this has no effect. Add a reservation rule if it matters for multiple types.

## Deferred
Aging or starvation protection, preemption of active tasks, reservation for imminent high-priority tasks, priority per campaign.

## Code Status
- `effective_priority`, `_validate_priority`, `settings.task_type_priorities`, task `priority`, `enqueue_task(..., priority=)` and sorted candidate selection in `get_next_task`.
- Army-training goals accept an optional priority (`enqueue_training_goal`, campaign `priority`); without it they use the `army_training` type default.

## Tests
`tests/test_task_controller.py`: later high priority wins, type default vs override, army training default, FIFO tie, blocked high priority bypassed and then first once ready, same-type active task still blocks, invalid values rejected, legacy queue without priority fields.
