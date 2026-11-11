# AI Agent Workflow: Audit and Improvement Plan

## Purpose

This document reviews repository organization specifically for effective AI-agent work. It complements [Project Refactor Log](game/project_refactor_log.md), which records code/refactor changes and their test results. This document focuses on instructions, source-of-truth routing, test entrypoints, and evidence boundaries.

It is an audit and plan, not a claim that the entire repository has been refactored. “Present in the worktree/history” does not identify which person or conversation created a change. The worktree contains uncommitted changes, so attribution beyond the available repository/session evidence is intentionally avoided.

## Current Model

The project has the intended three information layers:

1. `AGENTS.md` contains shared safety/work rules and an area map.
2. `.github/instructions/*.instructions.md` supplies topic-specific rules through `applyTo` patterns.
3. `docs/game/*_workflow.md` owns area behavior contracts and evidence/status; screen cards own visual evidence.

The model is appropriate for this repository. It keeps global instructions smaller and lets agents load the relevant behavior contract rather than treating every historical note as current. It should be retained, with a few targeted improvements below.

## Most Important Improvements Present

### 1. Explicit sources of truth and area routing

**Present in:** `AGENTS.md`, the workflow-documentation instruction, and area workflow feature contents.

**Why it matters:** agents need a reliable path from a request to the owning contract, implementation, and tests. This reduces broad repository scans and conflicting behavior assumptions.

**Expected effect:** start from the area contract, inspect only its implementation/test slice, then update the same source of truth.

**Evidence/limit:** these files and links are present in the worktree, but not every legacy area has equally complete current-state evidence. A workflow is a contract, not proof that code or tests satisfy it.

### 2. Clear separation of offline tests and live wrappers

**Present in:** `game-tests.instructions.md`, `README.md`, `tools/run_army_navigation_live.py`, and `tools/run_army_e2e.py`.

**Why it matters:** a no-argument runner is convenient, but its name and invocation must not hide clicks, queue mutation, or resource spending.

**Expected effect:** module tests remain fixture/mock based; selected user-important E2E flows have separately named wrappers and documented side effects; live execution still needs run-specific authorization.

**Evidence/limit:** the parameterless army navigation wrapper and tests exist. The full army E2E wrapper is a separate resource-consuming flow. Their existence does not imply a successful live run.

### 3. Failure-only evidence and explicit test results

**Present in:** game automation/test instructions and current workflow statuses.

**Why it matters:** agents should not collect screenshots by repeating uncertain actions, and should not report an inspected test as passing.

**Expected effect:** evidence is saved on relevant failure/uncertainty, tests use mocks or fixtures, and reports state command, result, and unvalidated live boundaries.

**Evidence/limit:** this policy is documented; compliance of every old script and historical status is not fully audited.

### 4. Scoped feature readiness

**Present in:** browser/UI readiness contract and Speed Up browser adapter skeleton.

**Why it matters:** browser fixture code or a shared icon is not proof that an entire browser client is ready. A single future browser feature can be isolated without enabling unrelated actions.

**Expected effect:** feature-specific gates remain independent; browser support is enabled only for the feature with verified assets and callbacks.

**Evidence/limit:** Speed Up browser remains blocked until its own screen/assets and adapter exist. No browser live validation is claimed.

### 5. Documented refactor history

**Present in:** `docs/game/project_refactor_log.md`.

**Why it matters:** users and agents can review why a change was made, its expected outcome, and actual test result without relying on chat memory.

**Expected effect:** decisions and evidence persist across sessions while area workflows remain the current behavior contract.

**Evidence/limit:** the report covers the recent scoped refactor work; it is not a full-project change inventory.

## Recommended Next Improvements

Prioritized by expected benefit to agent accuracy and setup time. These are recommendations, not automatically approved code changes.

### Priority 1: Add a repository inventory and dependency entrypoint

**Current friction:** the README has Python setup and test examples, but it does not summarize module ownership, test naming, optional native tools (especially Tesseract), or which files are safe to import versus operator/live entrypoints.

