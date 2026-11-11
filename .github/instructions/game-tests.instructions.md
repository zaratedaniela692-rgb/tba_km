---
description: "Use when changing or running Total Battle tests, game-flow integration tests, or supervised live automation."
applyTo: "tests/test_army_*.py, tests/test_client_router.py, tests/test_crypt.py, tests/test_profile_identity.py, tests/test_speedup*.py, tests/test_task_controller.py, tests/test_browser_army_training.py, tools/run_*.py, tools/test_*.py, tools/verify.py"
---

# Game Tests and Live Runs

- Prioritize delivering a small usable behavior change over prolonged analysis or expanding fixture matrices. Choose the smallest validation that can catch a consequential regression; do not add near-duplicate screen fixtures for every visual variation.
- For visual UI behavior, prefer a short supervised live-game check only after the user explicitly authorizes that specific run and scope. Follow the workflow's preconditions and stop conditions.
- Keep focused automated tests for pure logic, state transitions, parser behavior, and critical safety gates. Run the narrow relevant tests after a code change; use the full suite for shared behavior, multiple modules, regions/templates, or before a larger milestone.
- For every operator-facing automation module, provide a small no-argument test entrypoint when it has a repeatable workflow worth running outside pytest. Put the selected profile, scenario, target, and mode in clearly named constants near the top of the wrapper; do not make the operator reconstruct a long command or pass runtime flags. Keep the entrypoint focused on that module and have it report its result and evidence location.
- Keep module checks and end-to-end checks distinct. Module entrypoints should default to offline/fixture or read-only validation. Add separate no-argument E2E wrappers only for selected user-important or cross-module flows; configure their exact scenario at the top of the script and state their side effects before execution. Do not create an E2E wrapper for every module or combine unrelated flows into one runner.
- A wrapper that can send game input, mutate a profile/queue, or spend resources must make that scope explicit in its name/output and require the project's live gates. No wrapper may silently escalate from a read-only/module check into a live E2E action; a no-argument interface does not grant live authorization.
- Test wrappers with mocked/fixture cases for defaults, fail-closed gates, one-shot behavior, and reporting. Automated tests must use injected callbacks and must never control the live game.
- Run `tools/verify.py` when screen recognition, regions, or templates change.
- Never retry an uncertain game action to obtain evidence. Take at most one fresh diagnostic capture and preserve the workflow's failure-only screenshot policy.
- Report what was validated and what was not. A live check validates only the observed client, account, window geometry, and game state; do not generalize it into broad reliability evidence.
