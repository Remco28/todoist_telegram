import copy
import uuid
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update

from common.models import ActionDraft, EventLog


def run_planner_confidence(planned: Any) -> float:
    if not isinstance(planned, dict):
        return 0.0
    value = planned.get("confidence")
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def run_is_safe_completion_extraction(extraction: Dict[str, Any]) -> bool:
    tasks = extraction.get("tasks", []) if isinstance(extraction, dict) else []
    if not isinstance(tasks, list) or not tasks:
        return False
    if extraction.get("goals") or extraction.get("problems") or extraction.get("links") or extraction.get("reminders"):
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


def run_is_low_risk_action_extraction(extraction: Dict[str, Any]) -> bool:
    tasks = extraction.get("tasks", []) if isinstance(extraction, dict) else []
    if not isinstance(tasks, list) or not tasks:
        return False
    if extraction.get("goals") or extraction.get("problems") or extraction.get("links") or extraction.get("reminders"):
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


def run_unresolved_mutation_titles(extraction: Dict[str, Any], *, helpers: Dict[str, Any]) -> List[str]:
    if not isinstance(extraction, dict):
        return []
    tasks = extraction.get("tasks", [])
    unresolved: List[str] = []
    if isinstance(tasks, list):
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
    reminders = extraction.get("reminders", [])
    if isinstance(reminders, list):
        for reminder in reminders:
            if not isinstance(reminder, dict):
                continue
            title = reminder.get("title")
            label = title.strip() if isinstance(title, str) and title.strip() else "unnamed reminder"
            target_reminder_id = reminder.get("target_reminder_id")
            if helpers["_reminder_requires_target"](reminder):
                if isinstance(target_reminder_id, str) and target_reminder_id.strip():
                    continue
                unresolved.append(label)
                continue
            if helpers["_reminder_requires_schedule"](reminder):
                unresolved.append(label)
    return unresolved


def run_has_unresolved_task_target(extraction: Dict[str, Any]) -> bool:
    tasks = extraction.get("tasks", []) if isinstance(extraction, dict) else []
    if not isinstance(tasks, list):
        return False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        action = str(task.get("action") or "").lower()
        status = str(task.get("status") or "").lower()
        requires_target = action in {"update", "complete", "archive"} or status in {"done", "archived"}
        if requires_target and not (isinstance(task.get("target_task_id"), str) and task.get("target_task_id").strip()):
            return True
    return False


def run_has_unresolved_reminder_target(extraction: Dict[str, Any], *, helpers: Dict[str, Any]) -> bool:
    reminders = extraction.get("reminders", []) if isinstance(extraction, dict) else []
    if not isinstance(reminders, list):
        return False
    for reminder in reminders:
        if not isinstance(reminder, dict):
            continue
        if helpers["_reminder_requires_target"](reminder) and not (
            isinstance(reminder.get("target_reminder_id"), str) and reminder.get("target_reminder_id").strip()
        ):
            return True
    return False


def run_generic_unresolved_clarification_text(
    extraction: Dict[str, Any],
    unresolved_preview: str,
    *,
    helpers: Dict[str, Any],
) -> str:
    has_task_target = run_has_unresolved_task_target(extraction)
    has_reminder_target = run_has_unresolved_reminder_target(extraction, helpers=helpers)
    if has_task_target and not has_reminder_target:
        return (
            "I need one clarification before applying changes:\n"
            f"• Which existing task do you mean for: {unresolved_preview}?\n\n"
            "Reply with the task name, and I will revise the proposal."
        )
    if has_reminder_target and not has_task_target:
        return (
            "I need one clarification before applying changes:\n"
            f"• Which existing reminder do you mean for: {unresolved_preview}?\n\n"
            "Reply with the reminder name, and I will revise the proposal."
        )
    return (
        "I need one clarification before applying changes:\n"
        f"• I still need one more detail for: {unresolved_preview}.\n\n"
        "Reply with the missing name or time, and I will revise the proposal."
    )


def run_autopilot_decision(message: str, extraction: Dict[str, Any], planned: Any, *, helpers: Dict[str, Any]) -> tuple[bool, str]:
    if not helpers["_has_actionable_entities"](extraction):
        return False, "no_actionable_entities"
    confidence = run_planner_confidence(planned)
    completion_request = run_is_safe_completion_extraction(extraction)
    if completion_request and run_is_safe_completion_extraction(extraction):
        if confidence >= helpers["AUTOPILOT_COMPLETION_CONFIDENCE"]:
            return True, "completion_high_confidence"
        return False, "completion_low_confidence"
    if not isinstance(planned, dict):
        return False, "no_planner_payload"
    if planned.get("needs_confirmation") is True:
        return False, "planner_requires_confirmation"
    if confidence < helpers["AUTOPILOT_ACTION_CONFIDENCE"]:
        return False, "action_low_confidence"
    if run_is_low_risk_action_extraction(extraction):
        return True, "low_risk_action_high_confidence"
    return False, "not_low_risk_action"


