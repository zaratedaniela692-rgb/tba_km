"""Typed stock-goal decisions and explicit process state for army training."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from math import isfinite

from army_training_plan import MATCH_COUNTS_BY_LEVEL, evaluate_slot_replenishment
from task_controller import ACTIVE_STATUSES, enqueue_task, validate_task_queue


class TrainingProcessError(ValueError):
    """Invalid process input or unsafe transition."""


class ProcessState(StrEnum):
    NEEDS_OBSERVATION = "needs_observation"
    BLOCKED = "blocked"
    NEEDS_PREFLIGHT = "needs_preflight"
    WAITING_TRAINING = "waiting_training"
    RECONCILE = "reconcile"
    SATISFIED = "satisfied"


@dataclass(frozen=True)
class Slot:
    global_level: int
    match_number: int

    def __post_init__(self) -> None:
        if type(self.global_level) is not int or self.global_level not in MATCH_COUNTS_BY_LEVEL:
            raise TrainingProcessError("Invalid global level.")
        if type(self.match_number) is not int or not 1 <= self.match_number <= MATCH_COUNTS_BY_LEVEL[self.global_level]:
            raise TrainingProcessError("Invalid matching slot number.")


@dataclass(frozen=True)
class TrainingGoal:
    profile_id: str
    slot: Slot

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise TrainingProcessError("A goal must belong to a profile.")


@dataclass(frozen=True)
class NumericReading:
    value: int | None
    confidence: float | None
    raw: str = ""

    def reliable(self, minimum_confidence: float) -> bool:
        return (
            type(self.value) is int
            and self.value >= 0
            and type(self.confidence) in (int, float)
            and isfinite(self.confidence)
            and minimum_confidence <= self.confidence <= 100
        )


@dataclass(frozen=True)
class SlotObservation:
    profile_id: str
    slot: Slot
    observed_at: datetime
    source: str
    training_status: str
    highest_unlocked_level: NumericReading
    city_count: NumericReading
    queue_limits: dict[int, NumericReading]
    selection_verified: bool


@dataclass(frozen=True)
class TrainingDecision:
    state: ProcessState
    reason: str
    target_count: int | None = None
    threshold_count: int | None = None
    training_count: int = 0


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TrainingProcessError("A timezone-aware timestamp is required.")
    return value.astimezone(timezone.utc)


def decide_training_goal(
    goal: TrainingGoal,
    observation: SlotObservation,
    now: datetime,
    max_age_seconds: float = 30,
    minimum_confidence: float = 70,
) -> TrainingDecision:
    """Decide from supplied evidence only; never click or mutate a queue."""
    if type(max_age_seconds) not in (int, float) or not isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise TrainingProcessError("Observation lifetime must be positive and finite.")
    if type(minimum_confidence) not in (int, float) or not isfinite(minimum_confidence) or not 0 <= minimum_confidence <= 100:
        raise TrainingProcessError("Confidence threshold must be between 0 and 100.")
    current_time = _utc(now)
    captured_at = _utc(observation.observed_at)
    if goal.profile_id != observation.profile_id:
        return TrainingDecision(ProcessState.BLOCKED, "profile_mismatch")
    if goal.slot != observation.slot:
        return TrainingDecision(ProcessState.BLOCKED, "slot_mismatch")
    if not observation.source:
        return TrainingDecision(ProcessState.BLOCKED, "missing_source")
    if not timedelta(0) <= current_time - captured_at <= timedelta(seconds=max_age_seconds):
        return TrainingDecision(ProcessState.BLOCKED, "stale_or_future_observation")
    if observation.training_status == "active":
        return TrainingDecision(ProcessState.WAITING_TRAINING, "training_active")
    if observation.training_status != "idle":
        return TrainingDecision(ProcessState.BLOCKED, "training_state_unknown")
    highest = observation.highest_unlocked_level
    if not highest.reliable(minimum_confidence):
        return TrainingDecision(ProcessState.BLOCKED, "highest_level_uncertain")
    if highest.value is None or not 1 <= highest.value <= 9:
        return TrainingDecision(ProcessState.BLOCKED, "target_or_reference_level_unavailable")
    if highest.value == goal.slot.global_level - 1:
        return TrainingDecision(ProcessState.SATISFIED, "target_level_unavailable_for_slot")
    if highest.value < goal.slot.global_level:
        return TrainingDecision(ProcessState.BLOCKED, "target_level_unavailable_for_slot")
    if observation.selection_verified is not True:
        return TrainingDecision(ProcessState.BLOCKED, "selection_unverified")
    if highest.value < 2:
        return TrainingDecision(ProcessState.BLOCKED, "target_or_reference_level_unavailable")
    reference = observation.queue_limits.get(highest.value - 1)
    selected = observation.queue_limits.get(goal.slot.global_level)
    if reference is None or not reference.reliable(minimum_confidence) or not reference.value:
        return TrainingDecision(ProcessState.BLOCKED, "reference_limit_uncertain")
    if selected is None or not selected.reliable(minimum_confidence) or not selected.value:
        return TrainingDecision(ProcessState.BLOCKED, "selected_limit_uncertain")
    if not observation.city_count.reliable(minimum_confidence):
        return TrainingDecision(ProcessState.BLOCKED, "city_count_uncertain")
    result = evaluate_slot_replenishment(
        goal.slot.global_level,
        goal.slot.match_number,
        highest.value,
        observation.city_count.value,
        observation.city_count.confidence,
        {highest.value - 1: reference.value, goal.slot.global_level: selected.value},
        goal.slot.global_level,
        minimum_confidence,
    )
    satisfied = result["status"] == "satisfied"
    return TrainingDecision(
        ProcessState.SATISFIED if satisfied else ProcessState.NEEDS_PREFLIGHT,
        "stock_threshold_met" if satisfied else "stock_below_threshold",
        result["target_count"],
        result["completion_count"],
        result["recommended_training_count"],
    )


def enqueue_training_goal(queue: dict, goal: TrainingGoal, now: datetime) -> dict:
    """Materialize one stock goal, not a preselected number of training runs."""
    validate_task_queue(queue, expected_profile_id=goal.profile_id)
    timestamp = _utc(now).isoformat()
    task_id = f"army_stock:level_{goal.slot.global_level}:match_{goal.slot.match_number}"
    existing = next((task for task in queue["tasks"] if task["task_id"] == task_id), None)
    if existing is not None:
        _goal_task(queue, task_id)
        return deepcopy(existing)
    if queue["paused"]:
        raise TrainingProcessError("Cannot enqueue a goal while the profile is paused.")
    task = enqueue_task(
        queue, "army_training", task_id=task_id, now=now,
        payload={
            "goal_kind": "slot_stock_v1",
            "slot": asdict(goal.slot),
            "process": {
                "state": ProcessState.NEEDS_OBSERVATION.value,
                "decision": None,
                "decision_valid_until": None,
                "observation": None,
                "history": [{"at": timestamp, "from": None,
                             "to": ProcessState.NEEDS_OBSERVATION.value,
                             "reason": "goal_created"}],
            },
        },
    )
    return deepcopy(task)


def _goal_task(queue: dict, task_id: str) -> dict:
    validate_task_queue(queue)
    task = next((task for task in queue["tasks"] if task["task_id"] == task_id), None)
    if task is None or task["task_type"] != "army_training":
        raise TrainingProcessError("Army stock goal task not found.")
    if task["payload"].get("goal_kind") != "slot_stock_v1":
        raise TrainingProcessError("This task uses the legacy run-based plan, not a stock goal.")
    process = task["payload"].get("process")
    if (
        not isinstance(process, dict)
        or process.get("state") not in set(ProcessState)
        or not isinstance(process.get("history"), list)
    ):
        raise TrainingProcessError("Invalid persisted training process.")
    slot = task["payload"].get("slot")
    if not isinstance(slot, dict) or set(slot) != {"global_level", "match_number"}:
        raise TrainingProcessError("Invalid persisted slot identity.")
    Slot(**slot)
    return task


def _transition(task: dict, state: ProcessState, reason: str, now: datetime) -> None:
    process = task["payload"]["process"]
    process["history"].append({
        "at": _utc(now).isoformat(), "from": process["state"],
        "to": state.value, "reason": reason,
    })
    process["state"] = state.value


def reconcile_training_goal(
    queue: dict,
    task_id: str,
    observation: SlotObservation,
    now: datetime,
    max_age_seconds: float = 30,
    minimum_confidence: float = 70,
    dry_run: bool = True,
) -> TrainingDecision:
    """Reconcile queued stock against evidence; dry-run leaves the queue unchanged."""
    task = _goal_task(queue, task_id)
    if queue["paused"]:
        raise TrainingProcessError("Profile queue is paused.")
    if task["status"] in ACTIVE_STATUSES:
        raise TrainingProcessError("An active run must be reconciled separately before evaluating its stock goal.")
    goal = TrainingGoal(queue["profile_id"], Slot(**task["payload"]["slot"]))
    decision = decide_training_goal(goal, observation, now, max_age_seconds, minimum_confidence)
    if dry_run:
        return decision
    process = task["payload"]["process"]
    evidence = asdict(observation)
    evidence["observed_at"] = _utc(observation.observed_at).isoformat()
    evidence["queue_limits"] = {str(level): asdict(reading) for level, reading in observation.queue_limits.items()}
    process["observation"] = evidence
    process["decision"] = {**asdict(decision), "state": decision.state.value}
    process["decision_valid_until"] = (
        _utc(observation.observed_at) + timedelta(seconds=max_age_seconds)
    ).isoformat()
    _transition(task, decision.state, decision.reason, now)
    task["status"] = "completed" if decision.state == ProcessState.SATISFIED else "queued"
    task["completed_at"] = _utc(now).isoformat() if task["status"] == "completed" else None
    task["next_check_at"] = None
    validate_task_queue(queue)
    return decision


def resume_training_goal(queue: dict, task_id: str, now: datetime) -> dict:
    """Invalidate old authorization after restart without pretending a run finished."""
    task = _goal_task(queue, task_id)
    _transition(task, ProcessState.RECONCILE, "fresh_observation_required_after_resume", now)
    task["payload"]["process"]["decision"] = None
    task["payload"]["process"]["decision_valid_until"] = None
    validate_task_queue(queue)
    return deepcopy(task)