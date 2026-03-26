import json
from typing import List, Optional, Dict, Any
from sqlalchemy import select, or_, and_, not_
from sqlalchemy.ext.asyncio import AsyncSession

from common.config import settings
from common.models import (
    InboxItem,
    MemorySummary,
    Reminder,
    ReminderStatus,
    WorkItem,
    WorkItemKind,
    WorkItemLink,
    WorkItemLinkType,
    WorkItemStatus,
)
from common.telegram import user_facing_task_title

def _estimate_tokens_heuristic(text: str) -> int:
    if not text:
        return 0
    return len(text) // 4 + 1


def _estimate_tokens_precise(text: str) -> Optional[int]:
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore
    except Exception:
        return None
    try:
        encoder = tiktoken.get_encoding("cl100k_base")
        return len(encoder.encode(text))
    except Exception:
        return None


def estimate_tokens(text: str) -> int:
    if settings.MEMORY_PRECISE_TOKEN_ESTIMATOR:
        precise = _estimate_tokens_precise(text)
        if precise is not None:
            return precise
    return _estimate_tokens_heuristic(text)


def token_estimator_mode() -> str:
    if not settings.MEMORY_PRECISE_TOKEN_ESTIMATOR:
        return "heuristic"
    precise = _estimate_tokens_precise("mode_probe")
    if precise is None:
        return "heuristic_fallback"
    return "precise_cl100k_base"

def get_system_policy() -> str:
    return (
        "You are a helpful assistant managing local-first work items and reminders. "
        "Use the provided context to answer accurately. "
        "Prioritize recent information and linked entities."
    )


