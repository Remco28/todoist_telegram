import json
from typing import List, Optional, Dict, Any
from sqlalchemy import select, or_, and_, not_
from sqlalchemy.ext.asyncio import AsyncSession

from common.config import settings
from common.models import InboxItem, MemorySummary, Task, Goal, Problem, EntityLink, EntityType

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
        "You are a helpful assistant managing tasks, goals, and problems. "
        "Use the provided context to answer accurately. "
        "Prioritize recent information and linked entities."
    )

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
    stmt_tasks = select(Task).where(Task.user_id == user_id).order_by(Task.updated_at.desc()).limit(limit // 2)
    tasks = (await db.execute(stmt_tasks)).scalars().all()
    task_ids = [t.id for t in tasks]
    
    # 2. Include linked goals/problems
    related_ids = []
    if task_ids:
        stmt_links = select(EntityLink).where(
            EntityLink.user_id == user_id,
            EntityLink.from_entity_id.in_(task_ids),
            EntityLink.from_entity_type == EntityType.task
        )
        links = (await db.execute(stmt_links)).scalars().all()
        related_ids = [(l.to_entity_type, l.to_entity_id) for l in links]

    # 3. Fetch goals/problems by link proximity then recency
    goals = []
    problems = []
    
    # Fetch specifically linked ones first
    linked_goal_ids = [rid[1] for rid in related_ids if rid[0] == EntityType.goal]
    if linked_goal_ids:
        stmt_g = select(Goal).where(Goal.id.in_(linked_goal_ids))
        goals.extend((await db.execute(stmt_g)).scalars().all())
    
    linked_prob_ids = [rid[1] for rid in related_ids if rid[0] == EntityType.problem]
    if linked_prob_ids:
        stmt_p = select(Problem).where(Problem.id.in_(linked_prob_ids))
        problems.extend((await db.execute(stmt_p)).scalars().all())

    # Fill remaining slots by recency if under limit
    if len(goals) + len(problems) + len(tasks) < limit:
        needed = limit - (len(goals) + len(problems) + len(tasks))
        stmt_g_rec = select(Goal).where(Goal.user_id == user_id).order_by(Goal.updated_at.desc()).limit(needed // 2)
        more_goals = (await db.execute(stmt_g_rec)).scalars().all()
        for mg in more_goals:
            if mg.id not in linked_goal_ids: goals.append(mg)
            
        stmt_p_rec = select(Problem).where(Problem.user_id == user_id).order_by(Problem.updated_at.desc()).limit(needed // 2)
        more_probs = (await db.execute(stmt_p_rec)).scalars().all()
        for mp in more_probs:
            if mp.id not in linked_prob_ids: problems.append(mp)

    # Format
    res = []
    for t in tasks[:limit//2]: res.append(f"Task [{t.id}]: {t.title} (Status: {t.status.value})")
    for g in goals[:limit//4]: res.append(f"Goal [{g.id}]: {g.title} (Status: {g.status.value})")
    for p in problems[:limit//4]: res.append(f"Problem [{p.id}]: {p.title} (Status: {p.status.value})")
    return res

def enforce_budget(
    policy: str, 
    summary: Optional[str], 
    hot_turns: List[str], 
    entities: List[str], 
    query: str, 
    applied_max: int
) -> Dict[str, Any]:
    
    budget_truncated_core = False
    trunc_msg = "... [truncated]"
    estimator_mode = token_estimator_mode()
    
    def build_draft(s, h, e, q):
        parts = [policy]
        if s: parts.append(s)
        parts.extend(h)
        parts.extend(e)
        parts.append(f"Query: {q}")
        return "\n".join(parts)

    current_summary = summary
    current_hot = list(hot_turns)
    current_entities = list(entities)
    current_query = query

    # 1. Check if policy + query (minimum) already exceed budget
    # Estimate minimum possible payload
    min_draft_no_q = f"{policy}\nQuery: "
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
    while current_hot and estimate_tokens(build_draft(current_summary, current_hot, current_entities, current_query)) > applied_max:
        current_hot.pop(0)
        
    # Trim entities next
    while current_entities and estimate_tokens(build_draft(current_summary, current_hot, current_entities, current_query)) > applied_max:
        current_entities.pop()
        
    # Trim summary last
    if current_summary and estimate_tokens(build_draft(current_summary, current_hot, current_entities, current_query)) > applied_max:
        current_summary = None

    # 3. Final safety check - if still over budget due to estimation drift, force truncate query
    final_payload = build_draft(current_summary, current_hot, current_entities, current_query)
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
    max_tokens: Optional[int] = None
) -> Dict[str, Any]:
    
    applied_max = min(max_tokens or settings.MEMORY_CONTEXT_MAX_TOKENS, settings.MEMORY_CONTEXT_MAX_TOKENS)
    
    policy = get_system_policy()
    summary = await select_warm_summaries(db, user_id, chat_id)
    hot_turns = await select_hot_turns(db, user_id, chat_id, settings.MEMORY_HOT_TURNS_LIMIT)
    entities = await select_related_entities(db, user_id, query, settings.MEMORY_RELATED_ENTITIES_LIMIT)
    
    enforced = enforce_budget(policy, summary, hot_turns, entities, query, applied_max)
    
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