**Proposed change:** add a concise contributor index (in README or a small `docs/development.md`) listing major areas, authoritative workflow, code, tests, and whether a tool is offline, read-only, or live. Keep the area map in one place; do not duplicate all of `AGENTS.md`.

**Expected effect:** an agent can route a task in one lookup and avoid accidentally importing/running a live script.

**Validation:** verify every linked target exists; compare each row against `AGENTS.md`; do not claim scripts are safe without source/test evidence.

### Priority 2: Make instruction scopes complete and non-overlapping enough

**Current friction:** `applyTo` patterns are hand-maintained. New test files, runners, or feature modules may not receive the intended instructions; overlapping game/test rules can also repeat the same requirement.

**Proposed change:** periodically audit each `applyTo` against the area map and actual file inventory. Add a lightweight offline check that validates frontmatter syntax, local links, and that mapped key paths exist. Keep semantic policy in one owning instruction and refer to it from others.

**Expected effect:** relevant agents receive the safety/test instructions, while prompt context stays smaller and avoids contradictory duplicates.

**Validation:** run the metadata/link checker and inspect representative target files to confirm intended instruction coverage; this checker must not run game code.

### Priority 3: Standardize test runners only where an operator workflow exists

**Current friction:** `pytest` gives automated coverage, while users also need simple no-argument ways to invoke module checks and selected end-to-end flows. Without a consistent convention, test entrypoints are hard to discover and agents may confuse a fixture check with live automation.

**Status:** complete for the agreed offline wrapper scope on 2026-11-11. Four parameterless wrappers cover Speed Up planning, Army screen recognition, queue readiness, and an injected in-memory Army/queue E2E. They are separate from live runners; this does not certify live behavior or imply wrappers for every module/combination. See [Project Refactor Log](game/project_refactor_log.md) for the recorded implementation and validation.

**Expected effect:** scoped checks have predictable entrypoints, and the selected integrated workflow can be tested without runtime arguments. Module tests remain distinct from E2E and from live execution.

**Validation boundary:** wrapper tests cover default configuration, fail-closed gates, one-shot behavior, and reporting. Automated tests inject callbacks and never launch real game input. Any E2E wrapper capable of clicks, queue mutation, or resource spending must disclose those effects and retain run-specific live authorization; a parameterless command is not live authorization.

### Priority 4: Add a single validated development-check command

**Current friction:** commands are scattered among README and area workflows, and a full test run currently has known unrelated collection/failure issues.

**Proposed change:** after command baselines are stable, provide a PowerShell-friendly no-argument offline check script for fast lint/syntax plus selected tests, and keep a separate full-suite command. Do not mask failures with `--continue-on-collection-errors` in the normal gate.

**Expected effect:** contributors and agents can run the same fast gate and distinguish it from full validation.

**Validation:** run it from a clean shell in the selected `.venv`; ensure output identifies each check and fails nonzero on any failed check. Do not include live wrappers.

### Priority 5: Keep chat/session history supplemental

**Current friction:** repository state, current workflow, and previous chat summaries can diverge, especially with a dirty worktree.

**Proposed change:** use Git diff/workflows as the source of truth; treat memory and chat reports as navigation hints only. Continue recording only durable user decisions and scoped work plans in memory.

**Expected effect:** resumed agents re-read current files and do not repeat or misattribute stale work.

**Validation:** at task start, inspect status and diffs for touched files; at handoff, distinguish committed, uncommitted, tested, and live-validated work.

## Daily Project Optimization Review

Run this review once per active workday or at the user's request. It is a review cadence, not an automated background job: the assistant cannot initiate a review while no session is running. Use the repository and available session evidence as inputs; do not treat chat memory as the source of truth.

