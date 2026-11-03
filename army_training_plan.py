#!/usr/bin/env python3
"""Per-profile, non-interactive army training order plans."""

import hashlib
import json
import re
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
PROFILES_DIR = ROOT_DIR / "profiles"
PLAN_SCHEMA_VERSION = 2
DEFAULT_CHECK_INTERVAL_SECONDS = 45 * 60
RESET_DELAY_SECONDS = 5
MATCH_COUNTS_BY_LEVEL = {**{level: 3 for level in range(1, 5)}, **{level: 4 for level in range(5, 10)}}
DEFAULT_GUARD_LEVELS = ((5, 1), (4, 2))
DEFAULT_GUARD_MATCH_COUNT = 3
ORDER_STATUSES = {"pending", "active", "completed"}


class TrainingPlanError(ValueError):
    """Raised when a profile training plan is invalid or has an invalid transition."""


def _utc_time(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise TrainingPlanError("Czas musi zawierać strefę czasową.")
    return value.astimezone(timezone.utc)


def _parse_time(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise TrainingPlanError(f"Nieprawidłowy znacznik czasu: {value!r}") from error
    return _utc_time(parsed)


def _profile_slug(profile_id):
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise TrainingPlanError("profile_id musi być niepustym tekstem.")
    normalized = unicodedata.normalize("NFKD", profile_id.strip())
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9_-]+", "_", ascii_name).strip("_-") or "profile"
    digest = hashlib.sha256(profile_id.strip().encode("utf-8")).hexdigest()[:10]
    return f"{slug}_{digest}"


def profile_plan_path(profile_id, profiles_dir=PROFILES_DIR):
    return Path(profiles_dir) / _profile_slug(profile_id) / "army_training.json"


def create_guard_training_plan(profile_id, check_interval_seconds=DEFAULT_CHECK_INTERVAL_SECONDS):
    if isinstance(check_interval_seconds, bool) or not isinstance(check_interval_seconds, int) or check_interval_seconds <= 0:
        raise TrainingPlanError("check_interval_seconds musi być dodatnią liczbą całkowitą.")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise TrainingPlanError("profile_id musi być niepustym tekstem.")

    orders = []
    for match_number in range(1, DEFAULT_GUARD_MATCH_COUNT + 1):
        for global_level, requested_runs in DEFAULT_GUARD_LEVELS:
            orders.append({
                "order_id": f"level_{global_level}_match_{match_number}",
                "global_level": global_level,
                "match_number": match_number,
                "requested_runs": requested_runs,
                "completed_runs": 0,
                "status": "pending",
            })

    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "profile_id": profile_id.strip(),
        "check_interval_seconds": check_interval_seconds,
        "reset_delay_seconds": RESET_DELAY_SECONDS,
        "created_at": _utc_time().isoformat(),
        "active_order_id": None,
        "next_check_at": None,
        "not_before_next_order_at": None,
        "orders": orders,
    }
    validate_plan(plan)
    return plan


