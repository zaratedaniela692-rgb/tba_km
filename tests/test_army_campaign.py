from datetime import datetime, timedelta, timezone

import pytest

from army_campaign import Campaign, CampaignError, campaign_path, expand_campaign, load_campaign, resolve_campaign_level, save_campaign
from army_state import army_state_path, load_army_state, resolve_max_level, save_max_level
from army_training_process import Slot, TrainingGoal, enqueue_training_goal, rearm_training_goal, TrainingProcessError
from task_controller import create_task_queue, get_next_task

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def test_expansion_creates_three_goals_for_low_levels_and_four_for_high_levels():
    queue = create_task_queue("p")
    low = expand_campaign(queue, Campaign("fixed", 4), None, NOW)
    high = expand_campaign(queue, Campaign("fixed", 6), None, NOW)

    assert [goal["match_number"] for goal in low] == [1, 2, 3]
    assert [goal["match_number"] for goal in high] == [1, 2, 3, 4]
    assert {goal["action"] for goal in low + high} == {"created"}


def test_policies_resolve_from_max_level_and_reject_out_of_range():
    assert resolve_campaign_level(Campaign("max"), 7) == 7
    assert resolve_campaign_level(Campaign("max_minus_1"), 7) == 6
    assert resolve_campaign_level(Campaign("fixed", 3), 7) == 3
    with pytest.raises(CampaignError):
        resolve_campaign_level(Campaign("max_minus_1"), 1)
    with pytest.raises(CampaignError):
        Campaign("fixed")


def test_repeated_expansion_keeps_open_goals_and_rearms_only_completed_ones():
    queue = create_task_queue("p")
    campaign = Campaign("max_minus_1", priority=2)
    expand_campaign(queue, campaign, 7, NOW)
    done = queue["tasks"][0]
    done["status"] = "completed"
    done["payload"]["process"]["state"] = "satisfied"

    again = expand_campaign(queue, campaign, 7, NOW + timedelta(hours=1))

    assert [goal["action"] for goal in again] == ["rearmed", "kept", "kept", "kept"]
    assert len(queue["tasks"]) == 4
    assert queue["tasks"][0]["status"] == "queued"
    assert queue["tasks"][0]["payload"]["process"]["history"][-1]["reason"] == "rearmed"
    assert {task["priority"] for task in queue["tasks"]} == {2}


def test_rearm_rejects_open_goal():
    queue = create_task_queue("p")
    task = enqueue_training_goal(queue, TrainingGoal("p", Slot(5, 1)), NOW)
    with pytest.raises(TrainingProcessError):
        rearm_training_goal(queue, task["task_id"], NOW)


def test_single_slot_goal_equals_campaign_goal():
    single = create_task_queue("p")
    enqueue_training_goal(single, TrainingGoal("p", Slot(6, 2)), NOW)
    campaign = create_task_queue("p")
    expand_campaign(campaign, Campaign("fixed", 6), None, NOW)

    assert single["tasks"][0]["payload"]["slot"] == campaign["tasks"][1]["payload"]["slot"]
    assert single["tasks"][0]["task_id"] == campaign["tasks"][1]["task_id"]


def test_disabled_campaign_expands_nothing_and_goals_are_not_ready_without_a_decision():
    queue = create_task_queue("p")
    assert expand_campaign(queue, Campaign("max", enabled=False), 7, NOW) == []
    expand_campaign(queue, Campaign("max"), 7, NOW)
    assert get_next_task(queue, {}, now=NOW) is None


def test_campaign_round_trip_in_profile_directory(tmp_path):
    path = campaign_path("p", tmp_path)
    assert load_campaign(path) is None
    save_campaign(Campaign("max_minus_1", priority=2), path)
    assert load_campaign(path) == Campaign("max_minus_1", priority=2)


def test_max_level_fresh_wins_cache_only_within_ttl(tmp_path):
    path = army_state_path("p", tmp_path)
    save_max_level(path, 7, NOW, "test", 90)
    state = load_army_state(path)

    assert resolve_max_level(8, state, NOW).source == "fresh"
    cached = resolve_max_level(None, state, NOW + timedelta(hours=1))
    assert (cached.status, cached.level, cached.source) == ("ok", 7, "cache")
    stale = resolve_max_level(None, state, NOW + timedelta(hours=25))
    assert (stale.status, stale.reason) == ("blocked", "cached_max_level_stale")
    assert resolve_max_level(None, {}, NOW).reason == "max_level_unavailable"
    assert resolve_max_level(12, state, NOW).status == "blocked"
