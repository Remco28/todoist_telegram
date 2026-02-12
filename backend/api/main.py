import uuid
import hashlib
import json
import copy
import time
import re
import logging
import secrets
import asyncio
from datetime import datetime, timedelta, timezone, date
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx

from fastapi import FastAPI, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, select, update, delete

import redis.asyncio as redis

from common.config import settings
from common.models import (
    Base, IdempotencyKey, InboxItem, Task, Goal, Problem, 
    EntityLink, EventLog, PromptRun, TaskStatus, GoalStatus, 
    ProblemStatus, LinkType, EntityType, TodoistTaskMap, RecentContextItem,
    TelegramUserMap, TelegramLinkToken, ActionDraft
)
from common.adapter import adapter
from common.memory import assemble_context
from common.planner import collect_planning_state, build_plan_payload, render_fallback_plan_explanation
from api.schemas import (
    ThoughtCaptureRequest, ThoughtCaptureResponse, AppliedChanges,
    TaskUpdate, GoalUpdate, ProblemUpdate, LinkCreate,
    PlanRefreshRequest, PlanRefreshResponse, PlanResponseV1,
    QueryAskRequest, QueryResponseV1,
    TelegramUpdateEnvelope, TelegramWebhookResponse,
    TodoistSyncStatusResponse, TelegramLinkTokenCreateResponse
)
from common.telegram import (
    verify_telegram_secret, parse_update, extract_command, send_message, edit_message, answer_callback_query, build_draft_reply_markup,
    format_today_plan, format_plan_refresh_ack, format_focus_mode, format_capture_ack,
    escape_html, is_query_like_text, format_query_answer
)

# --- Shared Capture Pipeline ---
ACTION_DRAFT_TTL_SECONDS = 1800
AUTOPILOT_COMPLETION_CONFIDENCE = 0.70
AUTOPILOT_ACTION_CONFIDENCE = 0.90
CLARIFY_ACTION_CONFIDENCE = 0.50
COMPLETION_INTENT_TOKENS = ("mark", "complete", "completed", "close", "closed")


def _draft_now() -> datetime:
    return datetime.now(timezone.utc)


def _local_now() -> datetime:
    tz_name = (settings.APP_TIMEZONE or "").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    return datetime.now(tz)


def _local_today() -> date:
    return _local_now().date()