def validate_plan(plan, expected_profile_id=None):
    if not isinstance(plan, dict) or plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise TrainingPlanError("Nieobsługiwana lub nieprawidłowa wersja planu.")
    profile_id = plan.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise TrainingPlanError("Plan nie ma poprawnego profile_id.")
    if expected_profile_id is not None and profile_id != expected_profile_id:
        raise TrainingPlanError("Plan należy do innego profilu; odmowa użycia.")

    interval = plan.get("check_interval_seconds")
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        raise TrainingPlanError("Nieprawidłowy check_interval_seconds.")
    reset_delay = plan.get("reset_delay_seconds")
    if isinstance(reset_delay, bool) or not isinstance(reset_delay, int) or reset_delay < 0:
        raise TrainingPlanError("Nieprawidłowy reset_delay_seconds.")

    orders = plan.get("orders")
    if not isinstance(orders, list) or not orders:
        raise TrainingPlanError("Plan musi zawierać co najmniej jedno zlecenie.")
    order_ids = set()
    active_ids = []
    for order in orders:
        if not isinstance(order, dict):
            raise TrainingPlanError("Każde zlecenie musi być obiektem JSON.")
        order_id = order.get("order_id")
        global_level = order.get("global_level")
        match_number = order.get("match_number")
        requested_runs = order.get("requested_runs")
        completed_runs = order.get("completed_runs")
        status = order.get("status")
        if not isinstance(order_id, str) or not order_id or order_id in order_ids:
            raise TrainingPlanError(f"Nieprawidłowe lub powtórzone order_id: {order_id!r}")
        if isinstance(global_level, bool) or not isinstance(global_level, int) or global_level not in MATCH_COUNTS_BY_LEVEL:
            raise TrainingPlanError(f"Nieprawidłowy global_level dla {order_id}.")
        if (
            isinstance(match_number, bool)
            or not isinstance(match_number, int)
            or not 1 <= match_number <= MATCH_COUNTS_BY_LEVEL[global_level]
        ):
            raise TrainingPlanError(f"Nieprawidłowy match_number dla {order_id}.")
        if isinstance(requested_runs, bool) or not isinstance(requested_runs, int) or requested_runs <= 0:
            raise TrainingPlanError(f"Nieprawidłowy requested_runs dla {order_id}.")
        if isinstance(completed_runs, bool) or not isinstance(completed_runs, int) or not 0 <= completed_runs <= requested_runs:
            raise TrainingPlanError(f"Nieprawidłowy completed_runs dla {order_id}.")
        if status not in ORDER_STATUSES:
            raise TrainingPlanError(f"Nieprawidłowy status dla {order_id}.")
        if status == "active":
            active_ids.append(order_id)
        if status == "completed" and completed_runs != requested_runs:
            raise TrainingPlanError(f"Zlecenie {order_id} oznaczono jako completed przed wykonaniem wszystkich powtórzeń.")
        order_ids.add(order_id)

    active_order_id = plan.get("active_order_id")
    if len(active_ids) > 1:
        raise TrainingPlanError("Plan może mieć tylko jedno aktywne szkolenie.")
    if active_ids != ([active_order_id] if active_order_id is not None else []):
        raise TrainingPlanError("active_order_id nie zgadza się ze statusem zleceń.")
    _parse_time(plan.get("created_at"))
    _parse_time(plan.get("next_check_at"))
    _parse_time(plan.get("not_before_next_order_at"))
    return True


def load_plan(path, expected_profile_id=None):
    path = Path(path)
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TrainingPlanError(f"Nie można odczytać planu {path}: {error}") from error
    validate_plan(plan, expected_profile_id)
    return plan


def save_plan(plan, path=None):
    validate_plan(plan)
    path = Path(path) if path is not None else profile_plan_path(plan["profile_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix="army-training-", suffix=".json.tmp", delete=False) as file:
            json.dump(plan, file, ensure_ascii=False, indent=2)
            file.write("\n")
            temp_path = Path(file.name)
        temp_path.replace(path)
    except OSError as error:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise TrainingPlanError(f"Nie można zapisać planu {path}: {error}") from error
    return path


def start_next_order(plan, now=None):
    validate_plan(plan)
    if plan["active_order_id"] is not None:
        return None
    current_time = _utc_time(now)
    not_before = _parse_time(plan.get("not_before_next_order_at"))
    if not_before is not None and current_time < not_before:
        return None

    order = next((item for item in plan["orders"] if item["status"] == "pending"), None)
    if order is None:
        return None
    order["status"] = "active"
    plan["active_order_id"] = order["order_id"]
    plan["next_check_at"] = (current_time + timedelta(seconds=plan["check_interval_seconds"])).isoformat()
    plan["not_before_next_order_at"] = None
    return dict(order)


def get_active_training_target(plan):
    """Return only the single level/slot target for the active training run."""
    validate_plan(plan)
    active_order_id = plan["active_order_id"]
    if active_order_id is None:
        raise TrainingPlanError("Brak aktywnego zlecenia do wykonania.")
    order = next(item for item in plan["orders"] if item["order_id"] == active_order_id)
    return {
        "global_level": order["global_level"],
        "match_number": order["match_number"],
    }


def record_training_check(plan, now=None):
    validate_plan(plan)
    if plan["active_order_id"] is None:
        raise TrainingPlanError("Nie można zaplanować kontroli bez aktywnego zlecenia.")
    current_time = _utc_time(now)
    plan["next_check_at"] = (current_time + timedelta(seconds=plan["check_interval_seconds"])).isoformat()
    return plan["next_check_at"]


def confirm_active_order_run_completed(plan, now=None):
    validate_plan(plan)
    active_order_id = plan["active_order_id"]
    if active_order_id is None:
        raise TrainingPlanError("Brak aktywnego zlecenia do zakończenia.")
    order = next(item for item in plan["orders"] if item["order_id"] == active_order_id)
    order["completed_runs"] += 1
    order["status"] = "completed" if order["completed_runs"] == order["requested_runs"] else "pending"
    plan["active_order_id"] = None
    plan["next_check_at"] = None
    plan["not_before_next_order_at"] = (
        _utc_time(now) + timedelta(seconds=plan["reset_delay_seconds"])
    ).isoformat()
    validate_plan(plan)
    return dict(order)
