# Army Training Implementation Handoff

## Current Source of Truth

The current algorithm, decisions, diagram, implementation status, and MVP boundaries are recorded in [army_training_slot_workflow.md](army_training_slot_workflow.md). Use that document when discussing or changing slot detection and stock-goal behavior. The previous handoff included obsolete pre-implementation findings and is replaced by this current summary.

## Implemented

- `army_training_slots.py` detects all visible slot panels in a screenshot, orders them top-left to bottom-right, and provides translated per-slot crops. It is read-only.
- `army_training_slot_reader.py` reads each slot's queue amount/limit, city count, and silver cost independently, with raw OCR and confidence.
- `army_training_levels.py` chooses the largest selector badge as the presumed highest level, under the agreed assumption that the highest level is selected by default. It OCRs that badge's local Roman numeral and identifies the immediately preceding visible badge as the one-below candidate.
- `army_training_dry_run.py` now reports detected slots, level candidates, and per-slot readings. It stays read-only and blocks rather than assigning a frame index to an unverified persistent `match_number`.
- `army_training_live_e2e.py` implements an isolated one-shot flow for an explicitly supplied visible Guardsmen level in the first slot. It requires a routed desktop profile, detects Barracks before navigation, skips navigation when already open, and otherwise navigates once and verifies a fresh Barracks frame. Live execution requires `--level N --execute --confirm "NAVIGATE IF NEEDED AND TRAIN FIRST SLOT LEVEL N"` and can click Train at most once. A fresh selected-marker/category check is required immediately before Train. No supervised live run has been performed.
- `army_training_inspector.py` recognizes the currently highlighted Guardsmen or Specialists category from selected-state templates and reports visible slots/readings. `tools/run_army_category_inspector_live.py` resolves a desktop profile, detects Barracks first, and navigates only if needed; it never changes category or starts training. Engineers and monster categories remain unsupported.
- `army_training_plan.py` contains pure per-slot stock-goal calculations, including the 80% completion threshold.
- `army_training_process.py` has typed stock-goal, observation, decision, reconciliation, and persistent queue integration. Reconciliation defaults to dry-run. A reliable reading exactly one below a requested target completes that target with reason `target_level_unavailable_for_slot`; no replacement goal is generated.
- Tests cover the detector, per-slot measurements, selector candidates, stock-goal decisions, and queue persistence.

## Not Yet Integrated

- The selector result is a visible-level candidate, not proof that the badge is unlocked. The default-highest assumption is not verified for every account or frame.
- Local I/II cannot be safely mapped to global VIII/IX without list context.
- Frame-local slot indexes are not persistent `{global_level, match_number}` identities.
- No adapter currently assembles slot reads, level evidence, profile, timestamp, training state, and source screenshot into a complete `SlotObservation`.
- The adapter must keep each slot's own queue limit and, by the agreed rule, supply that same limit for both relevant levels of that slot.
- Persistent queue-manager identity and `SlotObservation` integration remain unimplemented. The one-shot live path does primary-monitor capture, explicit-level selector click with marker verification, same-slot re-detection, resource/stock preflight, at most one Train click, and post-click active-state confirmation. Scrolling and Help/Speed Up remain out of scope.

## Latest Validation

- Full test suite: 114 passed after adding the mocked live E2E executor.
- Live E2E executor tests are fully mocked; they do not capture the desktop or send clicks. Failure tests cover capture errors after selector click and uncertain Train-click exceptions with no retry.
- Local live-preview attempt safely returned `BLOCKED: Live capture requires the 'mss' package` with `actions_executed=false` and `queue_modified=false`. Install dependencies before attempting preview on this PC.
- `tools/verify.py --screen army_training --input screenshots/army_training` completed. State-dependent matches below threshold are expected and recorded in the workflow document.
- Pylance reported no errors in the changed selector reader and tests.

## Next Step

Install dependencies via `python -m pip install -r .\requirements-dev.txt` and install Tesseract OCR. Run the preview and review every reported gate before using the exact `--execute --confirm` command from the workflow document. After one successful one-shot experiment, continue with persistent queue-manager identity (`match_number`) and the `SlotObservation` adapter.