1. Inspect the current Git status and relevant diffs, then read the owning workflow and the focused test/validation results for changed areas.
2. Review structure and maintainability (ownership boundaries, duplicated rules, stale/conflicting docs), correctness and safety (test results and unvalidated paths), runtime performance (only where a representative measurement exists), and AI-workflow efficiency (context required, repeated searches/reads, tool calls, and rework).
3. Offer up to three improvement proposals. For each, state the evidence, expected benefit, effort/risk, a measurable success criterion, and the smallest validation. Separate confirmed findings from hypotheses. Do not implement proposals until the user selects one; a review is not blanket approval to change behavior or run live actions.
4. Record only durable decisions and meaningful tested changes in the sections below or the owning workflow. Keep routine review notes concise; do not create a new daily file or duplicate feature contracts here.

Suggested daily-review request: “Review today's project changes for maintainability, correctness, runtime performance, and AI context/token efficiency. Use repository and available session evidence, propose up to three measurable improvements, and do not change code or run live actions.”

## Measurement and Change Record

Use a small before/after experiment for an optimization claim. State a falsifiable hypothesis, capture a baseline with the same command/environment where practical, make one bounded change, run the focused validation, and record the result as improved, unchanged, regressed, or not measured. Do not infer a performance improvement from cleaner code or passing tests alone. If the result is inconclusive, keep that status rather than turning the expected effect into a claim.

Track measures that fit the change:

- **Correctness and safety:** focused test command and pass/fail count; relevant failure cases; live evidence separately marked as not run, blocked, or supervised and passed.
- **Runtime or resource use:** representative command, input/fixture, environment, duration or resource measure, baseline, and after value. Compare like with like; profile only when there is a concrete performance question.
- **Maintainability and agility:** affected ownership boundaries, duplicated logic removed/introduced, number of workflows or modules that must change for a typical follow-up, and any newly surfaced coupling. Treat these as review findings, not fabricated numeric scores.
- **AI context and interaction cost:** record exact token/context usage only when the interface exposes it. Otherwise mark exact usage unavailable and use explicit proxies such as files inspected before the first edit, repeated reads/searches, tool-call rounds, and repair iterations. These proxies help find waste but are not token counts or quality scores.
- **Change scope:** link the diff/commit when available and name tests actually run; distinguish uncommitted work, historic baselines, and current evidence.

Use this compact entry for a meaningful optimization experiment:

| Date / area | Baseline and evidence | Hypothesis and change | Expected measure | Actual result / validation | Decision |
| --- | --- | --- | --- | --- | --- |
| YYYY-MM-DD / area | command, result, or unavailable | one bounded change | metric and expected direction | measured result, test command and outcome | keep, revise, revert, or defer |

Do not log secrets, credentials, or raw game screenshots in this record. Link to approved repository evidence instead. Exact AI token accounting may be unavailable; never estimate it as fact from the apparent length of a conversation.

## Evidence from Other Sessions

Within the available repository and conversation context, these organizational changes are visible:

- `AGENTS.md` was condensed into shared rules, safety boundaries, and an area-to-workflow/code/test map.
- Topic instructions were added for game automation, game tests, task queue, and workflow documentation, with `applyTo` patterns.
- Workflow documents gained feature-level contracts and separated current status from historical notes.
- README gained developer setup, focused/full pytest examples, source-of-truth navigation, and explicit warnings for live wrappers.
- A parameterless, navigation-only army live wrapper was added with mocked safety tests, distinct from the resource-consuming army E2E.
- The Speed Up web-only adapter skeleton was separated from global browser readiness.

These are confirmed as present in the accessible worktree/history, but their exact origin in a specific earlier chat/session cannot be reliably established from Git status alone. Some files remain untracked or modified. See [Project Refactor Log](game/project_refactor_log.md) for runtime refactors and their validation; this document does not reattribute those code changes.

## Overall Assessment

The three-layer information model is sound and already materially better for AI collaboration than a flat set of stale instructions. The agreed offline test-runner stage is complete; it does not certify live behavior. Remaining organizational opportunities are discoverability, consistent instruction coverage, a repeatable offline validation command, and using the daily review to select evidence-backed improvements. Avoid a broad code rewrite for “AI optimization”; optimize how agents find the correct contract, inspect the smallest code/test slice, and prove changes without touching live game state.
