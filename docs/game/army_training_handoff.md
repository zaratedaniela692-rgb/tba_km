# Army Training Implementation Handoff

## Current Source of Truth

The current algorithm, decisions, diagram, implementation status, and MVP boundaries are recorded in [army_training_slot_workflow.md](army_training_slot_workflow.md). Use that document when discussing or changing slot detection and stock-goal behavior. The previous handoff included obsolete pre-implementation findings and is replaced by this current summary.

## Implemented

- `army_training_slots.py` detects all visible slot panels in a screenshot, orders them top-left to bottom-right, and provides translated per-slot crops. It is read-only.
- `army_training_slot_reader.py` reads each slot's queue amount/limit, city count, and silver cost independently, with raw OCR and confidence.
- `army_training_levels.py` chooses the largest selector badge as the presumed highest level, under the agreed assumption that the highest level is selected by default. It OCRs that badge's local Roman numeral and identifies the immediately preceding visible badge as the one-below candidate.
- `army_training_dry_run.py` now reports detected slots, level candidates, and per-slot readings. It stays read-only and blocks rather than assigning a frame index to an unverified persistent `match_number`.
- `army_training_plan.py` contains pure per-slot stock-goal calculations, including the 80% completion threshold.
- `army_training_process.py` has typed stock-goal, observation, decision, reconciliation, and persistent queue integration. Reconciliation defaults to dry-run. A reliable reading exactly one below a requested target completes that target with reason `target_level_unavailable_for_slot`; no replacement goal is generated.
- Tests cover the detector, per-slot measurements, selector candidates, stock-goal decisions, and queue persistence.

## Not Yet Integrated

- The selector result is a visible-level candidate, not proof that the badge is unlocked. The default-highest assumption is not verified for every account or frame.
- Local I/II cannot be safely mapped to global VIII/IX without list context.
- Frame-local slot indexes are not persistent `{global_level, match_number}` identities.
- No adapter currently assembles slot reads, level evidence, profile, timestamp, training state, and source screenshot into a complete `SlotObservation`.
- The adapter must keep each slot's own queue limit and, by the agreed rule, supply that same limit for both relevant levels of that slot.
- Food preflight, live-window capture, scrolling, selection clicks, Train clicks, Help, and post-click confirmation remain outside this MVP.

## Latest Validation

- Full test suite: `107 passed` on 2026-11-05 after integrating slot evidence into the CLI dry-run report.
- `tools/verify.py --screen army_training --input screenshots/army_training` completed. State-dependent matches below threshold are expected and recorded in the workflow document.
- Pylance reported no errors in the changed selector reader and tests.

## Next Step

Resolve the first target's persistent `{global_level, match_number}` binding from the intended profile/list position, then create the read-only adapter to `SlotObservation` and call the manager in dry-run. The current fixtures do not prove this binding: `pelny.png` has active training and the idle fixture shows VII/VI rather than the configured V target. Preserve the distinction between visible local-level evidence and a verified global highest-unlocked level. Do not add clicks or scrolling as part of this adapter.