# Task Manager: Priorities Contract

Status: **implemented** in [task_controller.py](../../task_controller.py); authoritative for task selection order.

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