def run_build_low_confidence_clarification(extraction: Dict[str, Any], *, helpers: Dict[str, Any]) -> str:
    tasks = extraction.get("tasks", []) if isinstance(extraction, dict) else []
    titles = [
        task.get("title", "").strip()
        for task in tasks
        if isinstance(task, dict) and isinstance(task.get("title"), str) and task.get("title").strip()
    ]
    if titles:
        preview = ", ".join(helpers["escape_html"](title) for title in titles[:3])
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


def run_apply_intent_fallbacks(message: str, extraction: Dict[str, Any], grounding: Dict[str, Any], *, helpers: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(extraction, dict):
        return helpers["_empty_extraction"]()
    extraction.setdefault("tasks", [])
    extraction.setdefault("goals", [])
    extraction.setdefault("problems", [])
    extraction.setdefault("links", [])
    extraction.setdefault("reminders", [])
    if helpers["_has_actionable_entities"](extraction):
        return extraction

    inferred_due_date = run_extract_relative_due_date(message, helpers=helpers)
    if inferred_due_date:
        displayed_match = run_extract_displayed_ordinal_task(message, grounding, helpers=helpers)
        if displayed_match:
            extraction["tasks"] = [
                {
                    "title": displayed_match["title"],
                    "action": "update",
                    "target_task_id": displayed_match["id"],
                    "due_date": inferred_due_date,
                }
            ]
            return extraction
        best_candidate = helpers["_best_task_reference_candidate"](message, grounding, open_only=True)
        if best_candidate:
            extraction["tasks"] = [
                {
                    "title": best_candidate["title"],
                    "action": "update",
                    "target_task_id": best_candidate["id"],
                    "due_date": inferred_due_date,
                }
            ]
            return extraction

    if run_is_completion_like_message(message, helpers=helpers):
        displayed_match = run_extract_displayed_ordinal_task(message, grounding, helpers=helpers)
        if displayed_match:
            extraction["tasks"] = [
                {
                    "title": displayed_match["title"],
                    "action": "complete",
                    "status": "done",
                    "target_task_id": displayed_match["id"],
                }
            ]
            return extraction
        best_candidate = helpers["_best_task_reference_candidate"](message, grounding, open_only=True)
        if best_candidate:
            extraction["tasks"] = [
                {
                    "title": best_candidate["title"],
                    "action": "complete",
                    "status": "done",
                    "target_task_id": best_candidate["id"],
                }
            ]
    return extraction


def run_is_completion_like_message(message: str, *, helpers: Dict[str, Any]) -> bool:
    if not isinstance(message, str) or not message.strip():
        return False
    if "?" in message:
        return False
    normalized = helpers["_normalize_query_text"](message)
    if not normalized:
        return False
    completion_patterns = (
        r"\bdone\b",
        r"\bcomplete(?:d)?\b",
        r"\bfinished\b",
        r"\bhandled\b",
        r"\btook care of\b",
    )
    return any(re.search(pattern, normalized) for pattern in completion_patterns)


def run_extract_displayed_ordinal_task(
    message: str,
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not isinstance(grounding, dict):
        return None
    rows = grounding.get("displayed_task_refs")
    if not isinstance(rows, list) or not rows:
        return None
    normalized = helpers["_normalize_query_text"](message)
    if not normalized:
        return None

    ordinal_tokens = [
        ("second", 2),
        ("2nd", 2),
        ("third", 3),
        ("3rd", 3),
        ("fourth", 4),
        ("4th", 4),
        ("fifth", 5),
        ("5th", 5),
        ("sixth", 6),
        ("6th", 6),
        ("seventh", 7),
        ("7th", 7),
        ("eighth", 8),
        ("8th", 8),
        ("ninth", 9),
        ("9th", 9),
        ("tenth", 10),
        ("10th", 10),
        ("first", 1),
        ("1st", 1),
        ("two", 2),
        ("three", 3),
        ("four", 4),
        ("five", 5),
        ("six", 6),
        ("seven", 7),
        ("eight", 8),
        ("nine", 9),
        ("ten", 10),
        ("one", 1),
    ]
    ordinal = None
    for token, value in ordinal_tokens:
        if re.search(rf"\b{re.escape(token)}\b", normalized):
            ordinal = value
            break
    if ordinal is None:
        match = re.search(r"\bitem\s+(\d{1,2})\b", normalized)
        if match:
            ordinal = int(match.group(1))
    if ordinal is None:
        return None

    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("ordinal") != ordinal:
            continue
        task_id = row.get("id")
        title = row.get("title")
        if isinstance(task_id, str) and task_id.strip() and isinstance(title, str) and title.strip():
            return {"id": task_id.strip(), "title": helpers["_canonical_task_title"](title)}
    return None


def run_extract_relative_due_date(message: str, *, helpers: Dict[str, Any]) -> Optional[str]:
    normalized = helpers["_normalize_query_text"](message)
    if not normalized:
        return None
    today = helpers["_local_today"]()
    if re.search(r"\btomorrow\b", normalized):
        return (today + timedelta(days=1)).isoformat()
    if re.search(r"\b(today|tonight)\b", normalized):
        return today.isoformat()
    if re.search(r"\bnext week\b", normalized):
        return (today + timedelta(days=7)).isoformat()

    weekday_map = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for name, weekday in weekday_map.items():
        if re.search(rf"\b(?:next\s+)?{name}\b", normalized):
            delta_days = (weekday - today.weekday()) % 7
            if delta_days == 0:
                delta_days = 7
            return (today + timedelta(days=delta_days)).isoformat()
    return None


def run_resolve_relative_due_date_overrides(
    message: str,
    extraction: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(extraction, dict):
        return helpers["_empty_extraction"]()
    inferred_due_date = run_extract_relative_due_date(message, helpers=helpers)
    if not inferred_due_date:
        return extraction
    raw_tasks = extraction.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return extraction
    normalized_tasks: List[Any] = []
    updated = False
    for task in raw_tasks:
        if not isinstance(task, dict):
            normalized_tasks.append(task)
            continue
        normalized = dict(task)
        action = str(normalized.get("action") or "").lower()
        if action in {"create", "update"} and not normalized.get("due_date"):
            normalized["due_date"] = inferred_due_date
            updated = True
        normalized_tasks.append(normalized)
    if not updated:
        return extraction
    out = dict(extraction)
    out["tasks"] = normalized_tasks
    return out


def run_actions_to_extraction(actions: Any, *, helpers: Dict[str, Any]) -> Dict[str, Any]:
    extraction: Dict[str, Any] = helpers["_empty_extraction"]()
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
            kind = action.get("kind")
            if isinstance(kind, str) and kind in {"project", "task", "subtask"}:
                task_item["kind"] = kind
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
            parent_task_id = action.get("parent_task_id")
            if isinstance(parent_task_id, str) and parent_task_id.strip():
                task_item["parent_task_id"] = parent_task_id.strip()
            parent_title = action.get("parent_title")
            if isinstance(parent_title, str) and parent_title.strip():
                task_item["parent_title"] = parent_title.strip()
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
                extraction["tasks"].append({"title": title.strip(), "kind": "project"})
        elif entity_type == "problem":
            title = action.get("title")
            if isinstance(title, str) and title.strip():
                extraction["tasks"].append({"title": title.strip(), "kind": "project"})
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
        elif entity_type == "reminder":
            title = action.get("title")
            target_reminder_id = action.get("target_reminder_id")
            if not isinstance(title, str) or not title.strip():
                if isinstance(target_reminder_id, str) and target_reminder_id.strip():
                    title = target_reminder_id.strip()
                else:
                    message = action.get("message") or action.get("notes")
                    if isinstance(message, str) and message.strip():
                        title = message.strip()
            if not isinstance(title, str) or not title.strip():
                continue
            reminder_item: Dict[str, Any] = {"title": title.strip()}
            if isinstance(op, str) and op in {"create", "update", "complete", "dismiss", "cancel", "noop"}:
                reminder_item["action"] = op
                if op == "complete":
                    reminder_item["status"] = "completed"
                elif op == "dismiss":
                    reminder_item["status"] = "dismissed"
                elif op == "cancel":
                    reminder_item["status"] = "canceled"
            status = action.get("status")
            if isinstance(status, str) and status in {"pending", "sent", "completed", "dismissed", "canceled"}:
                reminder_item["status"] = status
            if isinstance(target_reminder_id, str) and target_reminder_id.strip():
                reminder_item["target_reminder_id"] = target_reminder_id.strip()
            message = action.get("message") or action.get("notes")
            if isinstance(message, str) and message.strip():
                reminder_item["message"] = message.strip()
            remind_at = action.get("remind_at")
            if isinstance(remind_at, str) and remind_at.strip():
                reminder_item["remind_at"] = remind_at.strip()
            kind = action.get("kind")
            if isinstance(kind, str) and kind in {"one_off", "follow_up", "recurring"}:
                reminder_item["kind"] = kind
            recurrence_rule = action.get("recurrence_rule")
            if isinstance(recurrence_rule, str) and recurrence_rule.strip():
                reminder_item["recurrence_rule"] = recurrence_rule.strip()
            work_item_id = action.get("work_item_id")
            if isinstance(work_item_id, str) and work_item_id.strip():
                reminder_item["work_item_id"] = work_item_id.strip()
            person_id = action.get("person_id")
            if isinstance(person_id, str) and person_id.strip():
                reminder_item["person_id"] = person_id.strip()
            extraction["reminders"].append(reminder_item)
    return extraction


async def run_get_open_action_draft(user_id: str, chat_id: str, db, *, helpers: Dict[str, Any]):
    now = helpers["_draft_now"]()
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


async def run_create_action_draft(
    db,
    user_id: str,
    chat_id: str,
    message: str,
    extraction: Dict[str, Any],
    request_id: str,
    *,
    helpers: Dict[str, Any],
):
    now = helpers["_draft_now"]()
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
        expires_at=now + timedelta(seconds=helpers["ACTION_DRAFT_TTL_SECONDS"]),
        created_at=now,
        updated_at=now,
    )
    helpers["_draft_set_awaiting_edit_input"](draft, False)
    db.add(draft)
    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="action_draft_created",
            payload_json={"draft_id": draft.id, "chat_id": chat_id},
            created_at=helpers["utc_now"](),
        )
    )
    await db.commit()
    if "_invalidate_today_plan_cache" in helpers:
        try:
            await helpers["_invalidate_today_plan_cache"](user_id, chat_id)
        except Exception as exc:
            helpers["logger"].warning(
                "Failed to invalidate today plan cache after confirming draft %s for user %s chat %s: %s",
                draft.id,
                user_id,
                chat_id,
                exc,
            )
    if "_get_or_create_session" in helpers and "_update_session_state" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="draft",
            active_entity_refs=helpers["_session_state_payload"](session).get("active_entity_refs", []),
            pending_draft_id=draft.id,
            pending_clarification=helpers["_draft_get_clarification_state"](draft),
        )
    return draft