def _contains_word(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", (text or "").lower()))


def _should_force_tonight_to_today(message: str) -> bool:
    lowered = (message or "").lower()
    if "tomorrow night" in lowered:
        return False
    if _contains_word(lowered, "tomorrow"):
        return False
    return _contains_word(lowered, "tonight")


def _resolve_relative_due_date_overrides(message: str, extraction: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(extraction, dict):
        return extraction
    tasks = extraction.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return extraction
    if not _should_force_tonight_to_today(message):
        return extraction

    forced_due_date = _local_today().isoformat()
    rewritten: List[Any] = []
    for task in tasks:
        if not isinstance(task, dict):
            rewritten.append(task)
            continue
        action = task.get("action")
        status_value = task.get("status")
        if action in {"complete", "archive", "noop"} or status_value in {"done", "archived"}:
            rewritten.append(task)
            continue
        updated = dict(task)
        updated["due_date"] = forced_due_date
        rewritten.append(updated)

    out = dict(extraction)
    out["tasks"] = rewritten
    return out


def _is_telegram_sender_allowed(chat_id: str, username: Optional[str]) -> bool:
    allowed_chat_ids = settings.telegram_allowed_chat_ids
    allowed_usernames = settings.telegram_allowed_usernames
    if not allowed_chat_ids and not allowed_usernames:
        return True
    if chat_id in allowed_chat_ids:
        return True
    normalized_username = (username or "").strip().lstrip("@").lower()
    if normalized_username and normalized_username in allowed_usernames:
        return True
    return False


def _parse_draft_reply(text: str) -> tuple[Optional[str], Optional[str]]:
    normalized = (text or "").strip()
    lowered = normalized.lower()
    if lowered in {"yes", "y", "confirm", "apply", "do it", "sounds good"}:
        return "confirm", None
    if lowered in {"no", "n", "cancel", "discard", "skip"}:
        return "discard", None
    if lowered == "edit":
        return "edit", ""
    if lowered.startswith("edit "):
        return "edit", normalized[5:].strip()
    return None, None


def _parse_draft_callback(callback_data: str) -> tuple[Optional[str], Optional[str]]:
    # Expected format: draft:<confirm|edit|discard>:<draft_id>
    parts = (callback_data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "draft":
        return None, None
    action = parts[1]
    draft_id = parts[2]
    if action not in {"confirm", "edit", "discard"}:
        return None, None
    if not draft_id.strip():
        return None, None
    return action, draft_id.strip()


def _draft_set_awaiting_edit_input(draft: ActionDraft, value: bool) -> None:
    proposal = copy.deepcopy(draft.proposal_json) if isinstance(draft.proposal_json, dict) else {}
    meta = proposal.get("_meta") if isinstance(proposal.get("_meta"), dict) else {}
    meta["awaiting_edit_input"] = bool(value)
    proposal["_meta"] = meta
    draft.proposal_json = proposal


def _draft_is_awaiting_edit_input(draft: ActionDraft) -> bool:
    if not isinstance(draft.proposal_json, dict):
        return False
    meta = draft.proposal_json.get("_meta")
    if not isinstance(meta, dict):
        return False
    return bool(meta.get("awaiting_edit_input"))


def _draft_set_proposal_message_id(draft: ActionDraft, message_id: int) -> None:
    proposal = copy.deepcopy(draft.proposal_json) if isinstance(draft.proposal_json, dict) else {}
    meta = proposal.get("_meta") if isinstance(proposal.get("_meta"), dict) else {}
    meta["proposal_message_id"] = int(message_id)
    proposal["_meta"] = meta
    draft.proposal_json = proposal


def _draft_get_proposal_message_id(draft: ActionDraft) -> Optional[int]:
    if not isinstance(draft.proposal_json, dict):
        return None
    meta = draft.proposal_json.get("_meta")
    if not isinstance(meta, dict):
        return None
    message_id = meta.get("proposal_message_id")
    if isinstance(message_id, int):
        return message_id
    return None


async def _send_or_edit_draft_preview(chat_id: str, draft: ActionDraft, text: str) -> None:
    markup = build_draft_reply_markup(draft.id)
    message_id = _draft_get_proposal_message_id(draft)
    if message_id is not None:
        edited = await edit_message(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
        if edited.get("ok") is True:
            return
    sent = await send_message(chat_id, text, reply_markup=markup)
    result = sent.get("result") if isinstance(sent, dict) else None
    if isinstance(result, dict) and isinstance(result.get("message_id"), int):
        _draft_set_proposal_message_id(draft, result["message_id"])


def _format_action_draft_preview(extraction: Dict[str, Any]) -> str:
    tasks = [t.get("title", "").strip() for t in extraction.get("tasks", []) if isinstance(t, dict) and isinstance(t.get("title"), str)]
    goals = [g.get("title", "").strip() for g in extraction.get("goals", []) if isinstance(g, dict) and isinstance(g.get("title"), str)]
    problems = [p.get("title", "").strip() for p in extraction.get("problems", []) if isinstance(p, dict) and isinstance(p.get("title"), str)]
    links_count = len(extraction.get("links", [])) if isinstance(extraction.get("links"), list) else 0

    if not tasks and not goals and not problems and links_count == 0:
        return (
            "I did not find clear actions to apply yet.\n"
            "Reply with more details, or ask a question directly."
        )

    lines = ["<b>Proposed updates:</b>"]
    if tasks:
        lines.append("")
        lines.append("<b>Tasks</b>")
        for title in tasks[:6]:
            lines.append(f"• {escape_html(title)}")
        if len(tasks) > 6:
            lines.append(f"• +{len(tasks) - 6} more task(s)")
    if goals:
        lines.append("")
        lines.append(f"<b>Goals</b>: {len(goals)}")
    if problems:
        lines.append(f"<b>Problems</b>: {len(problems)}")
    if links_count:
        lines.append(f"<b>Links</b>: {links_count}")

    lines.append("")
    lines.append("Reply with <code>yes</code> to apply, <code>edit ...</code> to revise, or <code>no</code> to discard.")
    return "\n".join(lines)


def _has_actionable_entities(extraction: Dict[str, Any]) -> bool:
    return bool(
        extraction.get("tasks")
        or extraction.get("goals")
        or extraction.get("problems")
        or extraction.get("links")
    )


def _derive_bulk_complete_actions(message: str, grounding: Dict[str, Any]) -> List[Dict[str, Any]]:
    lowered = (message or "").strip().lower()
    if not lowered:
        return []

    has_global_scope = any(
        phrase in lowered
        for phrase in (
            "everything",
            "all tasks",
            "all my tasks",
            "all of my tasks",
            "all open tasks",
        )
    )
    has_completion_intent = any(_contains_word(lowered, phrase) for phrase in COMPLETION_INTENT_TOKENS)
    if not (has_global_scope and has_completion_intent):
        return []

    rows = grounding.get("tasks") if isinstance(grounding, dict) else None
    if not isinstance(rows, list):
        return []

    actions: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = row.get("status")
        if status in {"done", "archived"}:
            continue
        title = row.get("title")
        task_id = row.get("id")
        if not isinstance(title, str) or not title.strip():
            continue
        item: Dict[str, Any] = {
            "title": title.strip(),
            "action": "complete",
            "status": "done",
        }
        if isinstance(task_id, str) and task_id.strip():
            item["target_task_id"] = task_id.strip()
        actions.append(item)
    return actions


def _derive_reference_complete_actions(message: str, grounding: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = (message or "").lower()
    if is_query_like_text(raw):
        return []

    has_reference = any(
        _contains_word(raw, token)
        for token in (
            "those",
            "them",
            "that",
            "these",
            "this",
            "it",
            "assignments",
            "tasks",
            "ones",
        )
    )
    has_completion_intent = any(_contains_word(raw, token) for token in COMPLETION_INTENT_TOKENS)
    if not (has_reference and has_completion_intent):
        return []

    rows = grounding.get("recent_task_refs") if isinstance(grounding, dict) else None
    if not isinstance(rows, list):
        return []

    # Prefer explicit mentions in the current message over broad pronoun resolution.
    message_terms = _grounding_terms(raw)
    message_terms = {
        term
        for term in message_terms
        if term
        not in {
            "mark",
            "done",
            "complete",
            "completed",
            "close",
            "closed",
            "all",
            "those",
            "them",
            "that",
            "these",
            "this",
            "it",
            "assignments",
            "tasks",
            "ones",
            "now",
        }
    }

    explicit_matches: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = row.get("status")
        if status in {"done", "archived"}:
            continue
        title = row.get("title")
        task_id = row.get("id")
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(task_id, str) or not task_id.strip():
            continue

        action_item = {
            "title": title.strip(),
            "action": "complete",
            "status": "done",
            "target_task_id": task_id.strip(),
        }
        actions.append(action_item)

        title_terms = _grounding_terms(title.strip().lower())
        overlap = title_terms.intersection(message_terms)
        if overlap:
            explicit_matches.append(action_item)

    if explicit_matches:
        return explicit_matches

    return actions


def _is_completion_request(message: str) -> bool:
    raw = (message or "").strip().lower()
    if not raw or is_query_like_text(raw):
        return False
    has_explicit_completion = any(_contains_word(raw, token) for token in COMPLETION_INTENT_TOKENS)
    if has_explicit_completion:
        return True
    if _contains_word(raw, "mark") and _contains_word(raw, "done"):
        return True
    # Soft completion statements like "I cleaned the keyboard already."
    if "took care of" in raw or "already" in raw:
        if raw.startswith("i ") or raw.startswith("i've ") or raw.startswith("i have "):
            words = re.findall(r"[a-zA-Z]{4,}", raw)
            if any(word.endswith("ed") for word in words):
                return True
    return False


def _has_term_overlap(title_terms: set[str], msg_terms: set[str]) -> bool:
    for m in msg_terms:
        if len(m) < 4:
            continue
        for t in title_terms:
            if len(t) < 4:
                continue
            if m == t or m.startswith(t) or t.startswith(m):
                return True
    return False


def _completion_candidate_rows(grounding: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(grounding, dict):
        return []
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("recent_task_refs", "tasks"):
        rows = grounding.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            task_id = row.get("id")
            title = row.get("title")
            if not isinstance(task_id, str) or not task_id.strip():
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            if task_id in seen:
                continue
            seen.add(task_id)
            out.append(
                {
                    "id": task_id.strip(),
                    "title": title.strip(),
                    "status": str(row.get("status") or "").strip().lower(),
                }
            )
    return out


def _resolve_completion_actions(message: str, grounding: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = (message or "").strip().lower()
    if not _is_completion_request(raw):
        return []
    rows = _completion_candidate_rows(grounding)
    if not rows:
        return []

    open_rows = [row for row in rows if row.get("status") in {"open", "blocked"}]
    if not open_rows:
        return []

    explicit_completion = any(
        token in raw
        for token in COMPLETION_INTENT_TOKENS
    )
    message_terms = _grounding_terms(raw)
    message_terms = {
        term
        for term in message_terms
        if term
        not in {
            "mark",
            "done",
            "complete",
            "completed",
            "close",
            "closed",
            "all",
            "those",
            "them",
            "that",
            "these",
            "this",
            "it",
            "assignments",
            "tasks",
            "ones",
            "now",
        }
    }

    explicit_rows: List[Dict[str, Any]] = []

    for row in open_rows:
        title_terms = _grounding_terms(row["title"].lower())
        if _has_term_overlap(title_terms, message_terms):
            explicit_rows.append(row)
    selected_rows = explicit_rows
    if not selected_rows:
        if not explicit_completion:
            # For soft "I already ...ed" statements, only explicit matches are safe.
            selected_rows = []
        else:
            has_global_scope = any(
                phrase in raw
                for phrase in (
                    "everything",
                    "all tasks",
                    "all my tasks",
                    "all of my tasks",
                    "all open tasks",
                )
            )
            has_reference = any(
                token in raw
                for token in ("those", "them", "that", "these", "this", "it", "assignments", "tasks", "ones")
            )
            if has_global_scope:
                selected_rows = open_rows
            elif has_reference:
                recent_rows = grounding.get("recent_task_refs") if isinstance(grounding, dict) else []
                recent_ids = {
                    row.get("id")
                    for row in recent_rows
                    if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
                }
                selected_rows = [row for row in open_rows if row["id"] in recent_ids] or open_rows
    actions: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in selected_rows:
        task_id = row.get("id")
        if task_id in seen:
            continue
        seen.add(task_id)
        actions.append(
            {
                "title": row["title"],
                "action": "complete",
                "status": "done",
                "target_task_id": task_id,
            }
        )
    return actions


def _sanitize_completion_extraction(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
    *,
    allow_heuristic_resolution: bool = True,
) -> Dict[str, Any]:
    if not _is_completion_request(message):
        return extraction if isinstance(extraction, dict) else {"tasks": [], "goals": [], "problems": [], "links": []}

    rows = _completion_candidate_rows(grounding)
    open_by_id: Dict[str, Dict[str, Any]] = {}
    open_by_title: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if row.get("status") not in {"open", "blocked"}:
            continue
        task_id = row["id"]
        open_by_id[task_id] = row
        open_by_title[row["title"].lower().strip()] = row

    sanitized_tasks: List[Dict[str, Any]] = []
    seen: set[str] = set()
    raw_tasks = extraction.get("tasks", []) if isinstance(extraction, dict) else []
    if isinstance(raw_tasks, list):
        for task in raw_tasks:
            if not isinstance(task, dict):
                continue
            action = str(task.get("action") or "").lower()
            status = str(task.get("status") or "").lower()
            if action not in {"complete", ""} and status != "done":
                continue
            candidate = None
            target_id = task.get("target_task_id")
            if isinstance(target_id, str) and target_id.strip():
                candidate = open_by_id.get(target_id.strip())
            if candidate is None:
                title = task.get("title")
                if isinstance(title, str) and title.strip():
                    candidate = open_by_title.get(title.strip().lower())
            if candidate is None:
                continue
            task_id = candidate["id"]
            if task_id in seen:
                continue
            seen.add(task_id)
            sanitized_tasks.append(
                {
                    "title": candidate["title"],
                    "action": "complete",
                    "status": "done",
                    "target_task_id": task_id,
                }
            )

    if allow_heuristic_resolution:
        resolved_tasks = _resolve_completion_actions(message, grounding)
        if not sanitized_tasks:
            sanitized_tasks = resolved_tasks
        elif resolved_tasks:
            sanitized_ids = {
                task.get("target_task_id")
                for task in sanitized_tasks
                if isinstance(task, dict) and isinstance(task.get("target_task_id"), str)
            }
            resolved_ids = {
                task.get("target_task_id")
                for task in resolved_tasks
                if isinstance(task, dict) and isinstance(task.get("target_task_id"), str)
            }
            if sanitized_ids and sanitized_ids.issubset(resolved_ids):
                sanitized_tasks = resolved_tasks

    return {"tasks": sanitized_tasks, "goals": [], "problems": [], "links": []}


def _is_create_request(message: str) -> bool:
    raw = (message or "").strip().lower()
    if not raw or is_query_like_text(raw):
        return False
    has_create_verb = any(token in raw for token in ("add ", "create ", "new task", "put "))
    has_task_noun = any(
        token in raw for token in ("to my list", "on my list", "task", "todo", "to-do", "to do", "add ", "create ")
    )
    return has_create_verb and has_task_noun


def _derive_create_action_from_message(message: str) -> Optional[Dict[str, Any]]:
    raw = (message or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    start_idx = -1
    keyword_len = 0
    add_idx = lowered.find("add ")
    create_idx = lowered.find("create ")
    if add_idx >= 0 and (create_idx < 0 or add_idx < create_idx):
        start_idx = add_idx
        keyword_len = 4
    elif create_idx >= 0:
        start_idx = create_idx
        keyword_len = 7
    phrase = raw[start_idx + keyword_len :].strip() if start_idx >= 0 else raw
    phrase = re.split(r"\bto my list\b|\bon my list\b|[.!?]", phrase, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    phrase = re.sub(r"^(a|an|the)\s+", "", phrase, flags=re.IGNORECASE).strip()
    if not phrase:
        return None
    title = phrase[0].upper() + phrase[1:] if len(phrase) > 1 else phrase.upper()
    return {"title": title, "action": "create"}


def _sanitize_create_extraction(
    message: str,
    extraction: Dict[str, Any],
    *,
    allow_heuristic_derivation: bool = True,
) -> Dict[str, Any]:
    if not _is_create_request(message):
        return extraction if isinstance(extraction, dict) else {"tasks": [], "goals": [], "problems": [], "links": []}

    msg_terms = _grounding_terms((message or "").lower())
    raw_tasks = extraction.get("tasks", []) if isinstance(extraction, dict) else []
    sanitized_tasks: List[Dict[str, Any]] = []
    if isinstance(raw_tasks, list):
        for task in raw_tasks:
            if not isinstance(task, dict):
                continue
            title = task.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            title_clean = title.strip()
            title_terms = _grounding_terms(title_clean.lower())
            if msg_terms and not _has_term_overlap(title_terms, msg_terms):
                continue
            item: Dict[str, Any] = {"title": title_clean, "action": "create"}
            if isinstance(task.get("notes"), str) and task.get("notes").strip():
                item["notes"] = task.get("notes").strip()
            for key in ("priority", "impact_score", "urgency_score", "due_date"):
                if task.get(key) is not None:
                    item[key] = task.get(key)
            sanitized_tasks.append(item)

    if not sanitized_tasks and allow_heuristic_derivation:
        derived = _derive_create_action_from_message(message)
        if derived:
            sanitized_tasks = [derived]
    return {"tasks": sanitized_tasks[:3], "goals": [], "problems": [], "links": []}


def _sanitize_targeted_task_actions(message: str, extraction: Dict[str, Any], grounding: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(extraction, dict):
        return {"tasks": [], "goals": [], "problems": [], "links": []}
    raw_tasks = extraction.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return extraction

    rows = _completion_candidate_rows(grounding)
    row_by_id: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        row_by_id[row["id"]] = row

    msg_lower = (message or "").lower()
    msg_terms = _grounding_terms(msg_lower)
    weak_terms = {"today", "tonight", "tomorrow", "night", "morning", "evening", "week", "month", "day"}
    msg_terms = {term for term in msg_terms if term not in weak_terms}
    has_reference_language = any(
        _contains_word(msg_lower, token) for token in ("that", "this", "it", "previous", "earlier", "above", "again")
    ) or "same task" in msg_lower or "same one" in msg_lower

    sanitized: List[Any] = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            sanitized.append(task)
            continue
        target_id = task.get("target_task_id")
        if not isinstance(target_id, str) or not target_id.strip():
            sanitized.append(task)
            continue

        target = row_by_id.get(target_id.strip())
        if not target:
            normalized = dict(task)
            normalized.pop("target_task_id", None)
            if normalized.get("action") in {"update", "noop"}:
                normalized["action"] = "create"
            sanitized.append(normalized)
            continue

        action = str(task.get("action") or "").lower()
        if action in {"complete", "archive"}:
            sanitized.append(task)
            continue

        candidate_title = str(target.get("title") or "")
        candidate_terms = _grounding_terms(candidate_title.lower())
        candidate_terms = {term for term in candidate_terms if term not in weak_terms}

        overlaps_target = _has_term_overlap(candidate_terms, msg_terms)

        if has_reference_language or overlaps_target:
            sanitized.append(task)
            continue

        normalized = dict(task)
        normalized.pop("target_task_id", None)
        normalized["action"] = "create"
        sanitized.append(normalized)

    out = dict(extraction)
    out["tasks"] = sanitized
    return out


def _planner_confidence(planned: Any) -> float:
    if not isinstance(planned, dict):
        return 0.0
    value = planned.get("confidence")
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _is_safe_completion_extraction(extraction: Dict[str, Any]) -> bool:
    tasks = extraction.get("tasks", []) if isinstance(extraction, dict) else []
    if not isinstance(tasks, list) or not tasks:
        return False
    if extraction.get("goals") or extraction.get("problems") or extraction.get("links"):
        return False
    for task in tasks:
        if not isinstance(task, dict):
            return False
        action = str(task.get("action") or "").lower()
        status = str(task.get("status") or "").lower()
        target_task_id = task.get("target_task_id")
        if action != "complete" and status != "done":
            return False
        if not isinstance(target_task_id, str) or not target_task_id.strip():
            return False
    return True


def _is_low_risk_action_extraction(extraction: Dict[str, Any]) -> bool:
    tasks = extraction.get("tasks", []) if isinstance(extraction, dict) else []
    if not isinstance(tasks, list) or not tasks:
        return False
    if extraction.get("goals") or extraction.get("problems") or extraction.get("links"):
        return False
    if len(tasks) > 2:
        return False
    for task in tasks:
        if not isinstance(task, dict):
            return False
        action = str(task.get("action") or "").lower()
        if action and action not in {"create", "noop"}:
            return False
    return True


def _unresolved_mutation_titles(extraction: Dict[str, Any]) -> List[str]:
    if not isinstance(extraction, dict):
        return []
    tasks = extraction.get("tasks", [])
    if not isinstance(tasks, list):
        return []
    unresolved: List[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        action = str(task.get("action") or "").lower()
        status = str(task.get("status") or "").lower()
        requires_target = action in {"update", "complete", "archive"} or status in {"done", "archived"}
        target_task_id = task.get("target_task_id")
        if not requires_target:
            continue
        if isinstance(target_task_id, str) and target_task_id.strip():
            continue
        title = task.get("title")
        if isinstance(title, str) and title.strip():
            unresolved.append(title.strip())
        else:
            unresolved.append("unnamed task")
    return unresolved


def _autopilot_decision(message: str, extraction: Dict[str, Any], planned: Any) -> tuple[bool, str]:
    if not _has_actionable_entities(extraction):
        return False, "no_actionable_entities"
    confidence = _planner_confidence(planned)
    completion_request = _is_completion_request(message)
    if completion_request and _is_safe_completion_extraction(extraction):
        if confidence >= AUTOPILOT_COMPLETION_CONFIDENCE:
            return True, "completion_high_confidence"
        return False, "completion_low_confidence"
    if not isinstance(planned, dict):
        return False, "no_planner_payload"
    if planned.get("needs_confirmation") is True:
        return False, "planner_requires_confirmation"
    if confidence < AUTOPILOT_ACTION_CONFIDENCE:
        return False, "action_low_confidence"
    if _is_low_risk_action_extraction(extraction):
        return True, "low_risk_action_high_confidence"
    return False, "not_low_risk_action"


def _build_low_confidence_clarification(extraction: Dict[str, Any]) -> str:
    tasks = extraction.get("tasks", []) if isinstance(extraction, dict) else []
    titles = [
        task.get("title", "").strip()
        for task in tasks
        if isinstance(task, dict) and isinstance(task.get("title"), str) and task.get("title").strip()
    ]
    if titles:
        preview = ", ".join(escape_html(t) for t in titles[:3])
        return (
            "I need one clarification before applying changes:\n"
            f"• I am not fully confident yet. Should I proceed with: {preview}?\n\n"
            "Reply yes to apply, or edit ... to revise."
        )
    return (
        "I need one clarification before applying changes:\n"
        "• I am not fully confident about the intended action.\n\n"
        "Reply with one more detail and I will revise."
    )


def _apply_intent_fallbacks(message: str, extraction: Dict[str, Any], grounding: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(extraction, dict):
        return {"tasks": [], "goals": [], "problems": [], "links": []}
    # Phase 16 policy: no heuristic guessing of actions from phrase patterns.
    # Fallback only normalizes shape; planner or extraction must provide actionable entities.
    extraction.setdefault("tasks", [])
    extraction.setdefault("goals", [])
    extraction.setdefault("problems", [])
    extraction.setdefault("links", [])
    return extraction


def _actions_to_extraction(actions: Any) -> Dict[str, Any]:
    extraction: Dict[str, Any] = {"tasks": [], "goals": [], "problems": [], "links": []}
    if not isinstance(actions, list):
        return extraction
    for action in actions:
        if not isinstance(action, dict):
            continue
        entity_type = action.get("entity_type")
        op = action.get("action")
        if entity_type == "task":
            title = action.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            task_item: Dict[str, Any] = {"title": title.strip()}
            if isinstance(op, str) and op in {"create", "update", "complete", "archive", "noop"}:
                task_item["action"] = op
                if op == "complete":
                    task_item["status"] = "done"
                elif op == "archive":
                    task_item["status"] = "archived"
            status = action.get("status")
            if isinstance(status, str) and status in {"open", "blocked", "done", "archived"}:
                task_item["status"] = status
            target_task_id = action.get("target_task_id")
            if isinstance(target_task_id, str) and target_task_id.strip():
                task_item["target_task_id"] = target_task_id.strip()
            priority = action.get("priority")
            if isinstance(priority, int) and 1 <= priority <= 4:
                task_item["priority"] = priority
            impact_score = action.get("impact_score")
            if isinstance(impact_score, int) and 1 <= impact_score <= 5:
                task_item["impact_score"] = impact_score
            urgency_score = action.get("urgency_score")
            if isinstance(urgency_score, int) and 1 <= urgency_score <= 5:
                task_item["urgency_score"] = urgency_score
            notes = action.get("notes")
            if isinstance(notes, str) and notes.strip():
                task_item["notes"] = notes.strip()
            due_date = action.get("due_date")
            if isinstance(due_date, str):
                try:
                    date.fromisoformat(due_date.strip()[:10])
                    task_item["due_date"] = due_date.strip()[:10]
                except ValueError:
                    pass
            extraction["tasks"].append(task_item)
        elif entity_type == "goal":
            title = action.get("title")
            if isinstance(title, str) and title.strip():
                extraction["goals"].append({"title": title.strip()})
        elif entity_type == "problem":
            title = action.get("title")
            if isinstance(title, str) and title.strip():
                extraction["problems"].append({"title": title.strip()})
        elif entity_type == "link":
            link = {
                "from_type": action.get("from_type"),
                "from_title": action.get("from_title"),
                "to_type": action.get("to_type"),
                "to_title": action.get("to_title"),
                "link_type": action.get("link_type"),
            }
            if all(isinstance(v, str) and v.strip() for v in link.values()):
                extraction["links"].append({k: v.strip() for k, v in link.items()})
    return extraction


async def _get_open_action_draft(user_id: str, chat_id: str, db: AsyncSession) -> Optional[ActionDraft]:
    now = _draft_now()
    expire_stmt = (
        update(ActionDraft)
        .where(
            ActionDraft.user_id == user_id,
            ActionDraft.chat_id == chat_id,
            ActionDraft.status == "draft",
            ActionDraft.expires_at < now,
        )
        .values(status="expired", updated_at=now)
    )
    await db.execute(expire_stmt)

    stmt = (
        select(ActionDraft)
        .where(
            ActionDraft.user_id == user_id,
            ActionDraft.chat_id == chat_id,
            ActionDraft.status == "draft",
            ActionDraft.expires_at >= now,
        )
        .order_by(ActionDraft.updated_at.desc())
        .limit(1)
    )
    draft = (await db.execute(stmt)).scalar_one_or_none()
    await db.commit()
    return draft


async def _create_action_draft(
    db: AsyncSession,
    user_id: str,
    chat_id: str,
    message: str,
    extraction: Dict[str, Any],
    request_id: str,
) -> ActionDraft:
    now = _draft_now()
    clear_stmt = (
        update(ActionDraft)
        .where(
            ActionDraft.user_id == user_id,
            ActionDraft.chat_id == chat_id,
            ActionDraft.status == "draft",
        )
        .values(status="discarded", updated_at=now)
    )
    await db.execute(clear_stmt)

    draft = ActionDraft(
        id=f"drf_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        chat_id=chat_id,
        source_message=message,
        proposal_json=extraction,
        status="draft",
        expires_at=now + timedelta(seconds=ACTION_DRAFT_TTL_SECONDS),
        created_at=now,
        updated_at=now,
    )
    _draft_set_awaiting_edit_input(draft, False)
    db.add(draft)
    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="action_draft_created",
            payload_json={"draft_id": draft.id, "chat_id": chat_id},
            created_at=utc_now(),
        )
    )
    await db.commit()
    return draft


async def _discard_action_draft(draft: ActionDraft, user_id: str, request_id: str, db: AsyncSession) -> None:
    draft.status = "discarded"
    draft.updated_at = _draft_now()
    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="action_draft_discarded",
            payload_json={"draft_id": draft.id},
            created_at=utc_now(),
        )
    )
    await db.commit()


async def _revise_action_draft(
    draft: ActionDraft, user_id: str, request_id: str, edit_text: str, db: AsyncSession
) -> Dict[str, Any]:
    revised_message = f"{draft.source_message}\n\nUser clarification: {edit_text}".strip()
    grounding = await _build_extraction_grounding(db=db, user_id=user_id, chat_id=draft.chat_id, message=revised_message)
    extraction = await adapter.extract_structured_updates(revised_message, grounding=grounding)
    extraction = _apply_intent_fallbacks(revised_message, extraction, grounding)
    extraction = _sanitize_completion_extraction(
        revised_message, extraction, grounding, allow_heuristic_resolution=False
    )
    extraction = _sanitize_create_extraction(revised_message, extraction)
    extraction = _sanitize_targeted_task_actions(revised_message, extraction, grounding)
    extraction = _resolve_relative_due_date_overrides(revised_message, extraction)
    _validate_extraction_payload(extraction)
    draft.source_message = revised_message
    draft.proposal_json = extraction
    _draft_set_awaiting_edit_input(draft, False)
    draft.updated_at = _draft_now()
    draft.expires_at = _draft_now() + timedelta(seconds=ACTION_DRAFT_TTL_SECONDS)
    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="action_draft_revised",
            payload_json={"draft_id": draft.id},
            created_at=utc_now(),
        )
    )
    await db.commit()
    return extraction


async def _confirm_action_draft(
    draft: ActionDraft, user_id: str, chat_id: str, request_id: str, db: AsyncSession
) -> AppliedChanges:
    extraction = draft.proposal_json if isinstance(draft.proposal_json, dict) else {}
    inbox_item_id, applied = await _apply_capture(
        db=db,
        user_id=user_id,
        chat_id=chat_id,
        source=settings.TELEGRAM_DEFAULT_SOURCE,
        message=draft.source_message,
        extraction=extraction,
        request_id=request_id,
        commit=False,
        enqueue_summary=False,
    )
    draft.status = "confirmed"
    draft.updated_at = _draft_now()
    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="action_draft_confirmed",
            payload_json={"draft_id": draft.id},
            created_at=utc_now(),
        )
    )
    await db.commit()
    summary_enqueued = True
    sync_enqueued = True
    summary_error: Optional[str] = None
    sync_error: Optional[str] = None
    try:
        await _enqueue_summary_job(user_id=user_id, chat_id=chat_id, inbox_item_id=inbox_item_id)
    except Exception as exc:
        summary_enqueued = False
        summary_error = str(exc)
        logger.error("Failed to enqueue memory summary for draft %s: %s", draft.id, exc)
    try:
        await _enqueue_todoist_sync_job(user_id=user_id)
    except Exception as exc:
        sync_enqueued = False
        sync_error = str(exc)
        logger.error("Failed to enqueue Todoist sync for draft %s: %s", draft.id, exc)

    if not summary_enqueued or not sync_enqueued:
        db.add(
            EventLog(
                id=str(uuid.uuid4()),
                request_id=request_id,
                user_id=user_id,
                event_type="action_apply_partial_enqueue_failure",
                payload_json={
                    "draft_id": draft.id,
                    "summary_enqueued": summary_enqueued,
                    "sync_enqueued": sync_enqueued,
                    "summary_error": summary_error,
                    "sync_error": sync_error,
                },
                created_at=utc_now(),
            )
        )
        await db.commit()
    return applied


def _grounding_terms(message: str) -> set[str]:
    import re
    terms = set(re.findall(r"[a-zA-Z0-9]{3,}", (message or "").lower()))
    return {t for t in terms if t not in {"the", "and", "for", "with", "that", "this", "from", "have", "need"}}


async def _build_extraction_grounding(db: AsyncSession, user_id: str, chat_id: str, message: str = "") -> Dict[str, Any]:
    task_rows = (
        await db.execute(
            select(Task)
            .where(Task.user_id == user_id, Task.status != TaskStatus.archived)
            .order_by(Task.updated_at.desc())
            .limit(80)
        )
    ).scalars().all()
    prepared = []
    terms = _grounding_terms(message)
    for idx, task in enumerate(task_rows):
        title_l = (task.title or "").lower()
        notes_l = (task.notes or "").lower()
        overlap = 0
        if terms:
            for term in terms:
                if term in title_l:
                    overlap += 3
                elif term in notes_l:
                    overlap += 1
        status = task.status.value if hasattr(task.status, "value") else str(task.status)
        status_boost = 2 if status == "open" else 0
        recency_boost = max(0, 10 - idx)
        score = overlap + status_boost + recency_boost
        prepared.append(
            (
                score,
                {
                    "id": task.id,
                    "title": task.title,
                    "status": status,
                    "priority": task.priority,
                    "impact_score": task.impact_score,
                    "urgency_score": task.urgency_score,
                    "notes": task.notes,
                    "due_date": task.due_date.isoformat() if task.due_date else None,
                },
            )
        )
    prepared.sort(key=lambda item: item[0], reverse=True)
    max_items = 12 if terms else 8
    tasks = [item[1] for item in prepared[:max_items]]
    recent_refs: List[Dict[str, Any]] = []
    now = utc_now()
    recent_stmt = (
        select(RecentContextItem)
        .where(
            RecentContextItem.user_id == user_id,
            RecentContextItem.chat_id == chat_id,
            RecentContextItem.entity_type == EntityType.task,
            RecentContextItem.expires_at >= now,
        )
        .order_by(RecentContextItem.surfaced_at.desc())
        .limit(24)
    )
    recent_rows = (await db.execute(recent_stmt)).scalars().all()
    recent_task_ids: List[str] = []
    seen: set[str] = set()
    for row in recent_rows:
        if row.entity_id not in seen:
            seen.add(row.entity_id)
            recent_task_ids.append(row.entity_id)
        if len(recent_task_ids) >= 8:
            break
    if recent_task_ids:
        recent_tasks_stmt = select(Task).where(Task.user_id == user_id, Task.id.in_(recent_task_ids))
        recent_tasks = (await db.execute(recent_tasks_stmt)).scalars().all()
        task_by_id = {task.id: task for task in recent_tasks}
        for task_id in recent_task_ids:
            task = task_by_id.get(task_id)
            if not task:
                continue
            status = task.status.value if hasattr(task.status, "value") else str(task.status)
            recent_refs.append({"id": task.id, "title": task.title, "status": status})

    return {
        "chat_id": chat_id,
        "current_date_utc": utc_now().date().isoformat(),
        "current_datetime_utc": utc_now().isoformat(),
        "current_date_local": _local_today().isoformat(),
        "current_datetime_local": _local_now().isoformat(),
        "timezone": settings.APP_TIMEZONE,
        "tasks": tasks,
        "recent_task_refs": recent_refs,
    }


async def _enqueue_summary_job(user_id: str, chat_id: str, inbox_item_id: str) -> None:
    job_payload = {
        "job_id": str(uuid.uuid4()),
        "topic": "memory.summarize",
        "payload": {"user_id": user_id, "chat_id": chat_id, "inbox_item_id": inbox_item_id},
    }
    await redis_client.rpush("default_queue", json.dumps(job_payload))


async def _enqueue_todoist_sync_job(user_id: str) -> None:
    sync_job_id = str(uuid.uuid4())
    await redis_client.rpush(
        "default_queue",
        json.dumps({"job_id": sync_job_id, "topic": "sync.todoist", "payload": {"user_id": user_id}}),
    )


async def _remember_recent_tasks(
    db: AsyncSession,
    user_id: str,
    chat_id: str,
    task_ids: List[str],
    reason: str,
    ttl_hours: int = 24,
) -> None:
    now = utc_now()
    expires_at = now + timedelta(hours=max(1, ttl_hours))
    unique_ids: List[str] = []
    seen: set[str] = set()
    for task_id in task_ids:
        if isinstance(task_id, str) and task_id and task_id not in seen:
            seen.add(task_id)
            unique_ids.append(task_id)
    if not unique_ids:
        return
    for task_id in unique_ids[:12]:
        db.add(
            RecentContextItem(
                id=f"rcx_{uuid.uuid4().hex[:12]}",
                user_id=user_id,
                chat_id=chat_id,
                entity_type=EntityType.task,
                entity_id=task_id,
                reason=reason,
                surfaced_at=now,
                expires_at=expires_at,
            )
        )


def _parse_due_date(value: Any) -> Optional[date]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _infer_urgency_score(due: Optional[date], priority: Optional[int]) -> Optional[int]:
    # Explicit urgency should win; this is fallback inference only.
    inferred: Optional[int] = None
    today = _local_today()
    if due is not None:
        days = (due - today).days
        if days <= 0:
            inferred = 5
        elif days <= 2:
            inferred = 4
        elif days <= 7:
            inferred = 3
        else:
            inferred = 2
    if priority is not None and 1 <= priority <= 4:
        priority_hint = {1: 4, 2: 3, 3: 2, 4: 1}[priority]
        inferred = max(inferred or 1, priority_hint)
    return inferred

async def _apply_capture(db: AsyncSession, user_id: str, chat_id: str, source: str,
                         message: str, extraction: dict, request_id: str,
                         client_msg_id: Optional[str] = None,
                         commit: bool = True,
                         enqueue_summary: bool = True) -> tuple:
    """Core capture pipeline used by both API and Telegram paths.
    Returns (inbox_item_id, applied: AppliedChanges)."""
    applied = AppliedChanges()
    inbox_item_id = f"inb_{uuid.uuid4().hex[:12]}"
    touched_task_ids: List[str] = []
    db.add(InboxItem(
        id=inbox_item_id, user_id=user_id, chat_id=chat_id, source=source,
        client_msg_id=client_msg_id, message_raw=message, message_norm=message.strip(),
        received_at=utc_now()
    ))

    entity_map = {}
    for t_data in extraction.get("tasks", []):
        title_norm = t_data["title"].lower().strip()
        action = str(t_data.get("action") or "").strip().lower()
        status_hint = str(t_data.get("status") or "").strip().lower()
        requires_target = action in {"update", "complete", "archive"} or status_hint in {"done", "archived"}
        existing = None
        target_task_id = t_data.get("target_task_id")
        if isinstance(target_task_id, str) and target_task_id.strip():
            target_stmt = select(Task).where(Task.user_id == user_id, Task.id == target_task_id.strip())
            existing = (await db.execute(target_stmt)).scalar_one_or_none()
        if existing is None and not requires_target and action != "create":
            stmt = select(Task).where(Task.user_id == user_id, Task.title_norm == title_norm, Task.status != TaskStatus.archived)
            existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            if action not in {"complete", "archive"}:
                existing.title = t_data["title"]
                existing.title_norm = title_norm
            if "priority" in t_data:
                existing.priority = t_data.get("priority")
            if "impact_score" in t_data:
                existing.impact_score = t_data.get("impact_score")
            if "urgency_score" in t_data:
                existing.urgency_score = t_data.get("urgency_score")
            if "notes" in t_data and isinstance(t_data.get("notes"), str):
                existing.notes = t_data.get("notes")
            if "due_date" in t_data:
                due_raw = t_data.get("due_date")
                if isinstance(due_raw, str) and due_raw.strip():
                    try:
                        existing.due_date = date.fromisoformat(due_raw.strip()[:10])
                    except ValueError:
                        pass
                elif due_raw is None:
                    existing.due_date = None
            if t_data.get("urgency_score") is None:
                existing.urgency_score = _infer_urgency_score(existing.due_date, existing.priority)
            if action == "archive":
                existing.status = TaskStatus.archived
                existing.archived_at = utc_now()
            elif action == "complete":
                existing.status = TaskStatus.done
                existing.completed_at = utc_now()
            elif "status" in t_data and t_data.get("status"):
                existing.status = t_data.get("status")
                status_value = t_data.get("status")
                if status_value == TaskStatus.done or status_value == "done":
                    existing.completed_at = utc_now()
                else:
                    existing.completed_at = None
            existing.updated_at = utc_now()
            entity_map[(EntityType.task, title_norm)] = existing.id
            touched_task_ids.append(existing.id)
            applied.tasks_updated += 1
        else:
            if requires_target or action in {"noop"}:
                db.add(
                    EventLog(
                        id=str(uuid.uuid4()),
                        request_id=request_id,
                        user_id=user_id,
                        event_type="task_action_skipped_missing_target",
                        payload_json={"title": t_data.get("title"), "action": action},
                        created_at=utc_now(),
                    )
                )
                continue
            task_id = f"tsk_{uuid.uuid4().hex[:12]}"
            db.add(Task(
                id=task_id, user_id=user_id, title=t_data["title"], title_norm=title_norm,
                status=t_data.get("status", TaskStatus.open), priority=t_data.get("priority"),
                impact_score=t_data.get("impact_score"),
                urgency_score=t_data.get("urgency_score")
                if isinstance(t_data.get("urgency_score"), int)
                else _infer_urgency_score(_parse_due_date(t_data.get("due_date")), t_data.get("priority")),
                notes=t_data.get("notes") if isinstance(t_data.get("notes"), str) else None,
                due_date=_parse_due_date(t_data.get("due_date")),
                source_inbox_item_id=inbox_item_id, created_at=utc_now(), updated_at=utc_now()
            ))
            entity_map[(EntityType.task, title_norm)] = task_id
            touched_task_ids.append(task_id)
            applied.tasks_created += 1

    for g_data in extraction.get("goals", []):
        title_norm = g_data["title"].lower().strip()
        stmt = select(Goal).where(Goal.user_id == user_id, Goal.title_norm == title_norm)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing: entity_map[(EntityType.goal, title_norm)] = existing.id
        else:
            goal_id = f"gol_{uuid.uuid4().hex[:12]}"
            db.add(Goal(id=goal_id, user_id=user_id, title=g_data["title"], title_norm=title_norm, created_at=utc_now(), updated_at=utc_now()))
            entity_map[(EntityType.goal, title_norm)] = goal_id
            applied.goals_created += 1

    for p_data in extraction.get("problems", []):
        title_norm = p_data["title"].lower().strip()
        stmt = select(Problem).where(Problem.user_id == user_id, Problem.title_norm == title_norm)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing: entity_map[(EntityType.problem, title_norm)] = existing.id
        else:
            prob_id = f"prb_{uuid.uuid4().hex[:12]}"
            db.add(Problem(id=prob_id, user_id=user_id, title=p_data["title"], title_norm=title_norm, created_at=utc_now(), updated_at=utc_now()))
            entity_map[(EntityType.problem, title_norm)] = prob_id
            applied.problems_created += 1

    for l_data in extraction.get("links", []):
        try:
            from_type = EntityType(l_data["from_type"])
            to_type = EntityType(l_data["to_type"])
            link_type = LinkType(l_data["link_type"])
            from_id = entity_map.get((from_type, l_data["from_title"].lower().strip()))
            to_id = entity_map.get((to_type, l_data["to_title"].lower().strip()))
            if from_id and to_id:
                db.add(EntityLink(id=f"lnk_{uuid.uuid4().hex[:12]}", user_id=user_id, from_entity_type=from_type, from_entity_id=from_id, to_entity_type=to_type, to_entity_id=to_id, link_type=link_type, created_at=utc_now()))
                applied.links_created += 1
        except Exception as e:
            db.add(EventLog(id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, event_type="link_validation_failed", payload_json={"entry": l_data, "error": str(e)}))

    await _remember_recent_tasks(
        db=db,
        user_id=user_id,
        chat_id=chat_id,
        task_ids=touched_task_ids,
        reason="capture_apply",
    )

    if commit:
        await db.commit()
    if enqueue_summary:
        await _enqueue_summary_job(user_id=user_id, chat_id=chat_id, inbox_item_id=inbox_item_id)
    return inbox_item_id, applied

# --- Internal Helpers for Integration Routing ---

async def handle_telegram_command(command: str, args: Optional[str], chat_id: str, user_id: str, db: AsyncSession):

    if command == "/today":
        # Simulate GET /v1/plan/get_today logic
        cache_key = f"plan:today:{user_id}:{chat_id}"
        cached = await redis_client.get(cache_key)
        if cached:
            payload = json.loads(cached)
        else:
            state = await collect_planning_state(db, user_id)
            payload = build_plan_payload(state, utc_now())
            payload = render_fallback_plan_explanation(payload)
        
        await send_message(chat_id, format_today_plan(payload))

    elif command == "/plan":
        job_id = str(uuid.uuid4())
        await redis_client.rpush("default_queue", json.dumps({"job_id": job_id, "topic": "plan.refresh", "payload": {"user_id": user_id, "chat_id": chat_id}}))
        await send_message(chat_id, format_plan_refresh_ack(job_id))

    elif command == "/focus":
        cache_key = f"plan:today:{user_id}:{chat_id}"
        cached = await redis_client.get(cache_key)
        if cached:
            payload = json.loads(cached)
        else:
            state = await collect_planning_state(db, user_id)
            payload = build_plan_payload(state, utc_now())
        
        await send_message(chat_id, format_focus_mode(payload))

    elif command == "/done":
        if not args:
            await send_message(chat_id, "Please provide a task ID. Example: <code>/done tsk_123</code>")
            return
        
        task_id = args.strip()
        stmt = update(Task).where(Task.id == task_id, Task.user_id == user_id).values(status=TaskStatus.done, completed_at=utc_now())
        res = await db.execute(stmt)
        if res.rowcount > 0:
            await db.commit()
            await send_message(chat_id, f"Task <code>{escape_html(task_id)}</code> marked as done.")
        else:
            await send_message(chat_id, f"Task <code>{escape_html(task_id)}</code> not found or not owned by you.")

    elif command == "/ask":
        question = (args or "").strip()
        if not question:
            await send_message(chat_id, "Please provide a question. Example: <code>/ask What tasks are overdue?</code>")
            return
        response = await query_ask(QueryAskRequest(chat_id=chat_id, query=question), user_id=user_id, db=db)
        await send_message(chat_id, format_query_answer(response.answer, response.follow_up_question))

    else:
        supported = "/today - Show today's plan\n/plan - Refresh plan\n/focus - Show top 3 tasks\n/done &lt;id&gt; - Mark task as done\n/ask &lt;question&gt; - Ask a read-only question"
        await send_message(chat_id, f"Unknown command. Supported:\n{supported}")


def _hash_link_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _build_telegram_deep_link(raw_token: str) -> Optional[str]:
    if settings.TELEGRAM_DEEP_LINK_BASE_URL:
        return f"{settings.TELEGRAM_DEEP_LINK_BASE_URL}{raw_token}"
    if settings.TELEGRAM_BOT_USERNAME:
        return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={raw_token}"
    return None


async def _issue_telegram_link_token(user_id: str, db: AsyncSession) -> TelegramLinkTokenCreateResponse:
    raw_token = secrets.token_urlsafe(24)
    if settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS <= 0:
        expires_at = utc_now() + timedelta(days=36500)
    else:
        expires_at = utc_now() + timedelta(seconds=settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS)
    record = TelegramLinkToken(
        id=f"tlt_{uuid.uuid4().hex[:12]}",
        token_hash=_hash_link_token(raw_token),
        user_id=user_id,
        expires_at=expires_at,
        consumed_at=None,
        created_at=utc_now(),
    )
    db.add(record)
    await db.commit()
    return TelegramLinkTokenCreateResponse(
        link_token=raw_token,
        expires_at=expires_at,
        deep_link=_build_telegram_deep_link(raw_token),
    )


async def _resolve_telegram_user(chat_id: str, db: AsyncSession) -> Optional[str]:
    stmt = select(TelegramUserMap).where(TelegramUserMap.chat_id == chat_id)
    mapping = (await db.execute(stmt)).scalar_one_or_none()
    if not mapping:
        return None
    mapping.last_seen_at = utc_now()
    await db.commit()
    return mapping.user_id


async def _consume_telegram_link_token(chat_id: str, username: Optional[str], raw_token: str, db: AsyncSession) -> bool:
    token_hash = _hash_link_token(raw_token.strip())
    stmt = select(TelegramLinkToken).where(TelegramLinkToken.token_hash == token_hash)
    token_row = (await db.execute(stmt)).scalar_one_or_none()
    if not token_row:
        return False
    if token_row.consumed_at is not None:
        return False
    expires_at = token_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS > 0 and expires_at < utc_now():
        return False

    mapping_stmt = select(TelegramUserMap).where(TelegramUserMap.chat_id == chat_id)
    mapping = (await db.execute(mapping_stmt)).scalar_one_or_none()
    now = utc_now()
    if mapping:
        mapping.user_id = token_row.user_id
        mapping.telegram_username = username
        mapping.linked_at = now
        mapping.last_seen_at = now
    else:
        db.add(
            TelegramUserMap(
                id=f"tgm_{uuid.uuid4().hex[:12]}",
                chat_id=chat_id,
                user_id=token_row.user_id,
                telegram_username=username,
                linked_at=now,
                last_seen_at=now,
            )
        )
    token_row.consumed_at = now
    await db.commit()
    return True

logger = logging.getLogger(__name__)
app = FastAPI(title="Todoist MCP API")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

# DB Setup
engine = create_async_engine(settings.DATABASE_URL, echo=settings.APP_ENV == "dev")
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Redis Setup
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
_preflight_lock = asyncio.Lock()
_preflight_cache: Dict[str, Any] = {"checked_at": None, "report": None}

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# --- Middleware & Dependencies ---

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

async def get_authenticated_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid authorization header")
    token = auth_header.split(" ")[1]
    token_map = settings.token_user_map
    if token_map:
        mapped_user = token_map.get(token)
        if mapped_user:
            return mapped_user
    if token not in settings.auth_tokens:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if token == "test_user_2":
        return "usr_2"
    return "usr_dev"

async def enforce_rate_limit(user_id: str, endpoint_class: str, limit: int):
    key = f"rate_limit:{endpoint_class}:{user_id}"
    current = await redis_client.incr(key)
    if current == 1:
        await redis_client.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS)
    if current > limit:
        ttl = await redis_client.ttl(key)
        if ttl is None or ttl < 0:
            ttl = settings.RATE_LIMIT_WINDOW_SECONDS
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {endpoint_class}. Retry in {ttl}s.",
        )

def _extract_usage(metadata: Any) -> Dict[str, int]:
    if not isinstance(metadata, dict):
        return {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
    usage = metadata.get("usage", metadata)
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
    return {
        "input_tokens": usage.get("input_tokens", 0) if isinstance(usage.get("input_tokens", 0), int) else 0,
        "output_tokens": usage.get("output_tokens", 0) if isinstance(usage.get("output_tokens", 0), int) else 0,
        "cached_input_tokens": usage.get("cached_input_tokens", 0) if isinstance(usage.get("cached_input_tokens", 0), int) else 0,
    }


def _validate_extraction_payload(extraction: Any) -> None:
    if not isinstance(extraction, dict):
        raise ValueError("Invalid extraction payload type")

    required = ("tasks", "goals", "problems", "links")
    for key in required:
        value = extraction.get(key)
        if not isinstance(value, list):
            raise ValueError(f"Invalid extraction list for key: {key}")

    for task in extraction["tasks"]:
        if not isinstance(task, dict):
            raise ValueError("Invalid task entry type")
        if not isinstance(task.get("title"), str) or not task.get("title").strip():
            raise ValueError("Invalid task title")
        action = task.get("action")
        if action is not None and action not in {"create", "update", "complete", "archive", "noop"}:
            raise ValueError("Invalid task action")
        if "target_task_id" in task and task.get("target_task_id") is not None and not isinstance(task.get("target_task_id"), str):
            raise ValueError("Invalid target_task_id")
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
            if _parse_due_date(due_raw) is None:
                raise ValueError("Invalid task due_date format")

    for goal in extraction["goals"]:
        if not isinstance(goal, dict):
            raise ValueError("Invalid goal entry type")
        if not isinstance(goal.get("title"), str) or not goal.get("title").strip():
            raise ValueError("Invalid goal title")

    for problem in extraction["problems"]:
        if not isinstance(problem, dict):
            raise ValueError("Invalid problem entry type")
        if not isinstance(problem.get("title"), str) or not problem.get("title").strip():
            raise ValueError("Invalid problem title")

    link_keys = ("from_type", "from_title", "to_type", "to_title", "link_type")
    for link in extraction["links"]:
        if not isinstance(link, dict):
            raise ValueError("Invalid link entry type")
        for key in link_keys:
            if not isinstance(link.get(key), str) or not link.get(key).strip():
                raise ValueError(f"Invalid link field: {key}")

async def check_idempotency(request: Request, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if request.method not in ["POST", "PATCH", "PUT", "DELETE"]:
        return
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Idempotency-Key header")
    
    body = await request.body()
    identity_string = f"{request.method}|{request.url.path}|{user_id}|{body.decode('utf-8', errors='ignore')}"
    body_hash = hashlib.sha256(identity_string.encode("utf-8")).hexdigest()
    
    stmt = select(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.idempotency_key == idempotency_key)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        if existing.request_hash != body_hash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key collision")
        request.state.idempotent_response = existing.response_body
    
    request.state.idempotency_key = idempotency_key
    request.state.request_hash = body_hash

async def save_idempotency(user_id: str, idempotency_key: str, request_hash: str, status_code: int, response_body: dict):
    async with AsyncSessionLocal() as db:
        ik = IdempotencyKey(
            id=str(uuid.uuid4()), user_id=user_id, idempotency_key=idempotency_key,
            request_hash=request_hash, response_status=status_code, response_body=response_body,
            created_at=utc_now(), expires_at=utc_now() + timedelta(hours=settings.IDEMPOTENCY_TTL_HOURS)
        )
        db.add(ik)
        await db.commit()

# --- Health Endpoints ---

def _external_preflight_required() -> bool:
    return settings.APP_ENV.strip().lower() in {"staging", "prod", "production"}


def _http_ok_status(code: int) -> bool:
    return 200 <= code < 300


async def _check_llm_credentials() -> Dict[str, Any]:
    base = (settings.LLM_API_BASE_URL or "").strip().rstrip("/")
    api_key = (settings.LLM_API_KEY or "").strip()
    if not base:
        return {"ok": False, "reason": "llm_base_url_missing"}
    if not api_key:
        return {"ok": False, "reason": "llm_api_key_missing"}
    try:
        async with httpx.AsyncClient(timeout=settings.PREFLIGHT_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if _http_ok_status(response.status_code):
            return {"ok": True}
        if response.status_code in {401, 403}:
            return {"ok": False, "reason": "llm_auth_failed"}
        return {"ok": False, "reason": f"llm_http_{response.status_code}"}
    except httpx.HTTPError:
        return {"ok": False, "reason": "llm_unreachable"}


async def _check_telegram_credentials() -> Dict[str, Any]:
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        return {"ok": True, "skipped": True, "reason": "telegram_token_not_configured"}
    base = (settings.TELEGRAM_API_BASE or "https://api.telegram.org").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=settings.PREFLIGHT_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{base}/bot{token}/getMe")
        if not _http_ok_status(response.status_code):
            if response.status_code in {401, 403}:
                return {"ok": False, "reason": "telegram_auth_failed"}
            return {"ok": False, "reason": f"telegram_http_{response.status_code}"}
        payload = response.json() if response.content else {}
        if isinstance(payload, dict) and payload.get("ok") is True:
            return {"ok": True}
        return {"ok": False, "reason": "telegram_auth_failed"}
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "reason": "telegram_unreachable"}


async def _compute_preflight_report() -> Dict[str, Any]:
    llm = await _check_llm_credentials()
    telegram = await _check_telegram_credentials()
    checks = {"llm": llm, "telegram": telegram}
    return {
        "ok": all(isinstance(item, dict) and item.get("ok") is True for item in checks.values()),
        "checks": checks,
        "checked_at": utc_now().isoformat(),
    }


async def _get_preflight_report(force: bool = False) -> Dict[str, Any]:
    now = utc_now()
    async with _preflight_lock:
        checked_at = _preflight_cache.get("checked_at")
        cached = _preflight_cache.get("report")
        fresh = (
            isinstance(checked_at, datetime)
            and isinstance(cached, dict)
            and (now - checked_at).total_seconds() < max(1, settings.PREFLIGHT_CACHE_SECONDS)
        )
        if not force and fresh:
            return cached
        report = await _compute_preflight_report()
        _preflight_cache["checked_at"] = now
        _preflight_cache["report"] = report
        return report


@app.get("/health/live")
async def health_live():
    return {"status": "ok"}

@app.get("/health/ready")
async def health_ready(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        await redis_client.ping()
    except Exception:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Infrastructure unreachable")
    if _external_preflight_required():
        report = await _get_preflight_report()
        if not report.get("ok"):
            failing = [
                name
                for name, item in (report.get("checks") or {}).items()
                if not (isinstance(item, dict) and item.get("ok") is True)
            ]
            fail_key = failing[0] if failing else "unknown"
            reason = ((report.get("checks") or {}).get(fail_key) or {}).get("reason", "preflight_failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Preflight failed: {fail_key}:{reason}",
            )
    return {"status": "ready"}


@app.get("/health/preflight")
async def health_preflight():
    if not _external_preflight_required():
        return {"status": "skipped", "reason": "preflight_not_required_in_env", "env": settings.APP_ENV}
    report = await _get_preflight_report()
    return {
        "status": "ok" if report.get("ok") else "failed",
        "checked_at": report.get("checked_at"),
        "checks": report.get("checks", {}),
    }

@app.get("/health/metrics", dependencies=[Depends(get_authenticated_user)])
async def health_metrics(db: AsyncSession = Depends(get_db)):
    window_hours = settings.OPERATIONS_METRICS_WINDOW_HOURS
    window_cutoff = utc_now() - timedelta(hours=window_hours)

    queue_depth = {
        "default_queue": await redis_client.llen("default_queue"),
        "dead_letter_queue": await redis_client.llen("dead_letter_queue"),
    }

    failure_events = (await db.execute(
        select(EventLog).where(
            EventLog.created_at >= window_cutoff,
            EventLog.event_type.in_(["worker_retry_scheduled", "worker_moved_to_dlq"])
        )
    )).scalars().all()

    retry_count = 0
    dlq_count = 0
    for event in failure_events:
        if event.event_type == "worker_retry_scheduled":
            retry_count += 1
        elif event.event_type == "worker_moved_to_dlq":
            dlq_count += 1

    tracked_topics = ("memory.summarize", "plan.refresh", "sync.todoist")
    last_success_by_topic: Dict[str, Optional[str]] = {topic: None for topic in tracked_topics}
    completed_events = (await db.execute(
        select(EventLog).where(
            EventLog.event_type == "worker_topic_completed"
        ).order_by(EventLog.created_at.desc()).limit(1000)
    )).scalars().all()
    for event in completed_events:
        payload = event.payload_json or {}
        topic = payload.get("topic")
        if topic not in last_success_by_topic or last_success_by_topic[topic] is not None:
            continue
        if event.created_at:
            last_success_by_topic[topic] = event.created_at.isoformat()
        if all(last_success_by_topic.values()):
            break

    total_failures = retry_count + dlq_count
    return {
        "window_hours": window_hours,
        "window_started_at": window_cutoff.isoformat(),
        "queue_depth": queue_depth,
        "failure_counters": {
            "retry_scheduled": retry_count,
            "moved_to_dlq": dlq_count,
            "total": total_failures,
            "alert_threshold": settings.WORKER_ALERT_FAILURE_THRESHOLD,
            "alert_triggered": total_failures >= settings.WORKER_ALERT_FAILURE_THRESHOLD,
        },
        "last_success_by_topic": last_success_by_topic,
    }

@app.get("/health/costs/daily", dependencies=[Depends(get_authenticated_user)])
async def health_costs_daily(user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    day_start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    rows = (await db.execute(
        select(PromptRun).where(
            PromptRun.user_id == user_id,
            PromptRun.created_at >= day_start,
            PromptRun.created_at < day_end
        )
    )).scalars().all()

    total_input_tokens = 0
    total_output_tokens = 0
    total_cached_input_tokens = 0
    by_operation_model: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        input_tokens = row.input_tokens or 0
        output_tokens = row.output_tokens or 0
        cached_input_tokens = row.cached_input_tokens or 0
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        total_cached_input_tokens += cached_input_tokens
        key = f"{row.operation}|{row.model}"
        entry = by_operation_model.setdefault(
            key,
            {
                "operation": row.operation,
                "model": row.model,
                "runs": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
            },
        )
        entry["runs"] += 1
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["cached_input_tokens"] += cached_input_tokens

    def _estimate(input_t: int, output_t: int, cached_t: int) -> float:
        usd = (
            ((input_t - cached_t) / 1_000_000.0) * settings.COST_INPUT_PER_MILLION_USD
            + (cached_t / 1_000_000.0) * settings.COST_CACHED_INPUT_PER_MILLION_USD
            + (output_t / 1_000_000.0) * settings.COST_OUTPUT_PER_MILLION_USD
        )
        return round(max(usd, 0.0), 8)

    breakdown = []
    for entry in by_operation_model.values():
        entry["estimated_usd"] = _estimate(
            entry["input_tokens"],
            entry["output_tokens"],
            entry["cached_input_tokens"],
        )
        breakdown.append(entry)
    breakdown.sort(key=lambda item: (item["operation"], item["model"]))

    return {
        "day_utc": day_start.date().isoformat(),
        "totals": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cached_input_tokens": total_cached_input_tokens,
            "estimated_usd": _estimate(total_input_tokens, total_output_tokens, total_cached_input_tokens),
        },
        "breakdown": breakdown,
    }

# --- Telegram Integration ---


async def _handle_telegram_callback_update(data: Dict[str, Any], db: AsyncSession) -> None:
    chat_id = data["chat_id"]
    callback_query_id = data.get("callback_query_id")
    callback_data = data.get("callback_data", "")
    request_id = f"tg_{uuid.uuid4().hex[:8]}"

    user_id = await _resolve_telegram_user(chat_id, db)
    if not user_id:
        if callback_query_id:
            await answer_callback_query(callback_query_id, "Chat is not linked.")
        return

    open_draft = await _get_open_action_draft(user_id=user_id, chat_id=chat_id, db=db)
    action, draft_id = _parse_draft_callback(callback_data)
    if callback_query_id:
        await answer_callback_query(callback_query_id)
    if not open_draft or not action or draft_id != open_draft.id:
        await send_message(chat_id, "This proposal is no longer active. Send a new message to continue.")
        return

    if action == "confirm":
        applied = await _confirm_action_draft(
            draft=open_draft, user_id=user_id, chat_id=chat_id, request_id=request_id, db=db
        )
        await send_message(chat_id, "✅ Applied. " + format_capture_ack(applied.model_dump()))
    elif action == "discard":
        await _discard_action_draft(open_draft, user_id=user_id, request_id=request_id, db=db)
        await send_message(chat_id, "Discarded the pending proposal.")
    elif action == "edit":
        _draft_set_awaiting_edit_input(open_draft, True)
        open_draft.updated_at = _draft_now()
        open_draft.expires_at = _draft_now() + timedelta(seconds=ACTION_DRAFT_TTL_SECONDS)
        await db.commit()
        await send_message(chat_id, "Reply with your changes in one message, and I will revise the proposal.")


async def _handle_telegram_draft_flow(
    chat_id: str,
    text: str,
    client_msg_id: Optional[str],
    user_id: str,
    db: AsyncSession,
) -> None:
    request_id = f"tg_{uuid.uuid4().hex[:8]}"
    open_draft = await _get_open_action_draft(user_id=user_id, chat_id=chat_id, db=db)
    draft_action, draft_arg = _parse_draft_reply(text)
    awaiting_edit_input = bool(open_draft and _draft_is_awaiting_edit_input(open_draft))

    if open_draft and draft_action == "confirm":
        applied = await _confirm_action_draft(
            draft=open_draft, user_id=user_id, chat_id=chat_id, request_id=request_id, db=db
        )
        await send_message(chat_id, "✅ Applied. " + format_capture_ack(applied.model_dump()))
        return
    if open_draft and draft_action == "discard":
        await _discard_action_draft(open_draft, user_id=user_id, request_id=request_id, db=db)
        await send_message(chat_id, "Discarded the pending proposal.")
        return
    if open_draft and draft_action == "edit":
        if not draft_arg:
            _draft_set_awaiting_edit_input(open_draft, True)
            open_draft.updated_at = _draft_now()
            open_draft.expires_at = _draft_now() + timedelta(seconds=ACTION_DRAFT_TTL_SECONDS)
            await db.commit()
            await send_message(chat_id, "Reply with your changes in one message, and I will revise the proposal.")
            return
        extraction = await _revise_action_draft(
            draft=open_draft, user_id=user_id, request_id=request_id, edit_text=draft_arg, db=db
        )
        await _send_or_edit_draft_preview(chat_id, open_draft, _format_action_draft_preview(extraction))
        await db.commit()
        return
    if open_draft and awaiting_edit_input and draft_action is None and not is_query_like_text(text):
        extraction = await _revise_action_draft(
            draft=open_draft, user_id=user_id, request_id=request_id, edit_text=text, db=db
        )
        await _send_or_edit_draft_preview(chat_id, open_draft, _format_action_draft_preview(extraction))
        await db.commit()
        return
    if open_draft and draft_action is None and not is_query_like_text(text):
        await send_message(chat_id, "You already have a pending proposal. Reply <code>yes</code>, <code>edit ...</code>, or <code>no</code>.")
        return

    grounding = await _build_extraction_grounding(db=db, user_id=user_id, chat_id=chat_id, message=text)
    planned = await adapter.plan_actions(text, context={"grounding": grounding, "chat_id": chat_id})
    intent = planned.get("intent") if isinstance(planned, dict) else None
    actions = planned.get("actions") if isinstance(planned, dict) else None

    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="telegram_action_planned",
            payload_json={
                "chat_id": chat_id,
                "intent": intent,
                "confidence": planned.get("confidence") if isinstance(planned, dict) else None,
                "scope": planned.get("scope") if isinstance(planned, dict) else None,
                "actions_count": len(actions) if isinstance(actions, list) else 0,
            },
            created_at=utc_now(),
        )
    )
    await db.commit()

    if intent == "query":
        response = await query_ask(QueryAskRequest(chat_id=chat_id, query=text), user_id=user_id, db=db)
        discussed_task_ids = [
            row.get("id")
            for row in (grounding.get("tasks") if isinstance(grounding, dict) else [])
            if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
        ]
        await _remember_recent_tasks(
            db=db,
            user_id=user_id,
            chat_id=chat_id,
            task_ids=discussed_task_ids[:6],
            reason="query_context",
            ttl_hours=12,
        )
        await db.commit()
        await send_message(chat_id, format_query_answer(response.answer, response.follow_up_question))
        return

    planner_actions_valid = intent == "action" and isinstance(actions, list) and len(actions) > 0
    used_extract_fallback = False
    if planner_actions_valid:
        extraction = _actions_to_extraction(actions)
        if not _has_actionable_entities(extraction):
            used_extract_fallback = True
            db.add(
                EventLog(
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    event_type="action_fallback_heuristic_used",
                    payload_json={"chat_id": chat_id, "reason": "planner_actions_unusable"},
                    created_at=utc_now(),
                )
            )
            await db.commit()
            extraction = await adapter.extract_structured_updates(text, grounding=grounding)
    else:
        used_extract_fallback = True
        db.add(
            EventLog(
                id=str(uuid.uuid4()),
                request_id=request_id,
                user_id=user_id,
                event_type="action_fallback_heuristic_used",
                payload_json={"chat_id": chat_id, "reason": "planner_invalid_or_empty"},
                created_at=utc_now(),
            )
        )
        await db.commit()
        extraction = await adapter.extract_structured_updates(text, grounding=grounding)

    critic = await adapter.critique_actions(
        text,
        context={"grounding": grounding, "chat_id": chat_id},
        proposal={"intent": intent, "actions": actions},
    )
    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="telegram_action_critic_result",
            payload_json={
                "chat_id": chat_id,
                "approved": critic.get("approved"),
                "issues": critic.get("issues"),
            },
            created_at=utc_now(),
        )
    )
    await db.commit()

    revised_actions = critic.get("revised_actions") if isinstance(critic, dict) else None
    if isinstance(revised_actions, list):
        revised_extraction = _actions_to_extraction(revised_actions)
        if _has_actionable_entities(revised_extraction):
            extraction = revised_extraction
        else:
            db.add(
                EventLog(
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    event_type="action_fallback_heuristic_used",
                    payload_json={"chat_id": chat_id, "reason": "critic_revised_actions_unusable"},
                    created_at=utc_now(),
                )
            )
            await db.commit()
    completion_request = _is_completion_request(text)
    if isinstance(critic, dict) and critic.get("approved") is False and not completion_request:
        issues = critic.get("issues") if isinstance(critic.get("issues"), list) else []
        issue_text = "\n".join([f"• {escape_html(str(i))}" for i in issues[:3]]) if issues else "• Proposal needs clarification."
        await send_message(
            chat_id,
            "I need one clarification before applying changes:\n"
            f"{issue_text}\n\n"
            "Reply with more detail, and I will revise the proposal.",
        )
        return

    if used_extract_fallback:
        extraction = _apply_intent_fallbacks(text, extraction, grounding)
    extraction = _sanitize_completion_extraction(
        text,
        extraction,
        grounding,
        allow_heuristic_resolution=False,
    )
    extraction = _sanitize_create_extraction(
        message=text,
        extraction=extraction,
        allow_heuristic_derivation=used_extract_fallback,
    )
    extraction = _sanitize_targeted_task_actions(text, extraction, grounding)
    extraction = _resolve_relative_due_date_overrides(text, extraction)
    unresolved_mutations = _unresolved_mutation_titles(extraction)
    if unresolved_mutations:
        unresolved_preview = ", ".join(escape_html(t) for t in unresolved_mutations[:3])
        await send_message(
            chat_id,
            "I need one clarification before applying changes:\n"
            f"• Which existing task should I update for: {unresolved_preview}?\n\n"
            "Reply with the task id, or ask me to list open tasks.",
        )
        return
    if not _has_actionable_entities(extraction):
        if completion_request:
            await send_message(
                chat_id,
                "I could not find open matching tasks to complete. They may already be done.\n"
                "Ask me to list open tasks, then try again.",
            )
            return
        if used_extract_fallback:
            db.add(
                EventLog(
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    event_type="action_fallback_heuristic_used",
                    payload_json={"chat_id": chat_id, "reason": "planner_and_extract_empty"},
                    created_at=utc_now(),
                )
            )
            await db.commit()
        await send_message(
            chat_id,
            "I did not find clear actions to apply yet.\n"
            "Reply with more details, or ask a question directly.",
        )
        return

    _validate_extraction_payload(extraction)
    planner_confidence = _planner_confidence(planned)
    if planner_confidence < CLARIFY_ACTION_CONFIDENCE:
        await send_message(chat_id, _build_low_confidence_clarification(extraction))
        return
    auto_apply, auto_reason = _autopilot_decision(text, extraction, planned)
    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="telegram_autopilot_decision",
            payload_json={
                "chat_id": chat_id,
                "auto_apply": auto_apply,
                "reason": auto_reason,
                "confidence": planner_confidence,
            },
            created_at=utc_now(),
        )
    )
    await db.commit()
    if auto_apply:
        _, applied = await _apply_capture(
            db=db,
            user_id=user_id,
            chat_id=chat_id,
            source=settings.TELEGRAM_DEFAULT_SOURCE,
            message=text,
            extraction=extraction,
            request_id=request_id,
            client_msg_id=client_msg_id,
            commit=True,
            enqueue_summary=True,
        )
        try:
            await _enqueue_todoist_sync_job(user_id=user_id)
        except Exception as exc:
            logger.error("Failed to enqueue todoist sync after autopilot apply: %s", exc)
        await send_message(chat_id, "✅ Applied automatically. " + format_capture_ack(applied.model_dump()))
        return

    draft = await _create_action_draft(
        db=db,
        user_id=user_id,
        chat_id=chat_id,
        message=text,
        extraction=extraction,
        request_id=request_id,
    )
    await _send_or_edit_draft_preview(chat_id, draft, _format_action_draft_preview(extraction))
    await db.commit()


