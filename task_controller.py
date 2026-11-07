#!/usr/bin/env python3
"""Persistent per-profile queue for typed game tasks."""

import hashlib
import json
import re
import tempfile
import unicodedata
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


ROOT_DIR = Path(__file__).resolve().parent
PROFILES_DIR = ROOT_DIR / "profiles"
TASK_QUEUE_SCHEMA_VERSION = 1
TASK_TYPES = {"army_training", "building_upgrade", "academy_research"}
TASK_STATUSES = {
    "queued",
    "waiting_resources",
    "waiting_help_delay",
    "waiting_speedup",
    "ready_to_accelerate",
    "waiting_completion",
    "waiting_speedups",
    "completed",
}
ACTIVE_STATUSES = TASK_STATUSES - {"queued", "waiting_resources", "completed"}
DEFAULT_RESOURCE_RETRY_SECONDS = 45 * 60
DEFAULT_POST_ORDER_DELAY_SECONDS = 2.0
DEFAULT_HELP_TO_SPEEDUP_DELAY_SECONDS = 0.2
DEFAULT_PARALLEL_WAIT_THRESHOLD_SECONDS = 60


class TaskQueueError(ValueError):
    """Raised when a task queue is invalid or a task transition is unsafe."""


def _utc_time(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise TaskQueueError("Czas musi zawierać strefę czasową.")
    return value.astimezone(timezone.utc)


def _parse_time(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise TaskQueueError(f"Nieprawidłowy znacznik czasu: {value!r}") from error
    return _utc_time(parsed)


def _profile_slug(profile_id):
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise TaskQueueError("profile_id musi być niepustym tekstem.")
    normalized = unicodedata.normalize("NFKD", profile_id.strip())
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9_-]+", "_", ascii_name).strip("_-") or "profile"
    digest = hashlib.sha256(profile_id.strip().encode("utf-8")).hexdigest()[:10]
    return f"{slug}_{digest}"


def task_queue_path(profile_id, profiles_dir=PROFILES_DIR):
    return Path(profiles_dir) / _profile_slug(profile_id) / "tasks.json"


def create_task_queue(
    profile_id,
    resource_retry_seconds=DEFAULT_RESOURCE_RETRY_SECONDS,
    post_order_delay_seconds=DEFAULT_POST_ORDER_DELAY_SECONDS,
    help_to_speedup_delay_seconds=DEFAULT_HELP_TO_SPEEDUP_DELAY_SECONDS,
    parallel_wait_threshold_seconds=DEFAULT_PARALLEL_WAIT_THRESHOLD_SECONDS,
):
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise TaskQueueError("profile_id musi być niepustym tekstem.")
    settings = {
        "resource_retry_seconds": resource_retry_seconds,
        "post_order_delay_seconds": post_order_delay_seconds,
        "help_to_speedup_delay_seconds": help_to_speedup_delay_seconds,
        "parallel_wait_threshold_seconds": parallel_wait_threshold_seconds,
    }
    _validate_settings(settings)
    queue = {
        "schema_version": TASK_QUEUE_SCHEMA_VERSION,
        "profile_id": profile_id.strip(),
        "created_at": _utc_time().isoformat(),
        "paused": False,
        "pause_reason": None,
        "settings": settings,
        "tasks": [],
    }
    validate_task_queue(queue)
    return queue


def _validate_settings(settings):
    if not isinstance(settings, dict):
        raise TaskQueueError("settings musi być obiektem JSON.")
    for key in ("resource_retry_seconds", "parallel_wait_threshold_seconds"):
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TaskQueueError(f"{key} musi być nieujemną liczbą całkowitą.")
    for key in ("post_order_delay_seconds", "help_to_speedup_delay_seconds"):
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise TaskQueueError(f"{key} musi być nieujemną liczbą.")
    if not 1 <= settings["post_order_delay_seconds"] <= 3:
        raise TaskQueueError("post_order_delay_seconds musi należeć do zakresu 1-3.")


def validate_task_queue(queue, expected_profile_id=None):
    if not isinstance(queue, dict) or queue.get("schema_version") != TASK_QUEUE_SCHEMA_VERSION:
        raise TaskQueueError("Nieobsługiwana lub nieprawidłowa wersja kolejki.")
    profile_id = queue.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise TaskQueueError("Kolejka nie ma poprawnego profile_id.")
    if expected_profile_id is not None and profile_id != expected_profile_id:
        raise TaskQueueError("Kolejka należy do innego profilu; odmowa użycia.")
    if not isinstance(queue.get("paused"), bool):
        raise TaskQueueError("paused musi być wartością logiczną.")
    if queue["paused"] != bool(queue.get("pause_reason")):
        raise TaskQueueError("paused i pause_reason muszą być ze sobą zgodne.")
    _validate_settings(queue.get("settings"))
    _parse_time(queue.get("created_at"))

    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        raise TaskQueueError("tasks musi być listą.")
    task_ids = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise TaskQueueError("Każde zadanie musi być obiektem JSON.")
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in task_ids:
            raise TaskQueueError(f"Nieprawidłowy lub powtórzony task_id: {task_id!r}")
        if task.get("task_type") not in TASK_TYPES:
            raise TaskQueueError(f"Nieobsługiwany typ zadania: {task.get('task_type')!r}")
        if task.get("status") not in TASK_STATUSES:
            raise TaskQueueError(f"Nieprawidłowy status zadania {task_id}.")
        if not isinstance(task.get("payload"), dict):
            raise TaskQueueError(f"payload zadania {task_id} musi być obiektem.")
        resources = task.get("required_resources")
        if not isinstance(resources, dict):
            raise TaskQueueError(f"required_resources zadania {task_id} musi być obiektem.")
        for resource, amount in resources.items():
            if not isinstance(resource, str) or not resource:
                raise TaskQueueError(f"Nieprawidłowa nazwa zasobu w zadaniu {task_id}.")
            if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
                raise TaskQueueError(f"Nieprawidłowa ilość zasobu w zadaniu {task_id}.")
        if not isinstance(task.get("quick_finish"), bool):
            raise TaskQueueError(f"quick_finish zadania {task_id} musi być wartością logiczną.")
        for key in ("created_at", "next_check_at", "started_at", "help_due_at", "help_requested_at",
                    "speedup_check_at", "speedup_available_at", "completed_at"):
            _parse_time(task.get(key))
        for key in ("initial_remaining_seconds", "last_remaining_seconds"):
            value = task.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise TaskQueueError(f"{key} zadania {task_id} musi być nieujemną liczbą całkowitą.")
        task_ids.add(task_id)
    return True


def _find_task(queue, task_id):
    task = next((item for item in queue["tasks"] if item["task_id"] == task_id), None)
    if task is None:
        raise TaskQueueError(f"Nie znaleziono zadania {task_id!r}.")
    return task


def enqueue_task(queue, task_type, payload=None, required_resources=None, quick_finish=False, task_id=None, now=None):
    validate_task_queue(queue)
    if task_type not in TASK_TYPES:
        raise TaskQueueError(f"Nieobsługiwany typ zadania: {task_type!r}")
    if payload is not None and not isinstance(payload, dict):
        raise TaskQueueError("payload musi być obiektem JSON.")
    if not isinstance(quick_finish, bool):
        raise TaskQueueError("quick_finish musi być wartością logiczną.")
    resources = {} if required_resources is None else required_resources
    if not isinstance(resources, dict):
        raise TaskQueueError("required_resources musi być obiektem JSON.")
    for name, amount in resources.items():
        if not isinstance(name, str) or not name or isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise TaskQueueError("Wymagane zasoby muszą mieć niepuste nazwy i nieujemne liczby całkowite.")
    task_id = task_id or str(uuid4())
    if any(task["task_id"] == task_id for task in queue["tasks"]):
        raise TaskQueueError(f"Zadanie {task_id!r} już istnieje.")
    task = {
        "task_id": task_id,
        "task_type": task_type,
        "payload": deepcopy(payload or {}),
        "required_resources": dict(resources),
        "quick_finish": quick_finish,
        "status": "queued",
        "created_at": _utc_time(now).isoformat(),
        "next_check_at": None,
        "started_at": None,
        "initial_remaining_seconds": None,
        "last_remaining_seconds": None,
        "help_due_at": None,
        "help_requested_at": None,
        "speedup_check_at": None,
        "speedup_available_at": None,
        "completed_at": None,
    }
    queue["tasks"].append(task)
    validate_task_queue(queue)
    return task


def get_next_task(queue, available_resources, now=None):
    """Return the next eligible task; defer resource-blocked tasks without dropping them."""
    validate_task_queue(queue)
    if queue["paused"]:
        return None
    if not isinstance(available_resources, dict):
        raise TaskQueueError("available_resources musi być obiektem JSON.")
    for name, amount in available_resources.items():
        if not isinstance(name, str) or isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise TaskQueueError("Dostępne zasoby muszą mieć nieujemne liczby całkowite.")

    current_time = _utc_time(now)
    active_tasks = [task for task in queue["tasks"] if task["status"] in ACTIVE_STATUSES]
    for task in queue["tasks"]:
        if task["status"] not in {"queued", "waiting_resources"}:
            continue
        if task["payload"].get("goal_kind") == "slot_stock_v1":
            process = task["payload"].get("process", {})
            valid_until = _parse_time(process.get("decision_valid_until"))
            if (
                process.get("state") != "needs_preflight"
                or valid_until is None
                or current_time >= valid_until
            ):
                continue
        next_check = _parse_time(task.get("next_check_at"))
        if next_check is not None and current_time < next_check:
            continue
        if any(active["task_type"] == task["task_type"] for active in active_tasks):
            continue
        if active_tasks and any(
            active["status"] != "waiting_completion"
            or active.get("last_remaining_seconds") is None
            or active["last_remaining_seconds"] <= queue["settings"]["parallel_wait_threshold_seconds"]
            for active in active_tasks
        ):
            continue

        if any(available_resources.get(name, 0) < amount for name, amount in task["required_resources"].items()):
            task["status"] = "waiting_resources"
            task["next_check_at"] = (
                current_time + timedelta(seconds=queue["settings"]["resource_retry_seconds"])
            ).isoformat()
            continue

        task["status"] = "queued"
        task["next_check_at"] = None
        return deepcopy(task)
    validate_task_queue(queue)
    return None


def mark_task_started(queue, task_id, initial_remaining_seconds, now=None):
    """Record game-confirmed task start and schedule the Help click delay."""
    validate_task_queue(queue)
    task = _find_task(queue, task_id)
    if task["status"] not in {"queued", "waiting_resources"}:
        raise TaskQueueError("Zadanie można uruchomić tylko ze stanu queued lub waiting_resources.")
    active_tasks = [
        other for other in queue["tasks"]
        if other["task_id"] != task_id and other["status"] in ACTIVE_STATUSES
    ]
    if any(other["task_type"] == task["task_type"] for other in active_tasks):
        raise TaskQueueError("Nie można uruchomić drugiego aktywnego zadania tego samego typu.")
    if active_tasks and any(
        other["status"] != "waiting_completion"
        or other.get("last_remaining_seconds") is None
        or other["last_remaining_seconds"] <= queue["settings"]["parallel_wait_threshold_seconds"]
        for other in active_tasks
    ):
        raise TaskQueueError("Inne zadanie może ruszyć dopiero, gdy aktywne zadania czekają ponad próg równoległości.")
    if isinstance(initial_remaining_seconds, bool) or not isinstance(initial_remaining_seconds, int) or initial_remaining_seconds < 0:
        raise TaskQueueError("initial_remaining_seconds musi być nieujemną liczbą całkowitą.")
    started_at = _utc_time(now)
    task.update({
        "status": "waiting_help_delay",
        "started_at": started_at.isoformat(),
        "initial_remaining_seconds": initial_remaining_seconds,
        "last_remaining_seconds": initial_remaining_seconds,
        "help_due_at": (started_at + timedelta(seconds=queue["settings"]["post_order_delay_seconds"])).isoformat(),
        "next_check_at": None,
    })
    validate_task_queue(queue)
    return deepcopy(task)


def mark_help_requested(queue, task_id, now=None):
    validate_task_queue(queue)
    task = _find_task(queue, task_id)
    current_time = _utc_time(now)
    help_due_at = _parse_time(task.get("help_due_at"))
    if task["status"] != "waiting_help_delay" or help_due_at is None or current_time < help_due_at:
        raise TaskQueueError("Nie można kliknąć Pomoc przed upływem skonfigurowanego opóźnienia.")
    task.update({
        "status": "waiting_speedup",
        "help_requested_at": current_time.isoformat(),
        "speedup_check_at": (
            current_time + timedelta(seconds=queue["settings"]["help_to_speedup_delay_seconds"])
        ).isoformat(),
    })
    validate_task_queue(queue)
    return deepcopy(task)


def mark_speedup_available(queue, task_id, now=None):
    validate_task_queue(queue)
    task = _find_task(queue, task_id)
    current_time = _utc_time(now)
    check_at = _parse_time(task.get("speedup_check_at"))
    if task["status"] != "waiting_speedup" or check_at is None or current_time < check_at:
        raise TaskQueueError("Nie można potwierdzić Przyspiesz przed sprawdzeniem zmiany przycisku.")
    task["status"] = "ready_to_accelerate" if task["quick_finish"] else "waiting_completion"
    task["speedup_available_at"] = current_time.isoformat()
    validate_task_queue(queue)
    return deepcopy(task)


def update_task_remaining_time(queue, task_id, remaining_seconds):
    validate_task_queue(queue)
    task = _find_task(queue, task_id)
    if task["status"] not in {"waiting_speedup", "waiting_completion", "ready_to_accelerate"}:
        raise TaskQueueError("Pozostały czas można aktualizować tylko dla aktywnego zadania.")
    if isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, int) or remaining_seconds < 0:
        raise TaskQueueError("remaining_seconds musi być nieujemną liczbą całkowitą.")
    task["last_remaining_seconds"] = remaining_seconds
    validate_task_queue(queue)
    return remaining_seconds


