import json
from datetime import datetime, timezone

from workflow_trace import WorkflowTrace


def test_workflow_trace_preserves_context_and_renders_machine_and_human_logs():
    trace = WorkflowTrace(
        "army_training_category", run_id="run-1", profile_id="profile-1",
        clock=lambda: datetime(2026, 11, 8, tzinfo=timezone.utc),
    )
    trace.record(
        "category_match", target="specialists", observation={"scores": {"guardsmen": 0.41}},
        decision="block", verification="not_attempted", reason="no_known_category_highlighted",
    )

    event = json.loads(trace.jsonl())
    assert event == trace.events[0]
    assert event["run_id"] == "run-1"
    assert event["profile_id"] == "profile-1"
    assert event["observation"]["scores"]["guardsmen"] == 0.41
    assert event["decision"] == "block"
    assert "no_known_category_highlighted" in trace.text_lines()[0]