async def _handle_telegram_message_update(data: Dict[str, Any], db: AsyncSession) -> None:
    chat_id = data["chat_id"]
    text = data.get("text", "")
    username = data.get("username")
    client_msg_id = data.get("client_msg_id")

    command, args = extract_command(text)
    if command:
        if command == "/start":
            if args and await _consume_telegram_link_token(chat_id, username, args, db):
                await send_message(chat_id, "Telegram linked successfully. You can now send thoughts and commands.")
            else:
                await send_message(chat_id, "Link failed. Request a new link token from the API and try again.")
            return

        user_id = await _resolve_telegram_user(chat_id, db)
        if not user_id:
            await send_message(chat_id, "This chat is not linked yet. Use /start <token> from your generated link token.")
            return
        await handle_telegram_command(command, args, chat_id, user_id, db)
        return

    user_id = await _resolve_telegram_user(chat_id, db)
    if not user_id:
        await send_message(chat_id, "This chat is not linked yet. Use /start <token> from your generated link token.")
        return
    await _handle_telegram_draft_flow(chat_id=chat_id, text=text, client_msg_id=client_msg_id, user_id=user_id, db=db)

@app.post("/v1/integrations/telegram/link_token", response_model=TelegramLinkTokenCreateResponse)
async def create_telegram_link_token(
    user_id: str = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    return await _issue_telegram_link_token(user_id, db)


@app.post("/v1/integrations/telegram/webhook", response_model=TelegramWebhookResponse)
async def telegram_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    # 1. Validate secret
    if not verify_telegram_secret(request.headers):
        raise HTTPException(status_code=403, detail="Unauthorized webhook source")
    
    # 2. Parse update
    try:
        update_json = await request.json()
    except Exception:
        return {"status": "ignored"}
        
    data = parse_update(update_json)
    if not data:
        return {"status": "ignored"}
    
    chat_id = data["chat_id"]
    text = data.get("text", "")
    username = data.get("username")
    client_msg_id = data.get("client_msg_id")
    update_kind = data.get("kind")
    if not _is_telegram_sender_allowed(chat_id, username):
        logger.warning("Ignoring telegram message from disallowed sender chat_id=%s username=%s", chat_id, username)
        return {"status": "ignored"}

    try:
        if update_kind == "callback":
            await _handle_telegram_callback_update(data, db)
        else:
            await _handle_telegram_message_update(data, db)
    except Exception as e:
        logger.error(f"Telegram routing failed: {e}")
        await send_message(chat_id, "Sorry, I had trouble processing that message. Please try again later.")

    return {"status": "ok"}

# --- Capture Endpoints ---

@app.post("/v1/capture/thought", response_model=ThoughtCaptureResponse, dependencies=[Depends(check_idempotency)])
async def capture_thought(request: Request, payload: ThoughtCaptureRequest, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    await enforce_rate_limit(user_id, "capture", settings.RATE_LIMIT_CAPTURE_PER_WINDOW)
    request_id = request.state.request_id
    
    extraction = None
    for attempt_num in range(1, 3):
        start_time = time.time()
        try:
            grounding = await _build_extraction_grounding(db=db, user_id=user_id, chat_id=payload.chat_id, message=payload.message)
            extraction = await adapter.extract_structured_updates(payload.message, grounding=grounding)
            extraction = _apply_intent_fallbacks(payload.message, extraction, grounding)
            extraction = _sanitize_completion_extraction(
                payload.message, extraction, grounding, allow_heuristic_resolution=False
            )
            extraction = _sanitize_create_extraction(payload.message, extraction)
            extraction = _sanitize_targeted_task_actions(payload.message, extraction, grounding)
            extraction = _resolve_relative_due_date_overrides(payload.message, extraction)
            usage = _extract_usage(extraction)
            latency = int((time.time() - start_time) * 1000)
            _validate_extraction_payload(extraction)
            db.add(PromptRun(
                id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, operation="extract",
                provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_EXTRACT,
                prompt_version=settings.PROMPT_VERSION_EXTRACT, latency_ms=latency, status="success",
                input_tokens=usage["input_tokens"], cached_input_tokens=usage["cached_input_tokens"],
                output_tokens=usage["output_tokens"],
                created_at=utc_now()
            ))
            break
        except Exception as e:
            db.add(PromptRun(
                id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, operation="extract",
                provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_EXTRACT,
                prompt_version=settings.PROMPT_VERSION_EXTRACT, status="error", error_code=type(e).__name__, created_at=utc_now()
            ))
            if attempt_num == 2:
                await db.commit()
                raise HTTPException(status_code=422, detail="Extraction failed after retries")

    inbox_item_id, applied = await _apply_capture(
        db=db, user_id=user_id, chat_id=payload.chat_id, source=payload.source,
        message=payload.message, extraction=extraction, request_id=request_id,
        client_msg_id=payload.client_msg_id
    )
    resp = ThoughtCaptureResponse(status="ok", inbox_item_id=inbox_item_id, applied=applied, summary_refresh_enqueued=True)
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp.model_dump())
    return resp

# --- Entity CRUD ---

@app.get("/v1/tasks")
async def list_tasks(status: Optional[TaskStatus] = None, goal_id: Optional[str] = None, cursor: Optional[str] = None, limit: int = 50, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    query = select(Task).where(Task.user_id == user_id).order_by(Task.id).limit(min(limit, 200))
    if status: query = query.where(Task.status == status)
    if goal_id:
        query = query.join(EntityLink, (EntityLink.from_entity_id == Task.id) & (EntityLink.from_entity_type == EntityType.task))
        query = query.where(EntityLink.to_entity_id == goal_id, EntityLink.to_entity_type == EntityType.goal)
    if cursor: query = query.where(Task.id > cursor)
    return (await db.execute(query)).scalars().all()

@app.patch("/v1/tasks/{task_id}", dependencies=[Depends(check_idempotency)])
async def update_task(request: Request, task_id: str, payload: TaskUpdate, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data: raise HTTPException(status_code=400, detail="No fields to update")
    if "status" in update_data: update_data["completed_at"] = utc_now() if update_data["status"] == TaskStatus.done else None
    stmt = update(Task).where(Task.id == task_id, Task.user_id == user_id).values(**update_data)
    if (await db.execute(stmt)).rowcount == 0: raise HTTPException(status_code=404, detail="Task not found")
    await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.get("/v1/problems")
async def list_problems(user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Problem).where(Problem.user_id == user_id))).scalars().all()

@app.patch("/v1/problems/{problem_id}", dependencies=[Depends(check_idempotency)])
async def update_problem(request: Request, problem_id: str, payload: ProblemUpdate, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    stmt = update(Problem).where(Problem.id == problem_id, Problem.user_id == user_id).values(**payload.model_dump(exclude_unset=True))
    if (await db.execute(stmt)).rowcount == 0: raise HTTPException(status_code=404, detail="Problem not found")
    await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.get("/v1/goals")
async def list_goals(user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Goal).where(Goal.user_id == user_id))).scalars().all()

