"""Campaign policy that expands into per-slot stock goals; never a queue task itself."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from army_training_plan import MATCH_COUNTS_BY_LEVEL
from army_training_process import (
    Slot,
    TrainingGoal,
    enqueue_training_goal,
    goal_task_id,
    rearm_training_goal,
)
from task_controller import PROFILES_DIR, task_queue_path

POLICY_KINDS = ("max", "max_minus_1", "fixed")


class CampaignError(ValueError):
    """Raised for an invalid campaign or a level the campaign cannot target."""


@dataclass(frozen=True)
class Campaign:
    level_policy: str
    fixed_level: int | None = None
    enabled: bool = True
    priority: int | None = None

    def __post_init__(self):
        if self.level_policy not in POLICY_KINDS:
            raise CampaignError(f"Unknown level policy: {self.level_policy!r}")
        if self.level_policy == "fixed":
            if type(self.fixed_level) is not int or self.fixed_level not in MATCH_COUNTS_BY_LEVEL:
                raise CampaignError("A fixed policy needs a level between 1 and 9.")
        elif self.fixed_level is not None:
            raise CampaignError("fixed_level is only valid for the fixed policy.")
        if type(self.enabled) is not bool:
            raise CampaignError("enabled must be a boolean.")


def campaign_path(profile_id, profiles_dir=PROFILES_DIR):
    return task_queue_path(profile_id, profiles_dir).with_name("army_campaign.json")


def load_campaign(path):
    """Return the stored campaign, or None when the profile has none."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Campaign(**data)
    except (OSError, json.JSONDecodeError, TypeError) as error:
        raise CampaignError(f"Cannot read campaign: {error}") from error


def save_campaign(campaign, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(asdict(campaign), stream, indent=2)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return path


def resolve_campaign_level(campaign, max_level):
    """Global level the campaign targets; raises when it falls outside 1-9."""
    if campaign.level_policy == "fixed":
        return campaign.fixed_level
    level = max_level if campaign.level_policy == "max" else max_level - 1
    if type(level) is not int or level not in MATCH_COUNTS_BY_LEVEL:
        raise CampaignError("campaign_level_out_of_range")
    return level


def expand_goals(queue, level, now: datetime, priority=None):
    """Enqueue goals (level, 1..N); re-arm completed ones. Idempotent for open goals."""
    results = []
    for match_number in range(1, MATCH_COUNTS_BY_LEVEL[level] + 1):
        slot = Slot(level, match_number)
        task_id = goal_task_id(slot)
        existing = next((task for task in queue["tasks"] if task["task_id"] == task_id), None)
        if existing is None:
            enqueue_training_goal(queue, TrainingGoal(queue["profile_id"], slot), now, priority)
            action = "created"
        elif existing["status"] == "completed":
            rearm_training_goal(queue, task_id, now)
            action = "rearmed"
        else:
            action = "kept"
        results.append({"task_id": task_id, "level": level, "match_number": match_number, "action": action})
    return results


def expand_campaign(queue, campaign, max_level, now: datetime):
    if not campaign.enabled:
        return []
    level = resolve_campaign_level(campaign, max_level)
    return expand_goals(queue, level, now, campaign.priority)
