---
description: "Use when changing per-profile task queues, scheduling, lifecycle transitions, stock-goal reconciliation, or army campaign integration."
applyTo: "task_controller.py, army_training_process.py, army_training_plan.py, army_campaign.py, tests/test_task_controller.py, docs/game/task_manager.md"
---

# Task Queue

- Treat `docs/game/task_manager.md` as the authority for task selection and priority behavior. Treat the relevant army workflow as the authority for stock-goal behavior.
- Keep queue scheduling and lifecycle state separate from OCR, screen recognition, and game clicks. Do not connect a task type to live execution unless explicitly requested and its own workflow is approved.
- Preserve per-profile state isolation and atomic persistence. Never mix task queues, markers, or observations across profiles.
- The current integration scope is army training. Building-upgrade and academy-research task types may remain data-only; do not implement their game flows without a separate request.
- Update contract tests alongside queue behavior changes, including legacy queue compatibility where applicable.
