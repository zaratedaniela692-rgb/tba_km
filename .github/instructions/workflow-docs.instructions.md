---
description: "Use when editing project rules, workflow contracts, screen cards, or documentation of approved behavior and implementation status."
applyTo: "AGENTS.md, docs/game/**/*.md, docs/screens/**/*.md, README.md"
---

# Workflow Documentation

- Before changing behavior, update the authoritative workflow with the agreed contract, algorithm/diagram when useful, confirmed facts versus assumptions, uncertain/deferred cases, implementation status, and proportionate validation. A clear user request to implement the described behavior is approval for that scope; ask only when a consequential behavior or risk remains unclear.
- Keep one clear current status per workflow. Mark dated decisions and implementation notes as history or as scoped status; do not let an old snapshot look like the current project-wide state.
- When resuming after a pause or another session, re-read the current workflow and relevant files and inspect the existing diff before acting; treat the worktree as the source of truth, not a prior-session summary.
- Update the existing workflow status in place when implementation changes. Do not create per-module progress files or append a second current contract that contradicts an earlier one.
- Keep screen cards focused on visual evidence, recognition, and annotated regions. Link to the authoritative workflow for action behavior and business rules.
- Record user corrections in the relevant screen card's `Wiedza z poprawek` section or `docs/game/mechaniki.md`.
- Keep links relative to the repository and verify their targets. Do not read entire `debug/` or `screenshots/` folders; request specific evidence files.
- Project documentation is written in English unless the user explicitly requests another language.

## Documentation Ownership

- `AGENTS.md` owns global working rules and the area map, not detailed feature contracts.
- `docs/game/mechaniki.md` owns shared game facts. Area workflows own bot behavior, parameters, decisions, limitations, and current implementation status.
- Screen cards own visual evidence and recognition details; link to the owning feature section instead of maintaining another behavior contract.
- For an ordinary behavior question, use documentation first. Inspect code/tests for implementation work, debugging, or a missing, contradictory, or stale claim. Report unresolved facts rather than inventing an answer.

## Feature Contract Format

Use the following headings within the existing area workflow. Do not create a progress document for every Python module. Link migrated features from a short contents list in that workflow; keep the global area map in `AGENTS.md`.

1. **Purpose and current behavior:** describe what the feature does, its scope, and what it does not prove.
2. **Inputs and defaults:** include manual versus automatic sources, defaults, caller responsibilities, and cache use where relevant.
3. **Algorithm and outputs:** summarize decisions and result states without reproducing code.
4. **Safety and limitations:** distinguish confirmed game facts, heuristics, unsupported cases, and failure handling.
5. **Status and verification:** distinguish proposed, approved but not implemented, and implemented behavior; separately state automated-test evidence and live-validation evidence, with the date and scope of the last check.
6. **Proposed and deferred changes:** keep future behavior visibly separate from current functionality; do not infer implementation approval from documentation approval.
7. **Implementation and tests:** link the owning code and focused tests, with relevant symbols/test names when useful.

## Maintenance and Migration

- Update the owning section in the same behavior-change task: record the agreed contract before implementation and the actual status after validation. A no-behavior-change refactor only needs affected references/status refreshed.
- A date or a test file's existence does not prove freshness or success. Explicitly distinguish source inspection, tests actually run with their result, and supervised live validation.
- Consolidate one feature's current contract in place; preserve substantive rules and historical decisions through scoped notes or links. Keep existing heading anchors where practical and check incoming links when moving sections.
- Migrate one bounded feature at a time. Flag conflicting legacy claims instead of silently adopting the newest-looking note. Do not claim that unmigrated areas are fully documented.
- For documentation-only changes, check local links/heading anchors and instruction diagnostics; do not run game actions or the full test suite solely for prose edits. Report validation that could not be performed.