async def run_discard_action_draft(draft, user_id: str, request_id: str, db, *, helpers: Dict[str, Any]) -> None:
    draft.status = "discarded"
    draft.updated_at = helpers["_draft_now"]()
    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="action_draft_discarded",
            payload_json={"draft_id": draft.id},
            created_at=helpers["utc_now"](),
        )
    )
    await db.commit()
    if "_get_or_create_session" in helpers and "_update_session_state" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=draft.chat_id)
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="conversation",
            active_entity_refs=helpers["_session_state_payload"](session).get("active_entity_refs", []),
            pending_draft_id=None,
            pending_clarification=None,
        )


async def run_revise_action_draft(draft, user_id: str, request_id: str, edit_text: str, db, *, helpers: Dict[str, Any]) -> Dict[str, Any]:
    prior_extraction = copy.deepcopy(draft.proposal_json) if isinstance(draft.proposal_json, dict) else {}
    clarification_state = helpers["_draft_get_clarification_state"](draft)
    revised_message = f"{draft.source_message}\n\nUser clarification: {edit_text}".strip()
    grounding = await helpers["_build_extraction_grounding"](
        db=db,
        user_id=user_id,
        chat_id=draft.chat_id,
        message=revised_message,
    )
    clarification_candidates = clarification_state.get("candidates") if isinstance(clarification_state, dict) else None
    clarification_kind = clarification_state.get("kind") if isinstance(clarification_state, dict) else None
    if isinstance(clarification_candidates, list) and clarification_candidates:
        if clarification_kind == "reminder_candidates":
            helpers["_merge_grounding_task_refs"](grounding, "reminders", clarification_candidates)
        else:
            helpers["_merge_grounding_task_refs"](grounding, "recent_task_refs", clarification_candidates)
            helpers["_merge_grounding_task_refs"](grounding, "tasks", clarification_candidates)
    extraction = await helpers["adapter"].extract_structured_updates(revised_message, grounding=grounding)
    extraction = helpers["_apply_intent_fallbacks"](revised_message, extraction, grounding)
    extraction = helpers["_sanitize_completion_extraction"](extraction, grounding)
    extraction = helpers["_sanitize_create_extraction"](extraction)
    extraction = helpers["_sanitize_targeted_task_actions"](revised_message, extraction, grounding)
    extraction = helpers["_sanitize_targeted_reminder_actions"](revised_message, extraction, grounding)
    extraction = helpers["_apply_displayed_task_reference_extraction"](extraction, grounding)
    extraction = helpers["_resolve_relative_due_date_overrides"](revised_message, extraction)
    if isinstance(clarification_candidates, list) and clarification_candidates:
        selected_candidate = helpers["_select_clarification_candidate"](edit_text, clarification_candidates)
        if selected_candidate and (
            not helpers["_has_actionable_entities"](extraction) or helpers["_unresolved_mutation_titles"](extraction)
        ):
            base_extraction = extraction if helpers["_has_actionable_entities"](extraction) else prior_extraction
            if clarification_kind == "reminder_candidates":
                extraction = helpers["_fill_clarified_reminder_target"](base_extraction, selected_candidate)
            else:
                extraction = helpers["_fill_clarified_task_target"](base_extraction, selected_candidate)
    helpers["_validate_extraction_payload"](extraction)
    draft.source_message = revised_message
    draft.proposal_json = extraction
    helpers["_draft_set_awaiting_edit_input"](draft, False)
    if helpers["_has_actionable_entities"](extraction) and not helpers["_unresolved_mutation_titles"](extraction):
        helpers["_draft_set_clarification_state"](draft, None)
    draft.updated_at = helpers["_draft_now"]()
    draft.expires_at = helpers["_draft_now"]() + timedelta(seconds=helpers["ACTION_DRAFT_TTL_SECONDS"])
    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="action_draft_revised",
            payload_json={"draft_id": draft.id},
            created_at=helpers["utc_now"](),
        )
    )
    await db.commit()
    if "_get_or_create_session" in helpers and "_update_session_state" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=draft.chat_id)
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="draft",
            active_entity_refs=helpers["_session_state_payload"](session).get("active_entity_refs", []),
            pending_draft_id=draft.id,
            pending_clarification=helpers["_draft_get_clarification_state"](draft),
        )
    return extraction


