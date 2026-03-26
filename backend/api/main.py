import uuid
import copy
import re
import logging
import asyncio
from datetime import datetime, timedelta, timezone, date
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx

from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete

import redis.asyncio as redis

from common.config import settings
from common.models import (
    Base, IdempotencyKey, InboxItem, Session,
    EventLog, PromptRun, LinkType, RecentContextItem,
    ActionDraft, WorkItem, WorkItemKind, WorkItemStatus,
    ConversationEvent, ConversationSource, ConversationDirection, ActionBatch, ActionBatchStatus,
    WorkItemVersion, ReminderVersion, VersionOperation, WorkItemLink, WorkItemLinkType, Reminder, ReminderKind, ReminderStatus
)
from common.adapter import adapter
from common.memory import assemble_context
from common.planner import collect_planning_state, build_plan_payload, render_fallback_plan_explanation
from common.recent_context import remember_recent_reminders, remember_recent_tasks
from common.session_state import (
    active_entity_refs_from_grounding,
    get_latest_session,
    get_or_create_active_session,
    session_state_payload,
    update_session_state,
)
from common.reminders import (
    compute_snooze_remind_at,
    normalize_recurrence_rule,
    supported_recurrence_rules,
    supported_snooze_presets,
)
from common.work_items import (
    work_item_due_date_text,
    work_item_snapshot,
    work_item_attributes,
    due_at_to_due_date,
)
from api.interaction_routes import register_interaction_routes, run_query_ask
from api.local_first_routes import register_local_first_routes
from api.platform_routes import register_platform_routes
from api.capture_apply import (
    run_action_batch_summary,
    run_action_batch_view_payload,
    run_apply_capture,
    run_change_title_for_summary,
    run_infer_urgency_score,
    run_operation_for_work_item_change,
    run_operation_summary_verb,
    run_record_reminder_action_batch,
    run_record_work_item_action_batch,
    run_reminder_snapshot,
    run_reminder_version_view_payload,
    run_restore_reminder_from_snapshot,
    run_restore_work_item_from_snapshot,
    run_snapshot_datetime,
    run_work_item_version_view_payload,
)
from api.draft_runtime import (
    run_actions_to_extraction,
    run_apply_intent_fallbacks,
    run_autopilot_decision,
    run_build_low_confidence_clarification,
    run_confirm_action_draft,
    run_create_action_draft,
    run_discard_action_draft,
    run_generic_unresolved_clarification_text,
    run_get_open_action_draft,
    run_has_unresolved_reminder_target,
    run_has_unresolved_task_target,
    run_is_low_risk_action_extraction,
    run_is_safe_completion_extraction,
    run_planner_confidence,
    run_resolve_relative_due_date_overrides,
    run_revise_action_draft,
    run_unresolved_mutation_titles,
)
from api.grounding_runtime import (
    run_build_extraction_grounding,
    run_enqueue_summary_job,
    run_grounding_terms,
    run_infer_reminder_ids_from_answer_text,
    run_infer_task_ids_from_answer_text,
    run_parse_recent_display_reason,
    run_recent_display_reason,
    run_remember_displayed_tasks,
    run_remember_query_surface_context,
    run_remember_recent_reminders,
    run_remember_recent_tasks,
    run_reminder_ids_from_query_response,
    run_resolve_displayed_task_id,
    run_task_ids_from_query_response,
)
from api.health_runtime import (
    run_check_llm_credentials,
    run_check_telegram_credentials,
    run_compute_preflight_report,
    run_external_preflight_required,
    run_get_preflight_report,
    run_http_ok_status,
)
from api.maintenance_runtime import (
    run_apply_work_item_updates,
    run_coerce_reminder_kind,
    run_coerce_reminder_status,
    run_coerce_work_item_status,
    run_get_work_item_by_id,
    run_new_work_item_id,
    run_parse_due_at,
    run_parse_due_date,
    run_reminder_view_payload,
    run_validated_recurrence_rule,
    run_work_item_link_type_from_legacy,
    run_work_item_view_payload,
)
from api.request_runtime import (
    run_check_idempotency,
    run_enforce_rate_limit,
    run_extract_usage,
    run_get_authenticated_user,
    run_save_idempotency,
    run_validate_extraction_payload,
)
from api.reference_resolution import (
    run_apply_displayed_task_reference_extraction,
    run_best_reminder_reference_candidate,
    run_best_task_reference_candidate,
    run_build_candidate_clarification_text,
    run_build_candidate_task_clarification,
    run_candidate_reminder_clarification_info,
    run_candidate_task_clarification_info,
    run_completion_candidate_rows,
    run_detected_mutation_phrase,
    run_detected_reminder_mutation_phrase,
    run_fill_clarified_reminder_target,
    run_fill_clarified_task_target,
    run_has_term_overlap,
    run_is_explicit_displayed_reference_mutation,
    run_is_explicit_recent_named_reference_mutation,
    run_merge_grounding_task_refs,
    run_missing_reminder_schedule_info,
    run_rank_reminder_reference_candidates,
    run_rank_task_reference_candidates,
    run_reminder_reference_candidates,
    run_reminder_requires_schedule,
    run_reminder_requires_target,
    run_sanitize_completion_extraction,
    run_sanitize_create_extraction,
    run_sanitize_targeted_reminder_actions,
    run_sanitize_targeted_task_actions,
    run_score_reminder_reference_candidate,
    run_score_task_reference_candidate,
    run_select_clarification_candidate,
    run_task_reference_candidates,
)
from api.telegram_orchestration import (
    run_build_telegram_deep_link,
    run_build_workbench_url,
    run_consume_telegram_link_token,
    run_handle_telegram_callback_update,
    run_handle_telegram_command,
    run_handle_telegram_message_update,
    run_hash_link_token,
    run_issue_telegram_link_token,
    run_preferred_auth_token_for_user,
    run_resolve_telegram_user,
)
from api.telegram_draft_flow import run_handle_telegram_draft_flow
from api.telegram_views import (
    run_build_live_today_plan_payload,
    run_cache_today_plan_payload,
    run_extract_plan_task_ids,
    run_invalidate_today_plan_cache,
    run_load_today_plan_payload,
    run_plan_cache_key,
    run_plan_payload_generated_at,
    run_plan_payload_is_fresh,
    run_send_open_task_view,
    run_send_today_plan_view,
    run_send_urgent_task_view,
    run_stage_clarification_draft,
    run_telegram_plan_payload,
)
from api.schemas import (
    AppliedChanges, AppliedChangeItem,
    LinkCreate,
    PlanResponseV1,
    QueryAskRequest, QueryResponseV1,
    TelegramLinkTokenCreateResponse
)
from common.telegram import (
    verify_telegram_secret, parse_update, extract_command, send_message, edit_message, answer_callback_query, build_draft_reply_markup,
    format_today_plan, format_focus_mode, format_urgent_tasks, format_open_tasks, format_capture_ack,
    escape_html, format_query_answer, user_facing_task_title
)

