import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.config import settings
from common.models import Reminder, ReminderStatus, WorkItem, WorkItemKind, WorkItemLink, WorkItemLinkType, WorkItemStatus

_TASK_TITLE_WRAPPER_PATTERNS = (
    re.compile(
        r"^(?:move|set|reschedule)\s+(?P<quote>['\"])?(?P<title>.+?)(?P=quote)?\s+(?:to|for)\s+"
        r"(?:today|tomorrow|tonight|this week|next week|this month|next month)\.?$",
        re.IGNORECASE,
    ),
)
_TITLE_DEDUPE_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "onto",
    "about",
    "your",
    "our",
}


def _as_utc_datetime(value: Any, fallback: Optional[datetime] = None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if fallback is not None:
        return _as_utc_datetime(fallback)
    return datetime.now(timezone.utc)


def _planner_timezone():
    tz_name = (settings.APP_TIMEZONE or "").strip() or "UTC"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _local_date_in_planner(value: datetime) -> date:
    return _as_utc_datetime(value).astimezone(_planner_timezone()).date()


def _user_visible_title(title: Any) -> str:
    text = re.sub(r"\s+", " ", str(title or "").strip())
    if not text:
        return ""
    for pattern in _TASK_TITLE_WRAPPER_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        inner = re.sub(r"\s+", " ", (match.group("title") or "").strip())
        if inner:
            return inner
    return text


def _normalized_title_tokens(title: Any) -> List[str]:
    visible = _user_visible_title(title).lower()
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", visible)
    return [token for token in cleaned.split() if len(token) >= 3 and token not in _TITLE_DEDUPE_STOPWORDS]


def _is_near_duplicate_title(left: Any, right: Any) -> bool:
    left_tokens = set(_normalized_title_tokens(left))
    right_tokens = set(_normalized_title_tokens(right))
    if not left_tokens or not right_tokens:
        return _user_visible_title(left).lower() == _user_visible_title(right).lower()
    overlap = left_tokens & right_tokens
    shorter_ratio = len(overlap) / max(1, min(len(left_tokens), len(right_tokens)))
    longer_ratio = len(overlap) / max(1, max(len(left_tokens), len(right_tokens)))
    return shorter_ratio >= 0.80 and longer_ratio >= 0.60


def _title_information_score(title: Any) -> Tuple[int, int]:
    visible = _user_visible_title(title)
    tokens = _normalized_title_tokens(visible)
    return (len(set(tokens)), len(visible))


def _work_item_due_date(item: WorkItem, now: Optional[datetime] = None) -> Optional[date]:
    due_at = getattr(item, "due_at", None)
    if isinstance(due_at, datetime):
        return _as_utc_datetime(due_at, now).date()
    due_date = getattr(item, "due_date", None)
    if isinstance(due_date, date):
        return due_date
    return None


def _work_item_schedule_date(item: Any, now: Optional[datetime] = None) -> Optional[date]:
    scheduled_for = getattr(item, "scheduled_for", None)
    if isinstance(scheduled_for, datetime):
        return _local_date_in_planner(_as_utc_datetime(scheduled_for, now))
    due_at = getattr(item, "due_at", None)
    if isinstance(due_at, datetime):
        return _local_date_in_planner(_as_utc_datetime(due_at, now))
    due_date = getattr(item, "due_date", None)
    if isinstance(due_date, date):
        return due_date
    return None


def _status_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "").strip().lower()


def _link_depends_on(link: Any, task_id: str) -> Optional[str]:
    if getattr(link, "link_type", None) == WorkItemLinkType.depends_on and getattr(link, "from_work_item_id", None) == task_id:
        return getattr(link, "to_work_item_id", None)
    if _status_value(getattr(link, "link_type", None)) == "depends_on" and getattr(link, "from_entity_id", None) == task_id:
        return getattr(link, "to_entity_id", None)
    return None


def _link_blocks(link: Any, task_id: str) -> Optional[str]:
    if getattr(link, "link_type", None) == WorkItemLinkType.blocks and getattr(link, "to_work_item_id", None) == task_id:
        return getattr(link, "from_work_item_id", None)
    if _status_value(getattr(link, "link_type", None)) == "blocks" and getattr(link, "to_entity_id", None) == task_id:
        return getattr(link, "from_entity_id", None)
    return None


