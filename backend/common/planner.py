import json
from datetime import datetime, date
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.config import settings
from common.models import Task, Goal, EntityLink, TaskStatus, EntityType, LinkType, GoalStatus

async def collect_planning_state(db: AsyncSession, user_id: str) -> Dict[str, Any]:
    # 1. Fetch all tasks that are not archived
    stmt_tasks = select(Task).where(Task.user_id == user_id, Task.status != TaskStatus.archived)
    all_tasks = (await db.execute(stmt_tasks)).scalars().all()
    
    # 2. Fetch active goals
    stmt_goals = select(Goal).where(Goal.user_id == user_id, Goal.status == GoalStatus.active)
    goals = (await db.execute(stmt_goals)).scalars().all()
    
    # 3. Fetch all entity links for this user
    stmt_links = select(EntityLink).where(EntityLink.user_id == user_id)
    links = (await db.execute(stmt_links)).scalars().all()
    
    return {
        "tasks": all_tasks,
        "goals": goals,
        "links": links
    }

def detect_blocked_tasks(tasks: List[Task], links: List[EntityLink]) -> Tuple[List[str], Dict[str, List[str]]]:
    """
    Returns (ready_task_ids, blocked_map_with_reasons).
    Rules: explicit blocked status, unfinished depends_on, unfinished blocks.
    """
    ready_ids = []
    blocked_map = {} # task_id -> list of reasons
    
    # Task lookup for all tasks
    task_lookup = {t.id: t for t in tasks}
    
    # Evaluate blocks for OPEN and BLOCKED tasks
    candidate_tasks = [t for t in tasks if t.status in (TaskStatus.open, TaskStatus.blocked)]
    
    for task in candidate_tasks:
        reasons = []
        
        # 1. Explicitly blocked status (Requirement 1)
        if task.status == TaskStatus.blocked:
            reasons.append("Task status is explicitly set to 'blocked'.")

        # 2. Check links
        for link in links:
            if link.link_type == LinkType.depends_on and link.from_entity_id == task.id and link.from_entity_type == EntityType.task:
                dep_id = link.to_entity_id
                dep_task = task_lookup.get(dep_id)
                if not dep_task or dep_task.status != TaskStatus.done:
                    title = dep_task.title if dep_task else f"Unknown Task {dep_id}"
                    reasons.append(f"Depends on unfinished task: {title}")
            
            if link.link_type == LinkType.blocks and link.to_entity_id == task.id and link.to_entity_type == EntityType.task:
                blocker_id = link.from_entity_id
                blocker_task = task_lookup.get(blocker_id)
                if not blocker_task or blocker_task.status != TaskStatus.done:
                    title = blocker_task.title if blocker_task else f"Unknown Task {blocker_id}"
                    reasons.append(f"Blocked by unfinished task: {title}")
                    
        if reasons:
            blocked_map[task.id] = reasons
        elif task.status == TaskStatus.open: # Only open and unblocked are 'ready'
            ready_ids.append(task.id)
            
    return ready_ids, blocked_map

def score_task(task: Task, state: Dict[str, Any], now: datetime) -> Tuple[float, List[str]]:
    score = 0.0
    factors = []
    links = state["links"]
    goals = state["goals"]
    active_goal_ids = {g.id for g in goals}
    
    # 1. Urgency (Weight 4.0)
    if task.due_date:
        days_diff = (task.due_date - now.date()).days
        if days_diff < 0:
            score += settings.PLAN_WEIGHT_URGENCY * 2
            factors.append("overdue")
        elif days_diff <= 2:
            score += settings.PLAN_WEIGHT_URGENCY
            factors.append("due_soon")
            
    # 2. Impact (Weight 3.0)
    if task.impact_score:
        score += (task.impact_score / 5.0) * settings.PLAN_WEIGHT_IMPACT
        if task.impact_score >= 4:
            factors.append("high_impact")
            
    # 3. Goal Alignment (Weight 2.0)
    aligned = False
    for link in links:
        if link.from_entity_id == task.id and link.from_entity_type == EntityType.task:
            if link.link_type == LinkType.supports_goal or link.to_entity_type == EntityType.goal:
                if link.to_entity_id in active_goal_ids:
                    aligned = True
                    break
    if aligned:
        score += settings.PLAN_WEIGHT_GOAL_ALIGNMENT
        factors.append("goal_alignment")
        
    # 4. Staleness (Weight 1.0)
    days_stale = (now - task.updated_at.replace(tzinfo=None)).days
    if days_stale > 7:
        score += min(days_stale / 30.0, 1.0) * settings.PLAN_WEIGHT_STALENESS
        factors.append("stale")
        
    # 5. Quick Win
    if task.priority == 4:
        score += 0.5
        factors.append("quick_win")

    return score, factors

def build_plan_payload(state: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    all_tasks = state["tasks"]
    links = state["links"]
    
    ready_ids, blocked_map = detect_blocked_tasks(all_tasks, links)
    
    # Candidates for ranking are only OPEN tasks that are NOT blocked
    candidate_tasks = [t for t in all_tasks if t.id in ready_ids]
    
    scored_candidates = []
    for task in candidate_tasks:
        score, factors = score_task(task, state, now)
        scored_candidates.append({
            "task": task,
            "score": score,
            "factors": factors
        })
            
    # Tie-break order
    scored_candidates.sort(key=lambda x: (
        -x["score"],
        x["task"].due_date or date.max,
        x["task"].priority or 99,
        x["task"].updated_at,
        x["task"].id
    ))
    
    today_plan = []
    why_this_order = []
    for idx, st in enumerate(scored_candidates[:settings.PLAN_TOP_N_TODAY]):
        t = st["task"]
        rank = idx + 1
        today_plan.append({
            "task_id": t.id,
            "rank": rank,
            "title": t.title,
            "score": st["score"]
        })
        why_this_order.append({
            "task_id": t.id,
            "factors": st["factors"] if st["factors"] else ["dependency_ready"]
        })
        
    next_actions = []
    for idx, st in enumerate(scored_candidates[settings.PLAN_TOP_N_TODAY : settings.PLAN_TOP_N_TODAY + settings.PLAN_TOP_N_NEXT]):
        t = st["task"]
        rank = settings.PLAN_TOP_N_TODAY + idx + 1
        next_actions.append({
            "task_id": t.id,
            "rank": rank,
            "title": t.title,
            "score": st["score"]
        })
        
    blocked_items = []
    for tid, reasons in blocked_map.items():
        t = next((task for task in all_tasks if task.id == tid), None)
        if t:
            blocked_items.append({
                "task_id": tid,
                "title": t.title,
                "blocked_by": reasons
            })
            
    payload = {
        "schema_version": "plan.v1",
        "plan_window": "today",
        "generated_at": now.isoformat() + "Z",
        "today_plan": today_plan,
        "next_actions": next_actions,
        "blocked_items": blocked_items,
        "why_this_order": why_this_order,
        "assumptions": []
    }
    
    return payload

def render_fallback_plan_explanation(plan_payload: Dict[str, Any]) -> Dict[str, Any]:
    # Fallback path ensures minimal keys are present
    return plan_payload