# --- Shared Capture Pipeline ---
ACTION_DRAFT_TTL_SECONDS = 1800
AUTOPILOT_COMPLETION_CONFIDENCE = 0.70
AUTOPILOT_ACTION_CONFIDENCE = 0.90
CLARIFY_ACTION_CONFIDENCE = 0.50
TASK_MATCH_IGNORE_TERMS = {
    "mark",
    "done",
    "complete",
    "completed",
    "close",
    "closed",
    "finished",
    "handled",
    "delete",
    "remove",
    "drop",
    "archive",
    "discard",
    "cancel",
    "move",
    "reschedule",
    "update",
    "change",
    "set",
    "rename",
    "task",
    "tasks",
    "item",
    "items",
    "ones",
    "one",
    "please",
    "lets",
    "let",
    "already",
    "open",
    "today",
    "tonight",
    "tomorrow",
    "week",
    "month",
    "day",
}
PLAN_CACHE_TTL_SECONDS = 86400
PLAN_AUTO_REFRESH_MAX_AGE_SECONDS = 300


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


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_query_text(text: str) -> str:
    collapsed = re.sub(r"[^a-z0-9\s]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", collapsed).strip()

def _canonical_task_title(title: Any) -> str:
    cleaned = re.sub(r"\s+", " ", user_facing_task_title(title)).strip()
    return cleaned or re.sub(r"\s+", " ", str(title or "").strip())