def format_session_state(session_state: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(session_state, dict):
        return None
    lines = []
    current_mode = str(session_state.get("current_mode") or "").strip()
    if current_mode:
        lines.append(f"Session mode: {current_mode}")
    pending_draft_id = str(session_state.get("pending_draft_id") or "").strip()
    if pending_draft_id:
        lines.append(f"Pending draft: {pending_draft_id}")
    pending_clarification = session_state.get("pending_clarification")
    if isinstance(pending_clarification, dict) and pending_clarification:
        kind = str(pending_clarification.get("kind") or "").strip()
        if kind:
            lines.append(f"Pending clarification: {kind}")
    active_refs = session_state.get("active_entity_refs")
    if isinstance(active_refs, list) and active_refs:
        preview = []
        for row in active_refs[:6]:
            if not isinstance(row, dict):
                continue
            entity_type = str(row.get("entity_type") or "").strip()
            title = str(row.get("title") or "").strip()
            if title:
                preview.append(f"{entity_type or 'entity'}:{title}")
        if preview:
            lines.append("Active entities: " + ", ".join(preview))
    summary_metadata = session_state.get("summary_metadata")
    if isinstance(summary_metadata, dict):
        summary_text = str(summary_metadata.get("last_summary_text") or "").strip()
        if summary_text:
            lines.append(f"Session summary: {summary_text}")
    if not lines:
        return None
    return "\n".join(lines)

async def select_hot_turns(db: AsyncSession, user_id: str, chat_id: str, limit: int) -> List[str]:
    stmt = select(InboxItem).where(
        InboxItem.user_id == user_id,
        InboxItem.chat_id == chat_id
    ).order_by(InboxItem.received_at.desc()).limit(limit)
    objs = (await db.execute(stmt)).scalars().all()
    return [f"{t.source}: {t.message_norm}" for t in reversed(objs)]

async def select_warm_summaries(db: AsyncSession, user_id: str, chat_id: str) -> Optional[str]:
    stmt = select(MemorySummary).where(
        MemorySummary.user_id == user_id,
        MemorySummary.chat_id == chat_id
    ).order_by(MemorySummary.created_at.desc()).limit(1)
    summary_obj = (await db.execute(stmt)).scalar_one_or_none()
    return f"Summary: {summary_obj.summary_text}" if summary_obj else None

async def select_related_entities(db: AsyncSession, user_id: str, query: str, limit: int) -> List[str]:
    """
    Select entities based on recency + link proximity.
    """
    # 1. Start with recent tasks
    stmt_tasks = (
        select(WorkItem)
        .where(
            WorkItem.user_id == user_id,
            WorkItem.kind.in_([WorkItemKind.task, WorkItemKind.subtask]),
            WorkItem.status != WorkItemStatus.archived,
        )
        .order_by(WorkItem.updated_at.desc())
        .limit(limit // 2)
    )
    tasks = (await db.execute(stmt_tasks)).scalars().all()
    task_ids = [t.id for t in tasks]
    reminders = (
        await db.execute(
            select(Reminder)
            .where(
                Reminder.user_id == user_id,
                Reminder.status == ReminderStatus.pending,
            )
            .order_by(Reminder.remind_at.asc())
            .limit(max(2, limit // 4))
        )
    ).scalars().all()
    
    # 2. Include linked projects
    related_project_ids = []
    if task_ids:
        stmt_links = select(WorkItemLink).where(
            WorkItemLink.user_id == user_id,
            WorkItemLink.from_work_item_id.in_(task_ids),
            WorkItemLink.link_type == WorkItemLinkType.part_of,
        )
        links = (await db.execute(stmt_links)).scalars().all()
        related_project_ids = [
            link.to_work_item_id
            for link in links
            if isinstance(getattr(link, "to_work_item_id", None), str) and link.to_work_item_id
        ]

    # 3. Fetch projects by link proximity then recency
    projects = []
    if related_project_ids:
        stmt_projects = select(WorkItem).where(
            WorkItem.user_id == user_id,
            WorkItem.id.in_(related_project_ids),
            WorkItem.kind == WorkItemKind.project,
            WorkItem.status != WorkItemStatus.archived,
        )
        projects.extend((await db.execute(stmt_projects)).scalars().all())

    # Fill remaining slots by recency if under limit
    if len(projects) + len(tasks) < limit:
        needed = limit - (len(projects) + len(tasks))
        stmt_projects_rec = (
            select(WorkItem)
            .where(
                WorkItem.user_id == user_id,
                WorkItem.kind == WorkItemKind.project,
                WorkItem.status != WorkItemStatus.archived,
            )
            .order_by(WorkItem.updated_at.desc())
            .limit(max(1, needed // 2))
        )
        more_projects = (await db.execute(stmt_projects_rec)).scalars().all()
        for project in more_projects:
            if project.id not in related_project_ids:
                projects.append(project)

    # Format
    res = []
    for t in tasks[:limit//2]:
        status = getattr(getattr(t, "status", None), "value", getattr(t, "status", None))
        res.append(f"Task: {user_facing_task_title(t.title)} (Status: {status})")
    for reminder in reminders[: max(1, limit // 4)]:
        remind_at = getattr(reminder, "remind_at", None)
        remind_text = remind_at.isoformat() if hasattr(remind_at, "isoformat") else "unknown"
        res.append(f"Reminder: {reminder.title} (Remind at: {remind_text})")
    for project in projects[: limit // 4]:
        status = getattr(getattr(project, "status", None), "value", getattr(project, "status", None))
        res.append(f"Project: {project.title} (Status: {status})")
    return res

def enforce_budget(
    policy: str, 
    summary: Optional[str], 
    hot_turns: List[str], 
    entities: List[str], 
    query: str, 
    applied_max: int,
    session_state_text: Optional[str] = None,
) -> Dict[str, Any]:
    
    budget_truncated_core = False
    trunc_msg = "... [truncated]"
    estimator_mode = token_estimator_mode()
    
    def build_draft(ss, s, h, e, q):
        parts = [policy]
        if ss: parts.append(ss)
        if s: parts.append(s)
        parts.extend(h)
        parts.extend(e)
        parts.append(f"Query: {q}")
        return "\n".join(parts)

    current_session_state = session_state_text
    current_summary = summary
    current_hot = list(hot_turns)
    current_entities = list(entities)
    current_query = query

    # 1. Check if policy + query (minimum) already exceed budget
    # Estimate minimum possible payload
    min_parts = [policy]
    if current_session_state:
        min_parts.append(current_session_state)
    min_parts.append("Query: ")
    min_draft_no_q = "\n".join(min_parts)
    if estimate_tokens(min_draft_no_q + current_query) > applied_max:
        budget_truncated_core = True
        # Calculate exactly how many tokens are left for the query
        tokens_for_query = applied_max - estimate_tokens(min_draft_no_q) - estimate_tokens(trunc_msg) - 2
        if tokens_for_query > 0:
            char_limit = max(0, tokens_for_query * 4)
            current_query = current_query[:char_limit] + trunc_msg
        else:
            current_query = "[truncated]"
        
        # Strip all other layers if query alone is that big
        current_summary = None
        current_hot = []
        current_entities = []

    # 2. Progressively trim layers with re-checks
    # Trim hot turns first (oldest first)
    while current_hot and estimate_tokens(build_draft(current_session_state, current_summary, current_hot, current_entities, current_query)) > applied_max:
        current_hot.pop(0)
        
    # Trim entities next
    while current_entities and estimate_tokens(build_draft(current_session_state, current_summary, current_hot, current_entities, current_query)) > applied_max:
        current_entities.pop()
        
    # Trim summary last
    if current_summary and estimate_tokens(build_draft(current_session_state, current_summary, current_hot, current_entities, current_query)) > applied_max:
        current_summary = None

    # 3. Final safety check - if still over budget due to estimation drift, force truncate query
    final_payload = build_draft(current_session_state, current_summary, current_hot, current_entities, current_query)
    if estimate_tokens(final_payload) > applied_max:
        budget_truncated_core = True
        # Hard emergency truncate. With estimator = floor(len/4) + 1, 
        # we need len <= (applied_max - 1) * 4 to guarantee estimate <= applied_max.
        safe_chars = max(0, (applied_max - 1) * 4)
        final_payload = final_payload[:safe_chars]

    return {
        "context": final_payload,
        "metadata": {
            "estimated_used": estimate_tokens(final_payload),
            "token_estimator": estimator_mode,
            "budget_truncated_core": budget_truncated_core,
            "counts": {
                "hot_turns": len(current_hot),
                "summaries": 1 if current_summary else 0,
                "entities": len(current_entities)
            }
        }
    }

async def assemble_context(
    db: AsyncSession, 
    user_id: str, 
    chat_id: str, 
    query: str, 
    max_tokens: Optional[int] = None,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    
    applied_max = min(max_tokens or settings.MEMORY_CONTEXT_MAX_TOKENS, settings.MEMORY_CONTEXT_MAX_TOKENS)
    
    policy = get_system_policy()
    session_state_text = format_session_state(session_state)
    summary = await select_warm_summaries(db, user_id, chat_id)
    hot_turns = await select_hot_turns(db, user_id, chat_id, settings.MEMORY_HOT_TURNS_LIMIT)
    entities = await select_related_entities(db, user_id, query, settings.MEMORY_RELATED_ENTITIES_LIMIT)
    
    enforced = enforce_budget(policy, summary, hot_turns, entities, query, applied_max, session_state_text=session_state_text)
    
    return {
        "budget": {
            "requested": max_tokens or settings.MEMORY_CONTEXT_MAX_TOKENS,
            "applied": applied_max,
            "estimated_used": enforced["metadata"]["estimated_used"]
        },
        "sources": enforced["metadata"]["counts"],
        "metadata": {
            "token_estimator": enforced["metadata"]["token_estimator"],
            "budget_truncated_core": enforced["metadata"]["budget_truncated_core"]
        },
        "context": enforced["context"]
    }