async def run_confirm_action_draft(draft, user_id: str, chat_id: str, request_id: str, db, *, helpers: Dict[str, Any]):
    extraction = draft.proposal_json if isinstance(draft.proposal_json, dict) else {}
    inbox_item_id, applied = await helpers["_apply_capture"](
        db=db,
        user_id=user_id,
        chat_id=chat_id,
        source=helpers["settings"].TELEGRAM_DEFAULT_SOURCE,
        message=draft.source_message,
        extraction=extraction,
        request_id=request_id,
        commit=False,
        enqueue_summary=False,
    )
    draft.status = "confirmed"
    draft.updated_at = helpers["_draft_now"]()
    db.add(
        EventLog(
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="action_draft_confirmed",
            payload_json={"draft_id": draft.id},
            created_at=helpers["utc_now"](),
        )
    )
    await db.commit()
    if "_invalidate_today_plan_cache" in helpers:
        try:
            await helpers["_invalidate_today_plan_cache"](user_id, chat_id)
        except Exception as exc:
            helpers["logger"].warning(
                "Failed to invalidate today plan cache after confirming draft %s for user %s chat %s: %s",
                draft.id,
                user_id,
                chat_id,
                exc,
            )
    if "_get_or_create_session" in helpers and "_update_session_state" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="action",
            active_entity_refs=helpers["_session_state_payload"](session).get("active_entity_refs", []),
            pending_draft_id=None,
            pending_clarification=None,
        )
    summary_enqueued = True
    summary_error: Optional[str] = None
    try:
        await helpers["_enqueue_summary_job"](user_id=user_id, chat_id=chat_id, inbox_item_id=inbox_item_id)
    except Exception as exc:
        summary_enqueued = False
        summary_error = str(exc)
        helpers["logger"].error("Failed to enqueue memory summary for draft %s: %s", draft.id, exc)

    if not summary_enqueued:
        db.add(
            EventLog(
                id=str(uuid.uuid4()),
                request_id=request_id,
                user_id=user_id,
                event_type="action_apply_background_enqueue_failure",
                payload_json={
                    "draft_id": draft.id,
                    "summary_enqueued": summary_enqueued,
                    "summary_error": summary_error,
                },
                created_at=helpers["utc_now"](),
            )
        )
        await db.commit()
    return applied