async def collect_planning_state(db: AsyncSession, user_id: str) -> Dict[str, Any]:
    tasks = (
        await db.execute(
            select(WorkItem).where(
                WorkItem.user_id == user_id,
                WorkItem.kind.in_([WorkItemKind.task, WorkItemKind.subtask]),
                WorkItem.status != WorkItemStatus.archived,
            )
        )
    ).scalars().all()
    links = (await db.execute(select(WorkItemLink).where(WorkItemLink.user_id == user_id))).scalars().all()
    reminders = (
        await db.execute(
            select(Reminder).where(
                Reminder.user_id == user_id,
                Reminder.status == ReminderStatus.pending,
            )
        )
    ).scalars().all()

    return {"tasks": tasks, "goals": [], "links": links, "reminders": reminders}


def detect_blocked_tasks(tasks: List[Any], links: List[Any]) -> Tuple[List[str], Dict[str, List[str]]]:
    ready_ids: List[str] = []
    blocked_map: Dict[str, List[str]] = {}
    task_lookup = {task.id: task for task in tasks}
    candidate_tasks = [task for task in tasks if _status_value(getattr(task, "status", None)) in {"open", "blocked"}]

    for task in candidate_tasks:
        reasons: List[str] = []
        if _status_value(getattr(task, "status", None)) == "blocked":
            reasons.append("Task status is explicitly set to 'blocked'.")

        for link in links:
            dep_id = _link_depends_on(link, task.id)
            if dep_id:
                dep_task = task_lookup.get(dep_id)
                if not dep_task or _status_value(getattr(dep_task, "status", None)) != "done":
                    title = dep_task.title if dep_task else f"Unknown Task {dep_id}"
                    reasons.append(f"Depends on unfinished task: {title}")

            blocker_id = _link_blocks(link, task.id)
            if blocker_id:
                blocker_task = task_lookup.get(blocker_id)
                if not blocker_task or _status_value(getattr(blocker_task, "status", None)) != "done":
                    title = blocker_task.title if blocker_task else f"Unknown Task {blocker_id}"
                    reasons.append(f"Blocked by unfinished task: {title}")

        if reasons:
            blocked_map[task.id] = reasons
        elif _status_value(getattr(task, "status", None)) == "open":
            ready_ids.append(task.id)

    return ready_ids, blocked_map


def score_task(task: Any, state: Dict[str, Any], now: datetime) -> Tuple[float, List[str]]:
    now_utc = _as_utc_datetime(now)
    score = 0.0
    factors: List[str] = []

    due_date = _work_item_due_date(task, now_utc)
    if due_date:
        days_diff = (due_date - now_utc.date()).days
        if days_diff < 0:
            score += settings.PLAN_WEIGHT_URGENCY * 2
            factors.append("overdue")
        elif days_diff <= 2:
            score += settings.PLAN_WEIGHT_URGENCY
            factors.append("due_soon")

    updated_at_utc = _as_utc_datetime(task.updated_at, now_utc)
    days_stale = (now_utc - updated_at_utc).days
    if days_stale > 7:
        score += min(days_stale / 30.0, 1.0) * settings.PLAN_WEIGHT_STALENESS
        factors.append("stale")

    if task.priority == 1:
        score += 0.5
        factors.append("user_priority_high")
    elif task.priority == 2:
        score += 0.2

    return score, factors


def _is_deferred_beyond_today(task: Any, task_lookup: Dict[str, Any], now: datetime) -> bool:
    current_local_date = _local_date_in_planner(now)
    own_schedule = _work_item_schedule_date(task, now)
    if own_schedule and own_schedule > current_local_date:
        return True
    if own_schedule and own_schedule <= current_local_date:
        return False

    seen: set[str] = set()
    parent_id = getattr(task, "parent_id", None)
    while isinstance(parent_id, str) and parent_id.strip() and parent_id not in seen:
        seen.add(parent_id)
        parent = task_lookup.get(parent_id)
        if not parent:
            break
        parent_schedule = _work_item_schedule_date(parent, now)
        if parent_schedule and parent_schedule > current_local_date:
            return True
        if parent_schedule and parent_schedule <= current_local_date:
            return False
        parent_id = getattr(parent, "parent_id", None)
    return False


