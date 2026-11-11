---
description: "Use when changing Total Battle screen recognition, OCR, regions, templates, game automation flows, or visual client support."
applyTo: "army_*.py, automate.py, client_router.py, profile_identity.py, crypt.py, mines.py, watchtower_mines.py, speedup*.py, regions.json, templates/**, screenshots/**, tests/test_army_*.py, tests/test_client_router.py, tests/test_crypt.py, tests/test_speedup*.py, tests/test_mines*.py, docs/screens/**"
---

# Game Automation

- Treat the matching workflow in `docs/game/` as the behavior contract. Do not copy its detailed rules into this instruction.
- Do not guess coordinates from screenshots. Use verified `regions.json` entries and templates; request annotation when required data is missing. Coordinates must use the documented capture coordinate system.
- Use template matching for stable visual symbols and OCR for changing text/numbers. Prepare and validate OCR inputs; uncertain readings must remain uncertain, never be treated as zero or as permission to act.
- Detect list completion from an observed unchanged view, not a fixed number of scrolls.
- Model each game flow with recognized state, action, expected next state, timeout, and failure handling. Keep dry-run and emergency-stop behavior for flows that can send input.
- Log significant decisions/actions with timestamps. Save screenshots only under the repository evidence policy: on recognition/action/postcondition failure or exception, except explicit calibration/annotation outputs.
- Use the user's approved client assets only. Browser support is not implemented; never reuse desktop coordinates or templates for browser UI.
- The current capture path may use the primary monitor rather than a selected game window. Confirm the workflow's capture assumptions; do not claim window-relative coordinates are implemented without evidence.

Run project commands from the repository root. Check a script's `--help` before invoking it. Common checks:

```powershell
python -m pytest -q .\tests\test_army_training_slots.py .\tests\test_army_training_executor.py
python -m pytest -q .\tests\test_speedup*.py
python .\tools\verify.py --screen world_map --input .\tests\data\world_map
```
