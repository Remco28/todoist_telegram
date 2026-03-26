import hashlib
import uuid
from datetime import timedelta
from typing import Any, Dict

from fastapi import HTTPException, status
from sqlalchemy import select


async def run_get_authenticated_user(request, *, helpers: Dict[str, Any]):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )
    token = auth_header.split(" ")[1]
    token_map = helpers["settings"].token_user_map
    if token_map:
        mapped_user = token_map.get(token)
        if mapped_user:
            return mapped_user
    if token not in helpers["settings"].auth_tokens:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if token == "test_user_2":
        return "usr_2"
    return "usr_dev"


async def run_enforce_rate_limit(user_id: str, endpoint_class: str, limit: int, *, helpers: Dict[str, Any]):
    key = f"rate_limit:{endpoint_class}:{user_id}"
    current = await helpers["redis_client"].incr(key)
    if current == 1:
        await helpers["redis_client"].expire(key, helpers["settings"].RATE_LIMIT_WINDOW_SECONDS)
    if current > limit:
        ttl = await helpers["redis_client"].ttl(key)
        if ttl is None or ttl < 0:
            ttl = helpers["settings"].RATE_LIMIT_WINDOW_SECONDS
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {endpoint_class}. Retry in {ttl}s.",
        )


def run_extract_usage(metadata: Any) -> Dict[str, int]:
    if not isinstance(metadata, dict):
        return {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
    usage = metadata.get("usage", metadata)
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
    return {
        "input_tokens": usage.get("input_tokens", 0) if isinstance(usage.get("input_tokens", 0), int) else 0,
        "output_tokens": usage.get("output_tokens", 0) if isinstance(usage.get("output_tokens", 0), int) else 0,
        "cached_input_tokens": usage.get("cached_input_tokens", 0)
        if isinstance(usage.get("cached_input_tokens", 0), int)
        else 0,
    }


def run_validate_extraction_payload(extraction: Any, *, helpers: Dict[str, Any]) -> None:
    if not isinstance(extraction, dict):
        raise ValueError("Invalid extraction payload type")

    required = ("tasks", "goals", "problems", "links")
    for key in required:
        value = extraction.get(key)
        if not isinstance(value, list):
            raise ValueError(f"Invalid extraction list for key: {key}")
    reminders = extraction.get("reminders", [])
    if reminders is None:
        reminders = []
    if not isinstance(reminders, list):
        raise ValueError("Invalid extraction list for key: reminders")
    extraction["reminders"] = reminders

    for task in extraction["tasks"]:
        if not isinstance(task, dict):
            raise ValueError("Invalid task entry type")
        if not isinstance(task.get("title"), str) or not task.get("title").strip():
            raise ValueError("Invalid task title")
        if "kind" in task and task.get("kind") is not None:
            if task.get("kind") not in {"project", "task", "subtask"}:
                raise ValueError("Invalid task kind")
        action = task.get("action")
        if action is not None and action not in {"create", "update", "complete", "archive", "noop"}:
            raise ValueError("Invalid task action")
        if "target_task_id" in task and task.get("target_task_id") is not None and not isinstance(
            task.get("target_task_id"), str
        ):
            raise ValueError("Invalid target_task_id")
        if "parent_task_id" in task and task.get("parent_task_id") is not None and not isinstance(
            task.get("parent_task_id"), str
        ):
            raise ValueError("Invalid parent_task_id")
        if "parent_title" in task and task.get("parent_title") is not None and not isinstance(
            task.get("parent_title"), str
        ):
            raise ValueError("Invalid parent_title")
        if "priority" in task and task.get("priority") is not None and not isinstance(task.get("priority"), int):
            raise ValueError("Invalid task priority")
        if "priority" in task and isinstance(task.get("priority"), int) and not (1 <= task.get("priority") <= 4):
            raise ValueError("Invalid task priority range")
        if "impact_score" in task and task.get("impact_score") is not None:
            if not isinstance(task.get("impact_score"), int) or not (1 <= task.get("impact_score") <= 5):
                raise ValueError("Invalid task impact_score")
        if "urgency_score" in task and task.get("urgency_score") is not None:
            if not isinstance(task.get("urgency_score"), int) or not (1 <= task.get("urgency_score") <= 5):
                raise ValueError("Invalid task urgency_score")
        if "notes" in task and task.get("notes") is not None and not isinstance(task.get("notes"), str):
            raise ValueError("Invalid task notes")
        if "due_date" in task and task.get("due_date") is not None:
            due_raw = task.get("due_date")
            if not isinstance(due_raw, str):
                raise ValueError("Invalid task due_date")
            if helpers["_parse_due_date"](due_raw) is None:
                raise ValueError("Invalid task due_date format")

    folded_project_tasks = []
    for goal in extraction["goals"]:
        if not isinstance(goal, dict):
            raise ValueError("Invalid goal entry type")
        if not isinstance(goal.get("title"), str) or not goal.get("title").strip():
            raise ValueError("Invalid goal title")
        folded_project_tasks.append(
            {
                "title": goal.get("title").strip(),
                "kind": "project",
                "notes": goal.get("description").strip()
                if isinstance(goal.get("description"), str) and goal.get("description").strip()
                else None,
            }
        )

    for problem in extraction["problems"]:
        if not isinstance(problem, dict):
            raise ValueError("Invalid problem entry type")
        if not isinstance(problem.get("title"), str) or not problem.get("title").strip():
            raise ValueError("Invalid problem title")
        folded_project_tasks.append(
            {
                "title": problem.get("title").strip(),
                "kind": "project",
                "notes": problem.get("description").strip()
                if isinstance(problem.get("description"), str) and problem.get("description").strip()
                else None,
            }
        )

    if folded_project_tasks:
        extraction["tasks"].extend(folded_project_tasks)
        extraction["goals"] = []
        extraction["problems"] = []

    link_keys = ("from_type", "from_title", "to_type", "to_title", "link_type")
    for link in extraction["links"]:
        if not isinstance(link, dict):
            raise ValueError("Invalid link entry type")
        for key in link_keys:
            if not isinstance(link.get(key), str) or not link.get(key).strip():
                raise ValueError(f"Invalid link field: {key}")

    for reminder in extraction["reminders"]:
        if not isinstance(reminder, dict):
            raise ValueError("Invalid reminder entry type")
        if not isinstance(reminder.get("title"), str) or not reminder.get("title").strip():
            raise ValueError("Invalid reminder title")
        action = reminder.get("action")
        if action is not None and action not in {"create", "update", "complete", "dismiss", "cancel", "noop"}:
            raise ValueError("Invalid reminder action")
        if "target_reminder_id" in reminder and reminder.get("target_reminder_id") is not None and not isinstance(
            reminder.get("target_reminder_id"), str
        ):
            raise ValueError("Invalid target_reminder_id")
        if "message" in reminder and reminder.get("message") is not None and not isinstance(
            reminder.get("message"), str
        ):
            raise ValueError("Invalid reminder message")
        if "remind_at" in reminder and reminder.get("remind_at") is not None:
            remind_at = reminder.get("remind_at")
            if not isinstance(remind_at, str):
                raise ValueError("Invalid reminder remind_at")
            if helpers["_parse_due_at"](remind_at) is None:
                raise ValueError("Invalid reminder remind_at format")
        if "kind" in reminder and reminder.get("kind") is not None:
            if reminder.get("kind") not in {"one_off", "follow_up", "recurring"}:
                raise ValueError("Invalid reminder kind")
        if "status" in reminder and reminder.get("status") is not None:
            if reminder.get("status") not in {"pending", "sent", "completed", "dismissed", "canceled"}:
                raise ValueError("Invalid reminder status")
        if "recurrence_rule" in reminder and reminder.get("recurrence_rule") is not None:
            recurrence_rule = reminder.get("recurrence_rule")
            if not isinstance(recurrence_rule, str):
                raise ValueError("Invalid reminder recurrence_rule")
            if helpers["normalize_recurrence_rule"](recurrence_rule) is None:
                raise ValueError("Invalid reminder recurrence_rule")
        if "work_item_id" in reminder and reminder.get("work_item_id") is not None and not isinstance(
            reminder.get("work_item_id"), str
        ):
            raise ValueError("Invalid reminder work_item_id")
        if "person_id" in reminder and reminder.get("person_id") is not None and not isinstance(
            reminder.get("person_id"), str
        ):
            raise ValueError("Invalid reminder person_id")
        reminder_action = str(reminder.get("action") or "").strip().lower()
        if reminder_action == "create" and helpers["_parse_due_at"](reminder.get("remind_at")) is None:
            raise ValueError("Reminder create requires remind_at")
        reminder_kind = str(reminder.get("kind") or "").strip().lower()
        if reminder_kind == "recurring" and not reminder.get("recurrence_rule"):
            raise ValueError("Recurring reminders require recurrence_rule")


async def run_check_idempotency(request, user_id: str, db, *, helpers: Dict[str, Any]):
    if request.method not in ["POST", "PATCH", "PUT", "DELETE"]:
        return
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Idempotency-Key header")

    body = await request.body()
    identity_string = f"{request.method}|{request.url.path}|{user_id}|{body.decode('utf-8', errors='ignore')}"
    body_hash = hashlib.sha256(identity_string.encode("utf-8")).hexdigest()

    stmt = select(helpers["IdempotencyKey"]).where(
        helpers["IdempotencyKey"].user_id == user_id,
        helpers["IdempotencyKey"].idempotency_key == idempotency_key,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        if existing.request_hash != body_hash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key collision")
        request.state.idempotent_response = existing.response_body

    request.state.idempotency_key = idempotency_key
    request.state.request_hash = body_hash


async def run_save_idempotency(
    user_id: str,
    idempotency_key: str,
    request_hash: str,
    status_code: int,
    response_body: dict,
    *,
    helpers: Dict[str, Any],
):
    async with helpers["AsyncSessionLocal"]() as db:
        ik = helpers["IdempotencyKey"](
            id=str(uuid.uuid4()),
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_status=status_code,
            response_body=response_body,
            created_at=helpers["utc_now"](),
            expires_at=helpers["utc_now"]() + timedelta(hours=helpers["settings"].IDEMPOTENCY_TTL_HOURS),
        )
        db.add(ik)
        await db.commit()