def confirm_task_completed(queue, task_id, now=None):
    validate_task_queue(queue)
    task = _find_task(queue, task_id)
    if task["status"] not in {"ready_to_accelerate", "waiting_completion"}:
        raise TaskQueueError("Nie można zakończyć zadania bez potwierdzonego stanu końcowego.")
    task["status"] = "completed"
    task["completed_at"] = _utc_time(now).isoformat()
    validate_task_queue(queue)
    return deepcopy(task)


def record_acceleration_unavailable(queue, task_id, now=None):
    validate_task_queue(queue)
    task = _find_task(queue, task_id)
    if task["status"] != "ready_to_accelerate":
        raise TaskQueueError("Brak przyspieszeń można zgłosić tylko dla zadania gotowego do przyspieszenia.")
    task["status"] = "waiting_speedups"
    queue["paused"] = True
    queue["pause_reason"] = f"insufficient_speedups:{task_id}"
    task["last_checked_at"] = _utc_time(now).isoformat()
    validate_task_queue(queue)
    return deepcopy(task)


def resume_task_queue(queue, now=None):
    validate_task_queue(queue)
    if not queue["paused"]:
        return False
    current_time = _utc_time(now)
    for task in queue["tasks"]:
        if task["status"] == "waiting_speedups":
            task["status"] = "waiting_speedup"
            task["speedup_check_at"] = current_time.isoformat()
    queue["paused"] = False
    queue["pause_reason"] = None
    validate_task_queue(queue)
    return True


