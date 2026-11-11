"""Structured, text-renderable diagnostics for automation workflows."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

_CHECKPOINT_NUMBER = 0


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


def record_live_checkpoint(
    step, *, profile_id=None, decision=None, action=None, observation=None,
    verification=None, reason=None, frame=None, monitor_origin=None,
):
    """Always log an event; save its frame only for blocked or uncertain outcomes."""
    global _CHECKPOINT_NUMBER

    run_dir_value = os.environ.get("TBA_RUN_DIR")
    run_dir = Path(run_dir_value) if run_dir_value else None
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "run_id": run_dir.name if run_dir else None,
        "profile_id": profile_id or os.environ.get("TBA_PROFILE_ID"),
        "workflow": "army_training_live",
        "step": step,
        "decision": decision,
        "action": action,
        "observation": observation,
        "verification": verification,
        "reason": reason,
        "evidence_ref": None,
    }
    if monitor_origin is not None:
        event["monitor_origin"] = list(monitor_origin)

    failed_verifications = {"failed", "unknown", "not_confirmed", "unconfirmed", "mismatch"}
    needs_evidence = (
        decision in {"blocked", "uncertain", "error", "stop"}
        or verification in failed_verifications
    )
    if frame is not None and run_dir is not None and needs_evidence:
        _CHECKPOINT_NUMBER += 1
        safe_step = re.sub(r"[^a-zA-Z0-9_-]+", "_", step).strip("_") or "checkpoint"
        image_name = f"checkpoint_{_CHECKPOINT_NUMBER:02d}_{safe_step}.png"
        try:
            import cv2

            image_path = run_dir / image_name
            if not cv2.imwrite(str(image_path), frame):
                raise OSError("image_write_failed")
            event["evidence_ref"] = image_name
            event["frame_size"] = [int(frame.shape[1]), int(frame.shape[0])]
        except Exception as error:
            event["evidence_error"] = f"{type(error).__name__}: {error}"

    trace_path_value = os.environ.get("TBA_WORKFLOW_TRACE_PATH")
    trace_path = Path(trace_path_value) if trace_path_value else (run_dir / "workflow_trace.jsonl" if run_dir else None)
    if trace_path is not None:
        try:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            with trace_path.open("a", encoding="utf-8") as trace_file:
                trace_file.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except OSError as error:
            event["trace_error"] = f"{type(error).__name__}: {error}"
    return event