"""Structured, text-renderable diagnostics for automation workflows."""

import json
from datetime import datetime, timezone


class WorkflowTrace:
    def __init__(self, workflow, run_id=None, profile_id=None, clock=None):
        self.workflow = workflow
        self.run_id = run_id
        self.profile_id = profile_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.events = []

    def record(
        self, step, *, target=None, observation=None, decision=None, action=None,
        verification=None, reason=None, evidence_ref=None,
    ):
        event = {
            "timestamp": self.clock().isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "profile_id": self.profile_id,
            "workflow": self.workflow,
            "step": step,
            "target": target,
            "observation": observation,
            "decision": decision,
            "action": action,
            "verification": verification,
            "reason": reason,
            "evidence_ref": evidence_ref,
        }
        self.events.append(event)
        return event

    def jsonl(self):
        return "".join(json.dumps(event, ensure_ascii=False, default=str) + "\n" for event in self.events)

    def text_lines(self):
        lines = []
        for event in self.events:
            details = {key: value for key, value in event.items() if key != "timestamp" and value is not None}
            rendered = json.dumps(details, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
            lines.append(f"{event['timestamp']} workflow_event: {rendered}")
        return lines