def load_task_queue(path, expected_profile_id=None):
    path = Path(path)
    try:
        queue = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TaskQueueError(f"Nie można odczytać kolejki {path}: {error}") from error
    validate_task_queue(queue, expected_profile_id)
    return queue


def save_task_queue(queue, path=None):
    validate_task_queue(queue)
    path = Path(path) if path is not None else task_queue_path(queue["profile_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix="task-queue-", suffix=".json.tmp", delete=False) as file:
            json.dump(queue, file, ensure_ascii=False, indent=2)
            file.write("\n")
            temp_path = Path(file.name)
        temp_path.replace(path)
    except OSError as error:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise TaskQueueError(f"Nie można zapisać kolejki {path}: {error}") from error
    return path


def _validate_training_plan_pair(queue, plan):
    from army_training_plan import validate_plan

    validate_task_queue(queue)
    validate_plan(plan, expected_profile_id=queue["profile_id"])


def enqueue_next_training_run(queue, plan, required_resources=None, quick_finish=False, now=None):
    """Materialize one pending campaign run as a queue task without double-counting it."""
    _validate_training_plan_pair(queue, plan)
    if queue["paused"]:
        return None

    existing = [
        task for task in queue["tasks"]
        if task["task_type"] == "army_training"
        and task["status"] != "completed"
        and task["payload"].get("training_order_id")
    ]
    if plan["active_order_id"] is not None:
        matching = [
            task for task in existing
            if task["payload"]["training_order_id"] == plan["active_order_id"]
        ]
        if len(matching) != 1:
            raise TaskQueueError("Aktywne zlecenie planu musi mieć dokładnie jedno odpowiadające zadanie kolejki.")
        return deepcopy(matching[0])
    if existing:
        return deepcopy(existing[0])

    not_before = plan.get("not_before_next_order_at")
    current_time = _utc_time(now)
    if not_before is not None and current_time < datetime.fromisoformat(not_before).astimezone(timezone.utc):
        return None

    order = next((item for item in plan["orders"] if item["status"] == "pending"), None)
    if order is None:
        return None
    run_number = order["completed_runs"] + 1
    task_id = f"army_training:{order['order_id']}:run:{run_number}"
    return enqueue_task(
        queue,
        "army_training",
        payload={
            "training_order_id": order["order_id"],
            "global_level": order["global_level"],
            "match_number": order["match_number"],
            "run_number": run_number,
            "requested_runs": order["requested_runs"],
        },
        required_resources=required_resources,
        quick_finish=quick_finish,
        task_id=task_id,
        now=current_time,
    )


def start_training_task(queue, plan, task_id, initial_remaining_seconds, now=None):
    """Synchronize a game-confirmed training start into the campaign plan."""
    from army_training_plan import validate_plan

    _validate_training_plan_pair(queue, plan)
    task = _find_task(queue, task_id)
    if task["task_type"] != "army_training":
        raise TaskQueueError("Tylko zadanie army_training można powiązać z planerem treningu.")
    order_id = task["payload"].get("training_order_id")
    order = next((item for item in plan["orders"] if item["order_id"] == order_id), None)
    if order is None:
        raise TaskQueueError("Zadanie nie wskazuje zlecenia z planu treningu.")
    expected_run_number = order["completed_runs"] + 1
    if (
        task["payload"].get("run_number") != expected_run_number
        or task["payload"].get("requested_runs") != order["requested_runs"]
        or task["payload"].get("global_level") != order["global_level"]
        or task["payload"].get("match_number") != order["match_number"]
    ):
        raise TaskQueueError("Dane przebiegu kolejki nie zgadzają się z aktualnym celem planu.")
    if plan["active_order_id"] is not None or order["status"] != "pending":
        raise TaskQueueError("Plan treningu nie jest gotowy do rozpoczęcia tego przebiegu.")

    current_time = _utc_time(now)
    started_task = mark_task_started(
        queue,
        task_id,
        initial_remaining_seconds=initial_remaining_seconds,
        now=current_time,
    )
    order["status"] = "active"
    plan["active_order_id"] = order_id
    plan["next_check_at"] = (
        current_time + timedelta(seconds=plan["check_interval_seconds"])
    ).isoformat()
    plan["not_before_next_order_at"] = None
    validate_plan(plan, expected_profile_id=queue["profile_id"])
    return started_task


def complete_training_task(queue, plan, task_id, now=None):
    """Complete a game-confirmed run and update its campaign counter exactly once."""
    from army_training_plan import confirm_active_order_run_completed, validate_plan

    _validate_training_plan_pair(queue, plan)
    task = _find_task(queue, task_id)
    if task["task_type"] != "army_training":
        raise TaskQueueError("Tylko zadanie army_training można zakończyć przez planer treningu.")
    order_id = task["payload"].get("training_order_id")
    if plan["active_order_id"] != order_id:
        raise TaskQueueError("Ukończone zadanie nie odpowiada aktywnemu zleceniu planu.")

    current_time = _utc_time(now)
    completed_task = confirm_task_completed(queue, task_id, now=current_time)
    completed_order = confirm_active_order_run_completed(plan, now=current_time)
    validate_plan(plan, expected_profile_id=queue["profile_id"])
    validate_task_queue(queue)
    return {"task": completed_task, "order": completed_order}