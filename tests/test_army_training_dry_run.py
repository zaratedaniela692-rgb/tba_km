from pathlib import Path

import pytesseract

from army_training_dry_run import _target_candidate_kind, build_dry_run_report


ROOT_DIR = Path(__file__).resolve().parents[1]
SCREENSHOT = ROOT_DIR / "screenshots" / "army_training" / "pelny.png"


def test_target_candidate_classifies_exact_one_below_for_manager_skip():
    reading = {"highest_visible_level": 4, "one_below_visible_level": 3}

    assert _target_candidate_kind(reading, 5) == "target_unavailable_one_level_below"


def test_dry_run_reads_resources_and_blocks_unverified_training(monkeypatch):
    monkeypatch.setattr(
        pytesseract.pytesseract,
        "tesseract_cmd",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )

    report = build_dry_run_report(SCREENSHOT)

    assert report["status"] == "BLOCKED"
    assert report["actions_executed"] is False
    assert report["queue_modified"] is False
    assert report["target"] == {"global_level": 5, "match_number": 1}
    assert report["resources"]["food"]["value"] == 553_000_000
    assert report["resources"]["silver"]["value"] == 624_000_000
    assert report["resources"]["food"]["confidence_ok"] is True
    assert report["resources"]["silver"]["confidence_ok"] is True
    assert report["training"]["status"] == "active"
    assert "trained_unit_count" in report["training"]
    assert report["slot_layout"]["status"] == "ok"
    assert report["slot_layout"]["visible_slot_count"] == 3
    assert report["slot_layout"]["global_highest_visible_level"] == 5
    assert report["slot_layout"]["one_below_visible_level"] == 4
    assert [slot["readings"]["queue_limit"]["value"] for slot in report["slot_layout"]["slots"]] == [31310, 31310, 15655]
    assert [candidate["frame_index"] for candidate in report["target_candidates"]] == [0, 1, 2]
    assert "target_match_number_unverified" in report["blockers"]
    assert "training_cost_unverified" not in report["blockers"]
    assert "training_already_active" in report["blockers"]
    assert "queue_count_conflicts_with_visual_training_state" not in report["blockers"]
    assert report["manager_decision"] == {
        "status": "not_evaluated",
        "reason": "target_match_number_unverified",
    }
    assert report["actions_executed"] is False
    assert report["queue_modified"] is False


def test_dry_run_reports_idle_training_without_active_training_block(monkeypatch):
    monkeypatch.setattr(
        pytesseract.pytesseract,
        "tesseract_cmd",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )
    image_path = ROOT_DIR / "screenshots" / "army_training" / "pelny_army_training_empty_queue.png"

    report = build_dry_run_report(image_path)

    assert report["training"]["status"] == "idle"
    assert "training_already_active" not in report["blockers"]
    assert report["slot_layout"]["global_highest_visible_level"] == 7
    assert report["target_candidates"] == []
    assert "target_level_not_confirmed_in_visible_slots" in report["blockers"]
    assert report["manager_decision"]["status"] == "not_evaluated"
    start_step = next(step for step in report["planned_steps"] if step["action"] == "start_training")
    assert "aktywne szkolenie blokuje start" not in start_step["reason"]