def _result_rows(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _resolve_relative_due_date_overrides(message: str, extraction: Dict[str, Any]) -> Dict[str, Any]:
    return run_resolve_relative_due_date_overrides(message, extraction, helpers=globals())


def _session_state_payload(session: Optional[Session]) -> Dict[str, Any]:
    return session_state_payload(session)


def _active_entity_refs_from_grounding(grounding: Dict[str, Any], limit: int = 12) -> List[Dict[str, Any]]:
    return active_entity_refs_from_grounding(grounding, limit=limit)


async def _get_latest_session(db: AsyncSession, user_id: str, chat_id: str) -> Optional[Session]:
    return await get_latest_session(db, user_id=user_id, chat_id=chat_id)


async def _get_or_create_session(db: AsyncSession, user_id: str, chat_id: str) -> Session:
    return await get_or_create_active_session(
        db,
        user_id=user_id,
        chat_id=chat_id,
        now=utc_now(),
        inactivity_minutes=settings.SESSION_INACTIVITY_MINUTES,
    )


async def _update_session_state(
    db: AsyncSession,
    session: Optional[Session],
    *,
    current_mode: Any = None,
    active_entity_refs: Any = None,
    pending_draft_id: Any = None,
    pending_clarification: Any = None,
    summary_metadata: Optional[Dict[str, Any]] = None,
    touch: bool = True,
) -> Optional[Session]:
    return await update_session_state(
        db,
        session,
        now=utc_now(),
        current_mode=current_mode,
        active_entity_refs=active_entity_refs,
        pending_draft_id=pending_draft_id,
        pending_clarification=pending_clarification,
        summary_metadata=summary_metadata,
        touch=touch,
    )


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


def _draft_set_clarification_state(draft: ActionDraft, state: Optional[Dict[str, Any]]) -> None:
    proposal = copy.deepcopy(draft.proposal_json) if isinstance(draft.proposal_json, dict) else {}
    meta = proposal.get("_meta") if isinstance(proposal.get("_meta"), dict) else {}
    if isinstance(state, dict) and state:
        meta["clarification_state"] = state
    else:
        meta.pop("clarification_state", None)
    proposal["_meta"] = meta
    draft.proposal_json = proposal


def _draft_get_clarification_state(draft: ActionDraft) -> Optional[Dict[str, Any]]:
    if not isinstance(draft.proposal_json, dict):
        return None
    meta = draft.proposal_json.get("_meta")
    if not isinstance(meta, dict):
        return None
    state = meta.get("clarification_state")
    return state if isinstance(state, dict) else None


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


def _truncate_preview_text(value: Any, limit: int = 80) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _empty_extraction() -> Dict[str, Any]:
    return {"tasks": [], "goals": [], "problems": [], "links": [], "reminders": []}


def _task_preview_group(task: Dict[str, Any]) -> tuple[str, str, str]:
    action = str(task.get("action") or "").strip().lower()
    status = str(task.get("status") or "").strip().lower()
    kind = str(task.get("kind") or "").strip().lower()
    noun = "project" if kind == "project" else "subtask" if kind == "subtask" else "task"
    if action == "complete" or status == "done":
        return "completed", "Mark complete", f"Complete {noun}"
    if action == "archive" or status == "archived":
        return "archived", "Archive", f"Archive {noun}"
    if action == "update" or task.get("target_task_id"):
        if kind == "project":
            return "updated", "Update existing task", "Promote to project"
        return "updated", "Update existing task", f"Update {noun}"
    return "created", "Create new task", f"Create {noun}"


def _task_preview_details(task: Dict[str, Any]) -> List[str]:
    details: List[str] = []
    status_value = str(task.get("status") or "").strip().lower()
    if status_value and status_value not in {"done", "archived", "open"}:
        details.append(f"status -> {status_value}")
    parent_title = task.get("parent_title")
    if isinstance(parent_title, str) and parent_title.strip():
        details.append(f"parent -> {parent_title.strip()}")
    parent_task_id = task.get("parent_task_id")
    if isinstance(parent_task_id, str) and parent_task_id.strip():
        details.append(f"parent id -> {parent_task_id.strip()}")
    if isinstance(task.get("due_date"), str) and task.get("due_date").strip():
        details.append(f"due -> {task.get('due_date').strip()[:10]}")
    notes = task.get("notes")
    if isinstance(notes, str) and notes.strip():
        details.append(f"notes -> {_truncate_preview_text(notes)}")
    if isinstance(task.get("priority"), int):
        details.append(f"priority -> {task['priority']}")
    if isinstance(task.get("impact_score"), int):
        details.append(f"impact -> {task['impact_score']}")
    if isinstance(task.get("urgency_score"), int):
        details.append(f"urgency -> {task['urgency_score']}")
    return details


def _reminder_preview_group(reminder: Dict[str, Any]) -> tuple[str, str, str]:
    action = str(reminder.get("action") or "").strip().lower()
    status = str(reminder.get("status") or "").strip().lower()
    if action == "complete" or status == "completed":
        return "completed", "Mark reminder complete", "Complete reminder"
    if action in {"cancel", "dismiss"} or status in {"canceled", "dismissed"}:
        return "canceled", "Cancel reminder", "Cancel reminder"
    if action == "update" or reminder.get("target_reminder_id"):
        return "updated", "Update existing reminder", "Update reminder"
    return "created", "Create reminder", "Create reminder"


def _reminder_preview_details(reminder: Dict[str, Any]) -> List[str]:
    details: List[str] = []
    if isinstance(reminder.get("remind_at"), str) and reminder.get("remind_at").strip():
        details.append(f"at -> {reminder.get('remind_at').strip()}")
    if isinstance(reminder.get("recurrence_rule"), str) and reminder.get("recurrence_rule").strip():
        details.append(f"repeat -> {reminder.get('recurrence_rule').strip()}")
    if isinstance(reminder.get("message"), str) and reminder.get("message").strip():
        details.append(f"message -> {_truncate_preview_text(reminder.get('message'))}")
    return details


def _format_action_draft_preview(extraction: Dict[str, Any]) -> str:
    task_groups: Dict[str, List[tuple[str, List[str]]]] = {
        "created": [],
        "updated": [],
        "completed": [],
        "archived": [],
    }
    reminder_groups: Dict[str, List[tuple[str, List[str]]]] = {
        "created": [],
        "updated": [],
        "completed": [],
        "canceled": [],
    }
    links = [
        link for link in extraction.get("links", [])
        if isinstance(link, dict)
        and isinstance(link.get("from_title"), str)
        and isinstance(link.get("to_title"), str)
        and isinstance(link.get("link_type"), str)
    ]

    for task in extraction.get("tasks", []):
        if not isinstance(task, dict):
            continue
        title = task.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        key, heading, verb = _task_preview_group(task)
        details = _task_preview_details(task)
        task_groups[key].append((f"<b>{verb}:</b> {escape_html(title.strip())}", details))
    for reminder in extraction.get("reminders", []):
        if not isinstance(reminder, dict):
            continue
        title = reminder.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        key, heading, verb = _reminder_preview_group(reminder)
        details = _reminder_preview_details(reminder)
        reminder_groups[key].append((f"<b>{verb}:</b> {escape_html(title.strip())}", details))

    if not any(task_groups.values()) and not any(reminder_groups.values()) and not links:
        return (
            "I did not find clear actions to apply yet.\n"
            "Reply with more details, or ask a question directly."
        )

    lines = ["<b>Proposed changes</b>"]
    ordered_groups = [
        ("completed", "Mark complete"),
        ("updated", "Update existing task"),
        ("created", "Create new task"),
        ("archived", "Archive"),
    ]
    for key, heading in ordered_groups:
        items = task_groups[key]
        if not items:
            continue
        lines.extend(["", f"<b>{heading}</b>"])
        for preview, details in items[:4]:
            lines.append(f"• {preview}")
            if details:
                lines.append(f"  <i>{escape_html('; '.join(details))}</i>")
        if len(items) > 4:
            lines.append(f"• +{len(items) - 4} more task(s)")

    ordered_reminder_groups = [
        ("completed", "Mark reminder complete"),
        ("updated", "Update existing reminder"),
        ("created", "Create reminder"),
        ("canceled", "Cancel reminder"),
    ]
    for key, heading in ordered_reminder_groups:
        items = reminder_groups[key]
        if not items:
            continue
        lines.extend(["", f"<b>{heading}</b>"])
        for preview, details in items[:4]:
            lines.append(f"• {preview}")
            if details:
                lines.append(f"  <i>{escape_html('; '.join(details))}</i>")
        if len(items) > 4:
            lines.append(f"• +{len(items) - 4} more reminder(s)")

    if links:
        lines.extend(["", "<b>Links</b>"])
        for link in links[:3]:
            lines.append(
                "• <b>Create link:</b> "
                f"{escape_html(link['from_title'].strip())} {escape_html(link['link_type'].strip())} {escape_html(link['to_title'].strip())}"
            )
        if len(links) > 3:
            lines.append(f"• +{len(links) - 3} more link(s)")

    lines.extend(["", "Tap <code>Yes</code> to apply these exact changes, <code>Edit</code> to revise them, or <code>No</code> to discard."])
    return "\n".join(lines)


def _has_actionable_entities(extraction: Dict[str, Any]) -> bool:
    return bool(
        extraction.get("tasks")
        or extraction.get("links")
        or extraction.get("reminders")
    )


def _has_term_overlap(title_terms: set[str], msg_terms: set[str]) -> bool:
    return run_has_term_overlap(title_terms, msg_terms)


def _task_reference_candidates(grounding: Dict[str, Any]) -> List[Dict[str, Any]]:
    return run_task_reference_candidates(grounding, helpers=globals())


def _score_task_reference_candidate(clause: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
    return run_score_task_reference_candidate(clause, candidate, helpers=globals())


def _rank_task_reference_candidates(clause: str, grounding: Dict[str, Any], *, open_only: bool = True) -> List[Dict[str, Any]]:
    return run_rank_task_reference_candidates(clause, grounding, open_only=open_only, helpers=globals())


def _best_task_reference_candidate(clause: str, grounding: Dict[str, Any], *, open_only: bool = True) -> Optional[Dict[str, Any]]:
    return run_best_task_reference_candidate(clause, grounding, open_only=open_only, helpers=globals())


def _completion_candidate_rows(grounding: Dict[str, Any]) -> List[Dict[str, Any]]:
    return run_completion_candidate_rows(grounding, helpers=globals())


def _sanitize_completion_extraction(
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
) -> Dict[str, Any]:
    return run_sanitize_completion_extraction(extraction, grounding, helpers=globals())


def _sanitize_create_extraction(
    extraction: Dict[str, Any],
) -> Dict[str, Any]:
    return run_sanitize_create_extraction(extraction, helpers=globals())


def _apply_displayed_task_reference_extraction(
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
) -> Dict[str, Any]:
    return run_apply_displayed_task_reference_extraction(extraction, grounding, helpers=globals())


def _is_explicit_displayed_reference_mutation(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
) -> bool:
    return run_is_explicit_displayed_reference_mutation(message, extraction, grounding, helpers=globals())


def _is_explicit_recent_named_reference_mutation(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
) -> bool:
    return run_is_explicit_recent_named_reference_mutation(message, extraction, grounding, helpers=globals())


def _reminder_requires_target(reminder: Dict[str, Any]) -> bool:
    return run_reminder_requires_target(reminder)


def _reminder_requires_schedule(reminder: Dict[str, Any]) -> bool:
    return run_reminder_requires_schedule(reminder, helpers=globals())


def _sanitize_targeted_task_actions(message: str, extraction: Dict[str, Any], grounding: Dict[str, Any]) -> Dict[str, Any]:
    return run_sanitize_targeted_task_actions(message, extraction, grounding, helpers=globals())


def _reminder_reference_candidates(grounding: Dict[str, Any]) -> List[Dict[str, Any]]:
    return run_reminder_reference_candidates(grounding, helpers=globals())


def _score_reminder_reference_candidate(clause: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
    return run_score_reminder_reference_candidate(clause, candidate, helpers=globals())


def _rank_reminder_reference_candidates(clause: str, grounding: Dict[str, Any], *, active_only: bool = True) -> List[Dict[str, Any]]:
    return run_rank_reminder_reference_candidates(clause, grounding, active_only=active_only, helpers=globals())


def _best_reminder_reference_candidate(clause: str, grounding: Dict[str, Any], *, active_only: bool = True) -> Optional[Dict[str, Any]]:
    return run_best_reminder_reference_candidate(clause, grounding, active_only=active_only, helpers=globals())


def _sanitize_targeted_reminder_actions(message: str, extraction: Dict[str, Any], grounding: Dict[str, Any]) -> Dict[str, Any]:
    return run_sanitize_targeted_reminder_actions(message, extraction, grounding, helpers=globals())


def _detected_mutation_phrase(task: Optional[Dict[str, Any]] = None) -> str:
    return run_detected_mutation_phrase(task)


def _detected_reminder_mutation_phrase(reminder: Optional[Dict[str, Any]] = None) -> str:
    return run_detected_reminder_mutation_phrase(reminder)


def _build_candidate_clarification_text(action_phrase: str, entity_label: str, ranked: List[Dict[str, Any]]) -> str:
    return run_build_candidate_clarification_text(action_phrase, entity_label, ranked, helpers=globals())


def _candidate_task_clarification_info(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    return run_candidate_task_clarification_info(message, extraction, grounding, helpers=globals())


def _candidate_reminder_clarification_info(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    return run_candidate_reminder_clarification_info(message, extraction, grounding, helpers=globals())


def _missing_reminder_schedule_info(extraction: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return run_missing_reminder_schedule_info(extraction, helpers=globals())


def _build_candidate_task_clarification(message: str, extraction: Dict[str, Any], grounding: Dict[str, Any]) -> Optional[str]:
    return run_build_candidate_task_clarification(message, extraction, grounding, helpers=globals())


def _merge_grounding_task_refs(grounding: Dict[str, Any], key: str, rows: List[Dict[str, Any]]) -> None:
    run_merge_grounding_task_refs(grounding, key, rows)


def _select_clarification_candidate(reply_text: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return run_select_clarification_candidate(reply_text, candidates, helpers=globals())


def _fill_clarified_task_target(
    base_extraction: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    return run_fill_clarified_task_target(base_extraction, candidate, helpers=globals())


def _fill_clarified_reminder_target(
    base_extraction: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    return run_fill_clarified_reminder_target(base_extraction, candidate, helpers=globals())


def _planner_confidence(planned: Any) -> float:
    return run_planner_confidence(planned)


def _is_safe_completion_extraction(extraction: Dict[str, Any]) -> bool:
    return run_is_safe_completion_extraction(extraction)


def _is_low_risk_action_extraction(extraction: Dict[str, Any]) -> bool:
    return run_is_low_risk_action_extraction(extraction)


def _unresolved_mutation_titles(extraction: Dict[str, Any]) -> List[str]:
    return run_unresolved_mutation_titles(extraction, helpers=globals())


def _has_unresolved_task_target(extraction: Dict[str, Any]) -> bool:
    return run_has_unresolved_task_target(extraction)


def _has_unresolved_reminder_target(extraction: Dict[str, Any]) -> bool:
    return run_has_unresolved_reminder_target(extraction, helpers=globals())


def _generic_unresolved_clarification_text(extraction: Dict[str, Any], unresolved_preview: str) -> str:
    return run_generic_unresolved_clarification_text(extraction, unresolved_preview, helpers=globals())


def _autopilot_decision(message: str, extraction: Dict[str, Any], planned: Any) -> tuple[bool, str]:
    return run_autopilot_decision(message, extraction, planned, helpers=globals())


def _build_low_confidence_clarification(extraction: Dict[str, Any]) -> str:
    return run_build_low_confidence_clarification(extraction, helpers=globals())


def _apply_intent_fallbacks(message: str, extraction: Dict[str, Any], grounding: Dict[str, Any]) -> Dict[str, Any]:
    return run_apply_intent_fallbacks(message, extraction, grounding, helpers=globals())


def _actions_to_extraction(actions: Any) -> Dict[str, Any]:
    return run_actions_to_extraction(actions, helpers=globals())


async def _get_open_action_draft(user_id: str, chat_id: str, db: AsyncSession) -> Optional[ActionDraft]:
    return await run_get_open_action_draft(user_id, chat_id, db, helpers=globals())


async def _create_action_draft(
    db: AsyncSession,
    user_id: str,
    chat_id: str,
    message: str,
    extraction: Dict[str, Any],
    request_id: str,
) -> ActionDraft:
    return await run_create_action_draft(
        db,
        user_id,
        chat_id,
        message,
        extraction,
        request_id,
        helpers=globals(),
    )


async def _discard_action_draft(draft: ActionDraft, user_id: str, request_id: str, db: AsyncSession) -> None:
    await run_discard_action_draft(draft, user_id, request_id, db, helpers=globals())


async def _revise_action_draft(
    draft: ActionDraft, user_id: str, request_id: str, edit_text: str, db: AsyncSession
) -> Dict[str, Any]:
    return await run_revise_action_draft(draft, user_id, request_id, edit_text, db, helpers=globals())


async def _confirm_action_draft(
    draft: ActionDraft, user_id: str, chat_id: str, request_id: str, db: AsyncSession
) -> AppliedChanges:
    return await run_confirm_action_draft(draft, user_id, chat_id, request_id, db, helpers=globals())


def _grounding_terms(message: str) -> set[str]:
    return run_grounding_terms(message)


async def _build_extraction_grounding(db: AsyncSession, user_id: str, chat_id: str, message: str = "") -> Dict[str, Any]:
    return await run_build_extraction_grounding(
        db,
        user_id,
        chat_id,
        message=message,
        helpers=globals(),
    )


async def _enqueue_summary_job(user_id: str, chat_id: str, inbox_item_id: str) -> None:
    await run_enqueue_summary_job(user_id, chat_id, inbox_item_id, helpers=globals())


async def _remember_recent_tasks(
    db: AsyncSession,
    user_id: str,
    chat_id: str,
    task_ids: List[str],
    reason: str,
    ttl_hours: int = 24,
) -> None:
    await run_remember_recent_tasks(
        db,
        user_id,
        chat_id,
        task_ids,
        reason,
        ttl_hours=ttl_hours,
        helpers=globals(),
    )


async def _remember_recent_reminders(
    db: AsyncSession,
    user_id: str,
    chat_id: str,
    reminder_ids: List[str],
    reason: str,
    ttl_hours: int = 24,
) -> None:
    await run_remember_recent_reminders(
        db,
        user_id,
        chat_id,
        reminder_ids,
        reason,
        ttl_hours=ttl_hours,
        helpers=globals(),
    )


def _recent_display_reason(view_name: str, batch_id: str, ordinal: int) -> str:
    return run_recent_display_reason(view_name, batch_id, ordinal)


def _parse_recent_display_reason(reason: Any) -> tuple[str, str, int] | None:
    return run_parse_recent_display_reason(reason)


async def _remember_displayed_tasks(
    db: AsyncSession,
    user_id: str,
    chat_id: str,
    task_ids: List[str],
    view_name: str,
    ttl_hours: int = 12,
) -> None:
    await run_remember_displayed_tasks(
        db,
        user_id,
        chat_id,
        task_ids,
        view_name,
        ttl_hours=ttl_hours,
        helpers=globals(),
    )


def _task_ids_from_query_response(response: QueryResponseV1) -> List[str]:
    return run_task_ids_from_query_response(response)


def _reminder_ids_from_query_response(response: QueryResponseV1) -> List[str]:
    return run_reminder_ids_from_query_response(response)


def _infer_task_ids_from_answer_text(answer: str, grounding: Dict[str, Any], limit: int = 6) -> List[str]:
    return run_infer_task_ids_from_answer_text(answer, grounding, limit=limit, helpers=globals())


def _infer_reminder_ids_from_answer_text(answer: str, grounding: Dict[str, Any], limit: int = 6) -> List[str]:
    return run_infer_reminder_ids_from_answer_text(answer, grounding, limit=limit, helpers=globals())


async def _remember_query_surface_context(
    db: AsyncSession,
    *,
    user_id: str,
    chat_id: str,
    response: QueryResponseV1,
    grounding: Dict[str, Any],
) -> None:
    await run_remember_query_surface_context(
        db,
        user_id=user_id,
        chat_id=chat_id,
        response=response,
        grounding=grounding,
        helpers=globals(),
    )


async def _resolve_displayed_task_id(
    db: AsyncSession,
    user_id: str,
    chat_id: str,
    ordinal: int,
) -> Optional[str]:
    return await run_resolve_displayed_task_id(
        db,
        user_id,
        chat_id,
        ordinal,
        helpers=globals(),
    )


def _append_applied_item(applied: AppliedChanges, group: str, label: str) -> None:
    cleaned = _canonical_task_title(label)
    if not cleaned or len(applied.items) >= 40:
        return
    applied.items.append(AppliedChangeItem(group=group, label=_truncate_preview_text(cleaned, limit=240)))


def _parse_due_date(value: Any) -> Optional[date]:
    return run_parse_due_date(value)


def _parse_due_at(value: Any) -> Optional[datetime]:
    return run_parse_due_at(value, helpers=globals())


def _coerce_work_item_status(value: Any) -> WorkItemStatus:
    return run_coerce_work_item_status(value, helpers=globals())


def _new_work_item_id(kind: WorkItemKind) -> str:
    return run_new_work_item_id(kind, helpers=globals())


def _work_item_view_payload(item: WorkItem) -> Dict[str, Any]:
    return run_work_item_view_payload(item, helpers=globals())


def _work_item_link_type_from_legacy(link_type: LinkType) -> Optional[WorkItemLinkType]:
    return run_work_item_link_type_from_legacy(link_type, helpers=globals())


def _coerce_reminder_status(value: Any) -> ReminderStatus:
    return run_coerce_reminder_status(value, helpers=globals())


def _coerce_reminder_kind(value: Any) -> ReminderKind:
    return run_coerce_reminder_kind(value, helpers=globals())


def _reminder_view_payload(reminder: Reminder) -> Dict[str, Any]:
    return run_reminder_view_payload(reminder)


def _validated_recurrence_rule(value: Optional[str]) -> Optional[str]:
    return run_validated_recurrence_rule(value, helpers=globals())


def _action_batch_view_payload(batch: ActionBatch) -> Dict[str, Any]:
    return run_action_batch_view_payload(batch)


def _work_item_version_view_payload(version: WorkItemVersion) -> Dict[str, Any]:
    return run_work_item_version_view_payload(version)


def _reminder_version_view_payload(version: ReminderVersion) -> Dict[str, Any]:
    return run_reminder_version_view_payload(version)


def _change_title_for_summary(record: Dict[str, Any]) -> str:
    return run_change_title_for_summary(record)


def _operation_summary_verb(operation: Any) -> str:
    return run_operation_summary_verb(operation)


def _action_batch_summary(records: List[Dict[str, Any]], fallback: str = "Applied changes") -> str:
    return run_action_batch_summary(records, fallback=fallback)


def _snapshot_datetime(value: Any) -> Optional[datetime]:
    return run_snapshot_datetime(value, helpers=globals())


def _reminder_snapshot(reminder: Reminder) -> Dict[str, Any]:
    return run_reminder_snapshot(reminder)


def _restore_work_item_from_snapshot(item: WorkItem, snapshot: Dict[str, Any]) -> None:
    run_restore_work_item_from_snapshot(item, snapshot, helpers=globals())


def _restore_reminder_from_snapshot(reminder: Reminder, snapshot: Dict[str, Any]) -> None:
    run_restore_reminder_from_snapshot(reminder, snapshot, helpers=globals())


def _operation_for_work_item_change(before_snapshot: Dict[str, Any], item: WorkItem) -> VersionOperation:
    return run_operation_for_work_item_change(before_snapshot, item)


async def _record_work_item_action_batch(
    db: AsyncSession,
    *,
    user_id: str,
    source_message: str,
    proposal_json: Optional[Dict[str, Any]],
    version_records: List[Dict[str, Any]],
    conversation_event_id: Optional[str] = None,
    status: ActionBatchStatus = ActionBatchStatus.applied,
    after_summary: Optional[str] = None,
) -> ActionBatch:
    return await run_record_work_item_action_batch(
        db,
        user_id=user_id,
        source_message=source_message,
        proposal_json=proposal_json,
        version_records=version_records,
        helpers=globals(),
        conversation_event_id=conversation_event_id,
        status=status,
        after_summary=after_summary,
    )


async def _record_reminder_action_batch(
    db: AsyncSession,
    *,
    user_id: str,
    source_message: str,
    proposal_json: Optional[Dict[str, Any]],
    version_records: List[Dict[str, Any]],
    conversation_event_id: Optional[str] = None,
    status: ActionBatchStatus = ActionBatchStatus.applied,
    after_summary: Optional[str] = None,
) -> ActionBatch:
    return await run_record_reminder_action_batch(
        db,
        user_id=user_id,
        source_message=source_message,
        proposal_json=proposal_json,
        version_records=version_records,
        helpers=globals(),
        conversation_event_id=conversation_event_id,
        status=status,
        after_summary=after_summary,
    )


def _infer_urgency_score(due: Optional[date], priority: Optional[int]) -> Optional[int]:
    return run_infer_urgency_score(due, priority, helpers=globals())

async def _apply_capture(db: AsyncSession, user_id: str, chat_id: str, source: str,
                         message: str, extraction: dict, request_id: str,
                         client_msg_id: Optional[str] = None,
                         commit: bool = True,
                         enqueue_summary: bool = True) -> tuple:
    return await run_apply_capture(
        db,
        user_id,
        chat_id,
        source,
        message,
        extraction,
        request_id,
        helpers=globals(),
        client_msg_id=client_msg_id,
        commit=commit,
        enqueue_summary=enqueue_summary,
    )


def _plan_cache_key(user_id: str, chat_id: str) -> str:
    return run_plan_cache_key(user_id, chat_id)


def _plan_payload_generated_at(payload: Dict[str, Any]) -> Optional[datetime]:
    return run_plan_payload_generated_at(payload, helpers=globals())


def _plan_payload_is_fresh(payload: Dict[str, Any], *, max_age_seconds: int = PLAN_AUTO_REFRESH_MAX_AGE_SECONDS) -> bool:
    return run_plan_payload_is_fresh(payload, helpers=globals(), max_age_seconds=max_age_seconds)


def _telegram_plan_payload(payload: Dict[str, Any], *, served_from_cache: bool) -> Dict[str, Any]:
    return run_telegram_plan_payload(payload, served_from_cache=served_from_cache)


async def _invalidate_today_plan_cache(user_id: str, chat_id: str) -> None:
    await run_invalidate_today_plan_cache(user_id, chat_id, helpers=globals())


def _extract_plan_task_ids(plan_payload: Dict[str, Any], *, limit: Optional[int] = None) -> List[str]:
    return run_extract_plan_task_ids(plan_payload, limit=limit)


async def _cache_today_plan_payload(user_id: str, chat_id: str, payload: Dict[str, Any]) -> None:
    await run_cache_today_plan_payload(user_id, chat_id, payload, helpers=globals())


async def _build_live_today_plan_payload(db: AsyncSession, user_id: str) -> Dict[str, Any]:
    return await run_build_live_today_plan_payload(db, user_id, helpers=globals())


async def _load_today_plan_payload(
    db: AsyncSession,
    user_id: str,
    chat_id: str,
    *,
    require_fresh: bool = True,
) -> tuple[Dict[str, Any], bool]:
    return await run_load_today_plan_payload(
        db,
        user_id,
        chat_id,
        helpers=globals(),
        require_fresh=require_fresh,
    )


async def _send_today_plan_view(
    db: AsyncSession,
    user_id: str,
    chat_id: str,
    payload: Dict[str, Any],
    *,
    served_from_cache: bool,
    view_name: str,
) -> None:
    await run_send_today_plan_view(
        db,
        user_id,
        chat_id,
        payload,
        helpers=globals(),
        served_from_cache=served_from_cache,
        view_name=view_name,
    )


async def _send_urgent_task_view(db: AsyncSession, user_id: str, chat_id: str) -> None:
    await run_send_urgent_task_view(db, user_id, chat_id, helpers=globals())


async def _send_open_task_view(db: AsyncSession, user_id: str, chat_id: str) -> None:
    await run_send_open_task_view(db, user_id, chat_id, helpers=globals())


async def _stage_clarification_draft(
    db: AsyncSession,
    user_id: str,
    chat_id: str,
    message: str,
    extraction: Dict[str, Any],
    request_id: str,
    clarification_text: str,
    clarification_candidates: Optional[List[Dict[str, Any]]] = None,
    clarification_state: Optional[Dict[str, Any]] = None,
) -> None:
    await run_stage_clarification_draft(
        db,
        user_id,
        chat_id,
        message,
        extraction,
        request_id,
        clarification_text,
        helpers=globals(),
        clarification_candidates=clarification_candidates,
        clarification_state=clarification_state,
    )


# --- Internal Helpers for Integration Routing ---

async def handle_telegram_command(command: str, args: Optional[str], chat_id: str, user_id: str, db: AsyncSession):
    return await run_handle_telegram_command(command, args, chat_id, user_id, db, helpers=globals())


def _hash_link_token(raw_token: str) -> str:
    return run_hash_link_token(raw_token)


def _build_telegram_deep_link(raw_token: str) -> Optional[str]:
    return run_build_telegram_deep_link(raw_token, helpers=globals())


def _preferred_auth_token_for_user(user_id: str) -> Optional[str]:
    return run_preferred_auth_token_for_user(user_id, helpers=globals())


def _build_workbench_url(user_id: str) -> Optional[str]:
    return run_build_workbench_url(user_id, helpers=globals())


async def _issue_telegram_link_token(user_id: str, db: AsyncSession) -> TelegramLinkTokenCreateResponse:
    return await run_issue_telegram_link_token(user_id, db, helpers=globals())


async def _resolve_telegram_user(chat_id: str, db: AsyncSession) -> Optional[str]:
    return await run_resolve_telegram_user(chat_id, db, helpers=globals())


async def _consume_telegram_link_token(chat_id: str, username: Optional[str], raw_token: str, db: AsyncSession) -> bool:
    return await run_consume_telegram_link_token(chat_id, username, raw_token, db, helpers=globals())

logger = logging.getLogger(__name__)
app = FastAPI(title="Telegram Native AI Assistant API")


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
    return await run_get_authenticated_user(request, helpers=globals())

async def enforce_rate_limit(user_id: str, endpoint_class: str, limit: int):
    return await run_enforce_rate_limit(user_id, endpoint_class, limit, helpers=globals())

def _extract_usage(metadata: Any) -> Dict[str, int]:
    return run_extract_usage(metadata)


def _validate_extraction_payload(extraction: Any) -> None:
    run_validate_extraction_payload(extraction, helpers=globals())

async def check_idempotency(request: Request, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    return await run_check_idempotency(request, user_id, db, helpers=globals())

async def save_idempotency(user_id: str, idempotency_key: str, request_hash: str, status_code: int, response_body: dict):
    return await run_save_idempotency(
        user_id,
        idempotency_key,
        request_hash,
        status_code,
        response_body,
        helpers=globals(),
    )

register_platform_routes(
    app,
    get_authenticated_user=get_authenticated_user,
    get_db=get_db,
    check_idempotency=check_idempotency,
    helpers=globals(),
)
register_interaction_routes(
    app,
    get_authenticated_user=get_authenticated_user,
    get_db=get_db,
    check_idempotency=check_idempotency,
    helpers=globals(),
)

# --- Health Endpoints ---

def _external_preflight_required() -> bool:
    return run_external_preflight_required(helpers=globals())


def _http_ok_status(code: int) -> bool:
    return run_http_ok_status(code)


async def _check_llm_credentials() -> Dict[str, Any]:
    return await run_check_llm_credentials(helpers=globals())


async def _check_telegram_credentials() -> Dict[str, Any]:
    return await run_check_telegram_credentials(helpers=globals())


async def _compute_preflight_report() -> Dict[str, Any]:
    return await run_compute_preflight_report(helpers=globals())


async def _get_preflight_report(force: bool = False) -> Dict[str, Any]:
    return await run_get_preflight_report(force=force, helpers=globals())


# --- Telegram Integration ---


async def _handle_telegram_callback_update(data: Dict[str, Any], db: AsyncSession) -> None:
    return await run_handle_telegram_callback_update(data, db, helpers=globals())


async def _handle_telegram_draft_flow(
    chat_id: str,
    text: str,
    client_msg_id: Optional[str],
    user_id: str,
    db: AsyncSession,
) -> None:
    return await run_handle_telegram_draft_flow(chat_id, text, client_msg_id, user_id, db, helpers=globals())


async def _handle_telegram_message_update(data: Dict[str, Any], db: AsyncSession) -> None:
    return await run_handle_telegram_message_update(data, db, helpers=globals())

# --- Entity CRUD ---

async def _get_work_item_by_id(
    db: AsyncSession,
    user_id: str,
    item_id: str,
    *,
    kinds: Optional[List[WorkItemKind]] = None,
) -> Optional[WorkItem]:
    return await run_get_work_item_by_id(db, user_id, item_id, kinds=kinds, helpers=globals())


def _apply_work_item_updates(item: WorkItem, update_data: Dict[str, Any]) -> None:
    run_apply_work_item_updates(item, update_data, helpers=globals())


register_local_first_routes(
    app,
    get_authenticated_user=get_authenticated_user,
    get_db=get_db,
    check_idempotency=check_idempotency,
    helpers=globals(),
)


@app.post("/v1/links", dependencies=[Depends(check_idempotency)])
async def create_link(request: Request, payload: LinkCreate, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    link_id = f"lnk_{uuid.uuid4().hex[:12]}"
    projected_type = _work_item_link_type_from_legacy(payload.link_type)
    if projected_type is None:
        raise HTTPException(status_code=400, detail="Unsupported link type for canonical work items")
    related_items = _result_rows((
        await db.execute(
            select(WorkItem).where(
                WorkItem.user_id == user_id,
                WorkItem.id.in_([payload.from_entity_id, payload.to_entity_id]),
            )
        )
    ).scalars().all())
    related_ids = {item.id for item in related_items if isinstance(item, WorkItem)}
    if payload.from_entity_id not in related_ids or payload.to_entity_id not in related_ids:
        raise HTTPException(status_code=404, detail="Both linked work items must exist and belong to you")
    db.add(
        WorkItemLink(
            id=link_id,
            user_id=user_id,
            from_work_item_id=payload.from_entity_id,
            to_work_item_id=payload.to_entity_id,
            link_type=projected_type,
            created_at=utc_now(),
        )
    )
    await db.commit()
    resp = {"id": link_id}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.delete("/v1/links/{link_id}", dependencies=[Depends(check_idempotency)])
async def delete_link(request: Request, link_id: str, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    work_item_deleted = (await db.execute(delete(WorkItemLink).where(WorkItemLink.id == link_id, WorkItemLink.user_id == user_id))).rowcount > 0
    if work_item_deleted:
        await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

# --- Planning & Query (Phase 3) ---

async def query_ask(payload: QueryAskRequest, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    return await run_query_ask(payload, user_id, db, helpers=globals())