@app.patch("/v1/goals/{goal_id}", dependencies=[Depends(check_idempotency)])
async def update_goal(request: Request, goal_id: str, payload: GoalUpdate, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    stmt = update(Goal).where(Goal.id == goal_id, Goal.user_id == user_id).values(**payload.model_dump(exclude_unset=True))
    if (await db.execute(stmt)).rowcount == 0: raise HTTPException(status_code=404, detail="Goal not found")
    await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.post("/v1/links", dependencies=[Depends(check_idempotency)])
async def create_link(request: Request, payload: LinkCreate, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    link_id = f"lnk_{uuid.uuid4().hex[:12]}"
    db.add(EntityLink(id=link_id, user_id=user_id, from_entity_type=payload.from_entity_type, from_entity_id=payload.from_entity_id, to_entity_type=payload.to_entity_type, to_entity_id=payload.to_entity_id, link_type=payload.link_type, created_at=utc_now()))
    await db.commit()
    resp = {"id": link_id}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.delete("/v1/links/{link_id}", dependencies=[Depends(check_idempotency)])
async def delete_link(request: Request, link_id: str, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    if (await db.execute(delete(EntityLink).where(EntityLink.id == link_id, EntityLink.user_id == user_id))).rowcount > 0: await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

# --- Planning & Query (Phase 3) ---

@app.post("/v1/plan/refresh", response_model=PlanRefreshResponse, dependencies=[Depends(check_idempotency)])
async def plan_refresh(request: Request, payload: PlanRefreshRequest, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    await enforce_rate_limit(user_id, "plan", settings.RATE_LIMIT_PLAN_PER_WINDOW)
    job_id = str(uuid.uuid4())
    await redis_client.rpush("default_queue", json.dumps({"job_id": job_id, "topic": "plan.refresh", "payload": {"user_id": user_id, "chat_id": payload.chat_id}}))
    resp = PlanRefreshResponse(status="ok", enqueued=True, job_id=job_id)
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp.model_dump())
    return resp

@app.get("/v1/plan/get_today", response_model=PlanResponseV1, dependencies=[Depends(get_authenticated_user)])
async def get_today_plan(chat_id: str, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    cached = await redis_client.get(f"plan:today:{user_id}:{chat_id}")
    if cached:
        try:
            return PlanResponseV1(**json.loads(cached))
        except Exception as e:
            logger.warning(f"Cached plan invalid: {e}")
    
    state = await collect_planning_state(db, user_id)
    payload = build_plan_payload(state, utc_now())
    try:
        validated = PlanResponseV1(**render_fallback_plan_explanation(payload))
        return validated
    except Exception as e:
        logger.error(f"Plan validation failed: {e}")
        db.add(EventLog(
            id=str(uuid.uuid4()), request_id=f"req_{uuid.uuid4().hex[:8]}", user_id=user_id,
            event_type="plan_rewrite_fallback", payload_json={"error": str(e), "context": "api_get_today"}
        ))
        await db.commit()
        # Create a emergency minimal valid payload if even the deterministic builder failed somehow
        emergency_payload = {
            "schema_version": "plan.v1", "plan_window": "today", 
            "generated_at": utc_now().isoformat().replace("+00:00", "Z"),
            "today_plan": [], "next_actions": [], "blocked_items": []
        }
        return PlanResponseV1(**emergency_payload)

@app.post("/v1/query/ask", response_model=QueryResponseV1, dependencies=[Depends(get_authenticated_user)])
async def query_ask(payload: QueryAskRequest, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    await enforce_rate_limit(user_id, "query", settings.RATE_LIMIT_QUERY_PER_WINDOW)
    ctx = await assemble_context(db=db, user_id=user_id, chat_id=payload.chat_id, query=payload.query, max_tokens=payload.max_tokens or settings.QUERY_MAX_TOKENS)
    start_time = time.time()
    request_id = str(uuid.uuid4())
    try:
        raw_resp = await adapter.answer_query(payload.query, ctx)
        usage = _extract_usage(raw_resp)
        query_response = QueryResponseV1(**raw_resp) # Requirement 2: Strict Validation
        db.add(PromptRun(
            id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, operation="query",
            provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_QUERY,
            prompt_version=settings.PROMPT_VERSION_QUERY, latency_ms=int((time.time()-start_time)*1000),
            input_tokens=usage["input_tokens"], cached_input_tokens=usage["cached_input_tokens"],
            output_tokens=usage["output_tokens"],
            status="success", created_at=utc_now()
        ))
    except Exception as e:
        logger.error(f"Query failure: {e}")
        db.add(PromptRun(id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, operation="query", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_QUERY, prompt_version=settings.PROMPT_VERSION_QUERY, status="error", error_code=type(e).__name__, created_at=utc_now()))
        db.add(EventLog(id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, event_type="query_fallback_used", payload_json={"error": str(e)}))
        query_response = QueryResponseV1(answer="I'm sorry, I couldn't process your request.", confidence=0.0)
    await db.commit()
    return query_response

@app.get("/v1/memory/context", dependencies=[Depends(get_authenticated_user)])

async def get_memory_context(chat_id: str, query: str, max_tokens: Optional[int] = None, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):

    return await assemble_context(db=db, user_id=user_id, chat_id=chat_id, query=query, max_tokens=max_tokens)



# --- Phase 5/11 Todoist Sync ---

@app.post("/v1/sync/todoist", dependencies=[Depends(check_idempotency)])
async def trigger_todoist_sync(request: Request, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"):
        return request.state.idempotent_response
    job_id = str(uuid.uuid4())
    await redis_client.rpush(
        "default_queue",
        json.dumps({"job_id": job_id, "topic": "sync.todoist", "payload": {"user_id": user_id}}),
    )
    resp = {"status": "ok", "job_id": job_id}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp


@app.post("/v1/sync/todoist/reconcile", dependencies=[Depends(check_idempotency)])
async def trigger_todoist_reconcile(request: Request, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"):
        return request.state.idempotent_response
    job_id = str(uuid.uuid4())
    await redis_client.rpush(
        "default_queue",
        json.dumps({"job_id": job_id, "topic": "sync.todoist.reconcile", "payload": {"user_id": user_id}}),
    )
    resp = {"status": "ok", "enqueued": True, "job_id": job_id}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp


@app.get("/v1/sync/todoist/status", response_model=TodoistSyncStatusResponse, dependencies=[Depends(get_authenticated_user)])
async def get_todoist_sync_status(user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func

    total_mapped = (
        await db.execute(select(func.count(TodoistTaskMap.id)).where(TodoistTaskMap.user_id == user_id))
    ).scalar()
    pending_sync = (
        await db.execute(
            select(func.count(TodoistTaskMap.id)).where(
                TodoistTaskMap.user_id == user_id,
                TodoistTaskMap.sync_state == "pending",
            )
        )
    ).scalar()
    error_count = (
        await db.execute(
            select(func.count(TodoistTaskMap.id)).where(
                TodoistTaskMap.user_id == user_id,
                TodoistTaskMap.sync_state == "error",
            )
        )
    ).scalar()
    last_synced = (
        await db.execute(select(func.max(TodoistTaskMap.last_synced_at)).where(TodoistTaskMap.user_id == user_id))
    ).scalar()
    last_attempt = (
        await db.execute(select(func.max(TodoistTaskMap.last_attempt_at)).where(TodoistTaskMap.user_id == user_id))
    ).scalar()
    last_reconcile = (
        await db.execute(
            select(func.max(EventLog.created_at)).where(
                EventLog.user_id == user_id,
                EventLog.event_type == "todoist_reconcile_completed",
            )
        )
    ).scalar()
    reconcile_window_cutoff = utc_now() - timedelta(minutes=settings.TODOIST_RECONCILE_WINDOW_MINUTES)
    reconcile_error_count = (
        await db.execute(
            select(func.count(EventLog.id)).where(
                EventLog.user_id == user_id,
                EventLog.event_type.in_(["todoist_reconcile_task_failed", "todoist_reconcile_remote_missing"]),
                EventLog.created_at >= reconcile_window_cutoff,
            )
        )
    ).scalar()

    return TodoistSyncStatusResponse(
        total_mapped=total_mapped or 0,
        pending_sync=pending_sync or 0,
        error_count=error_count or 0,
        last_synced_at=last_synced.isoformat() if last_synced else None,
        last_attempt_at=last_attempt.isoformat() if last_attempt else None,
        last_reconcile_at=last_reconcile.isoformat() if last_reconcile else None,
        reconcile_error_count=reconcile_error_count or 0,
    )





    

    