def build_plan_payload(state: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    now_utc = _as_utc_datetime(now)
    all_tasks: List[WorkItem] = state["tasks"]
    links: List[WorkItemLink] = state["links"]
    reminders: List[Reminder] = state.get("reminders", [])
    task_lookup = {task.id: task for task in all_tasks}

    ready_ids, blocked_map = detect_blocked_tasks(all_tasks, links)
    candidate_tasks = [
        task
        for task in all_tasks
        if task.id in ready_ids and not _is_deferred_beyond_today(task, task_lookup, now_utc)
    ]

    scored_candidates: List[Dict[str, Any]] = []
    for task in candidate_tasks:
        score, factors = score_task(task, state, now_utc)
        scored_candidates.append({"task": task, "score": score, "factors": factors})

    scored_candidates.sort(
        key=lambda row: (
            -row["score"],
            _work_item_due_date(row["task"], now_utc) or date.max,
            row["task"].priority or 99,
            _as_utc_datetime(row["task"].updated_at, now_utc),
            row["task"].id,
        )
    )

    visible_candidates: List[Dict[str, Any]] = []
    for candidate in scored_candidates:
        duplicate_idx: Optional[int] = None
        for idx, existing in enumerate(visible_candidates):
            if _is_near_duplicate_title(candidate["task"].title, existing["task"].title):
                duplicate_idx = idx
                break
        if duplicate_idx is None:
            visible_candidates.append(candidate)
            continue
        existing = visible_candidates[duplicate_idx]
        if _title_information_score(candidate["task"].title) > _title_information_score(existing["task"].title):
            visible_candidates[duplicate_idx] = candidate

    today_plan: List[Dict[str, Any]] = []
    why_this_order: List[Dict[str, Any]] = []
    for idx, candidate in enumerate(visible_candidates[: settings.PLAN_TOP_N_TODAY]):
        task = candidate["task"]
        today_plan.append(
            {
                "task_id": task.id,
                "rank": idx + 1,
                "title": task.title,
                "score": candidate["score"],
                "estimated_minutes": getattr(task, "estimated_minutes", None),
            }
        )
        why_this_order.append(
            {
                "task_id": task.id,
                "factors": candidate["factors"] if candidate["factors"] else ["dependency_ready"],
            }
        )

    next_actions: List[Dict[str, Any]] = []
    next_slice = visible_candidates[settings.PLAN_TOP_N_TODAY : settings.PLAN_TOP_N_TODAY + settings.PLAN_TOP_N_NEXT]
    for idx, candidate in enumerate(next_slice):
        task = candidate["task"]
        next_actions.append(
            {
                "task_id": task.id,
                "rank": settings.PLAN_TOP_N_TODAY + idx + 1,
                "title": task.title,
                "score": candidate["score"],
                "estimated_minutes": getattr(task, "estimated_minutes", None),
            }
        )

    blocked_items: List[Dict[str, Any]] = []
    for task_id, reasons in blocked_map.items():
        task = next((row for row in all_tasks if row.id == task_id), None)
        if not task:
            continue
        blocked_items.append({"task_id": task_id, "title": task.title, "blocked_by": reasons})

    current_local_date = _local_date_in_planner(now_utc)
    due_reminders: List[Dict[str, Any]] = []
    for reminder in sorted(reminders, key=lambda row: _as_utc_datetime(getattr(row, "remind_at", None), now_utc)):
        remind_at = getattr(reminder, "remind_at", None)
        if not isinstance(remind_at, datetime):
            continue
        if _local_date_in_planner(remind_at) > current_local_date:
            continue
        due_reminders.append(
            {
                "reminder_id": reminder.id,
                "title": reminder.title,
                "message": reminder.message,
                "remind_at": _as_utc_datetime(remind_at).isoformat().replace("+00:00", "Z"),
                "work_item_id": reminder.work_item_id,
            }
        )

    return {
        "schema_version": "plan.v1",
        "plan_window": "today",
        "generated_at": now_utc.isoformat().replace("+00:00", "Z"),
        "today_plan": today_plan,
        "next_actions": next_actions,
        "blocked_items": blocked_items,
        "due_reminders": due_reminders,
        "why_this_order": why_this_order,
        "assumptions": [],
    }


def render_fallback_plan_explanation(plan_payload: Dict[str, Any]) -> Dict[str, Any]:
    return plan_payload
