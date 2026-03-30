import uuid
from datetime import timedelta
from typing import Any, Dict, Optional


def _split_mixed_turn_clauses(text: str) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    if "\n" in text:
        raw_parts = [part.strip() for part in text.splitlines() if part.strip()]
    else:
        import re

        raw_parts = [
            part.strip()
            for part in re.split(
                r"(?<=[.!?])\s+(?=(?:also|and also|then|next|plus|separately)\b)",
                text,
                flags=re.IGNORECASE,
            )
            if part.strip()
        ]
    clauses: list[str] = []
    for part in raw_parts:
        if len(part) < 4:
            continue
        clauses.append(part)
    return clauses


def _looks_like_structured_capture_message(text: str) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped or "?" in stripped:
        return False
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    if lines[0].endswith(":"):
        item_lines = lines[1:]
        return len(item_lines) >= 2 and all(len(line.split()) <= 16 for line in item_lines)
    return len(lines) >= 3 and all(len(line.split()) <= 16 for line in lines)


async def run_handle_telegram_draft_flow(
    chat_id: str,
    text: str,
    client_msg_id: Optional[str],
    user_id: str,
    db,
    *,
    helpers: Dict[str, Any],
) -> None:
    request_id = f"tg_{uuid.uuid4().hex[:8]}"
    session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
    open_draft = await helpers["_get_open_action_draft"](user_id=user_id, chat_id=chat_id, db=db)
    awaiting_edit_input = bool(open_draft and helpers["_draft_is_awaiting_edit_input"](open_draft))
    clarification_state = helpers["_draft_get_clarification_state"](open_draft) if open_draft else None
    await helpers["_update_session_state"](
        db=db,
        session=session,
        current_mode="draft" if open_draft else session.current_mode,
        active_entity_refs=helpers["_session_state_payload"](session).get("active_entity_refs", []),
        pending_draft_id=open_draft.id if open_draft else None,
        pending_clarification=clarification_state,
    )
    session_state = helpers["_session_state_payload"](session)
    turn = await helpers["adapter"].interpret_telegram_turn(
        text,
        context={
            "chat_id": chat_id,
            "has_open_draft": bool(open_draft),
            "has_pending_clarification": bool(clarification_state),
            "session_state": session_state,
        },
    )
    speech_act = turn.get("speech_act") if isinstance(turn, dict) else None
    requested_view = turn.get("view_name") if isinstance(turn, dict) else None
    draft_action = turn.get("draft_action") if isinstance(turn, dict) else None
    draft_edit_text = turn.get("draft_edit_text") if isinstance(turn, dict) else None
    turn_confidence = turn.get("confidence") if isinstance(turn, dict) else None
    rescue_grounding = None
    rescue_planned = None

    db.add(
        helpers["EventLog"](
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="telegram_turn_interpreted",
            payload_json={
                "chat_id": chat_id,
                "speech_act": speech_act,
                "view_name": requested_view,
                "confidence": turn_confidence,
                "has_open_draft": bool(open_draft),
            },
            created_at=helpers["utc_now"](),
        )
    )
    await db.commit()

    if not open_draft and speech_act in {"query", "action", "unknown"}:
        mixed_clauses = _split_mixed_turn_clauses(text)
        if 2 <= len(mixed_clauses) <= 3:
            clause_turns = []
            for clause in mixed_clauses:
                clause_turn = await helpers["adapter"].interpret_telegram_turn(
                    clause,
                    context={
                        "chat_id": chat_id,
                        "has_open_draft": False,
                        "has_pending_clarification": False,
                        "session_state": session_state,
                    },
                )
                clause_turns.append((clause, clause_turn))
            query_clauses = [
                (clause, clause_turn)
                for clause, clause_turn in clause_turns
                if isinstance(clause_turn, dict) and clause_turn.get("speech_act") == "query"
            ]
            action_clauses = [
                (clause, clause_turn)
                for clause, clause_turn in clause_turns
                if isinstance(clause_turn, dict) and clause_turn.get("speech_act") == "action"
            ]
            if (
                len(query_clauses) == 1
                and len(action_clauses) >= 1
                and len(query_clauses) + len(action_clauses) == len(clause_turns)
            ):
                db.add(
                    helpers["EventLog"](
                        id=str(uuid.uuid4()),
                        request_id=request_id,
                        user_id=user_id,
                        event_type="telegram_turn_mixed_split",
                        payload_json={
                            "chat_id": chat_id,
                            "query_clauses": len(query_clauses),
                            "action_clauses": len(action_clauses),
                        },
                        created_at=helpers["utc_now"](),
                    )
                )
                await db.commit()

                query_text, query_turn = query_clauses[0]
                query_view = query_turn.get("view_name") if isinstance(query_turn, dict) else None
                if query_view in {"today", "focus"}:
                    payload, served_from_cache = await helpers["_load_today_plan_payload"](db, user_id, chat_id, require_fresh=True)
                    await helpers["_send_today_plan_view"](
                        db,
                        user_id,
                        chat_id,
                        payload,
                        served_from_cache=served_from_cache,
                        view_name=query_view,
                    )
                elif query_view == "due_today":
                    await helpers["_send_due_today_view"](db, user_id, chat_id)
                elif query_view == "due_next_week":
                    await helpers["_send_due_next_week_view"](db, user_id, chat_id)
                elif query_view == "open_tasks":
                    await helpers["_send_open_task_view"](db, user_id, chat_id)
                elif query_view == "urgent":
                    await helpers["_send_urgent_task_view"](db, user_id, chat_id)
                else:
                    query_grounding = await helpers["_build_extraction_grounding"](
                        db=db,
                        user_id=user_id,
                        chat_id=chat_id,
                        message=query_text,
                    )
                    query_grounding["session_state"] = session_state
                    await helpers["_update_session_state"](
                        db=db,
                        session=session,
                        current_mode="query",
                        active_entity_refs=helpers["_active_entity_refs_from_grounding"](query_grounding),
                        pending_draft_id=None,
                        pending_clarification=None,
                    )
                    response = await helpers["query_ask"](
                        helpers["QueryAskRequest"](chat_id=chat_id, query=query_text),
                        user_id=user_id,
                        db=db,
                    )
                    sent = await helpers["send_message"](
                        chat_id,
                        helpers["format_query_answer"](response.answer, response.follow_up_question),
                    )
                    if isinstance(sent, dict) and sent.get("ok") is True:
                        await helpers["_remember_query_surface_context"](
                            db,
                            user_id=user_id,
                            chat_id=chat_id,
                            response=response,
                            grounding=query_grounding,
                        )

                text = "\n\n".join(clause for clause, _ in action_clauses)
                speech_act = "action"
                requested_view = None
                draft_action = None
                draft_edit_text = None
                turn_confidence = max(
                    float((clause_turn or {}).get("confidence") or 0.0)
                    for _, clause_turn in action_clauses
                    if isinstance(clause_turn, dict)
                )

    if speech_act == "unknown":
        await helpers["send_message"](chat_id, "I could not interpret that confidently. Please rephrase it.")
        return
    if open_draft and clarification_state and draft_action == "confirm":
        await helpers["send_message"](
            chat_id,
            "I still need you to pick the task first. Reply with the task name, or say no to cancel.",
        )
        return
    if open_draft and draft_action == "confirm":
        applied = await helpers["_confirm_action_draft"](
            draft=open_draft,
            user_id=user_id,
            chat_id=chat_id,
            request_id=request_id,
            db=db,
        )
        await helpers["_send_capture_ack"](chat_id, applied)
        return
    if open_draft and draft_action == "discard":
        await helpers["_discard_action_draft"](open_draft, user_id=user_id, request_id=request_id, db=db)
        await helpers["send_message"](chat_id, "Discarded the pending proposal.")
        return
    if open_draft and draft_action == "edit":
        if not isinstance(draft_edit_text, str) or not draft_edit_text.strip():
            helpers["_draft_set_awaiting_edit_input"](open_draft, True)
            open_draft.updated_at = helpers["_draft_now"]()
            open_draft.expires_at = helpers["_draft_now"]() + timedelta(seconds=helpers["ACTION_DRAFT_TTL_SECONDS"])
            await db.commit()
            await helpers["send_message"](
                chat_id,
                "Reply with your changes in one message, and I will revise the proposal.",
            )
            return
        extraction = await helpers["_revise_action_draft"](
            draft=open_draft,
            user_id=user_id,
            request_id=request_id,
            edit_text=draft_edit_text.strip(),
            db=db,
        )
        await helpers["_send_or_edit_draft_preview"](
            chat_id,
            open_draft,
            helpers["_format_action_draft_preview"](extraction),
        )
        await db.commit()
        return
    if open_draft and clarification_state and draft_action is None:
        extraction = await helpers["_revise_action_draft"](
            draft=open_draft,
            user_id=user_id,
            request_id=request_id,
            edit_text=text,
            db=db,
        )
        unresolved_mutations = helpers["_unresolved_mutation_titles"](extraction)
        if unresolved_mutations:
            followup_grounding = await helpers["_build_extraction_grounding"](
                db=db,
                user_id=user_id,
                chat_id=chat_id,
                message=text,
            )
            clarification = helpers["_candidate_task_clarification_info"](text, extraction, followup_grounding)
            if not clarification:
                clarification = helpers["_candidate_reminder_clarification_info"](text, extraction, followup_grounding)
            if clarification:
                helpers["_draft_set_awaiting_edit_input"](open_draft, True)
                helpers["_draft_set_clarification_state"](
                    open_draft,
                    clarification.get("state")
                    or {"kind": "task_candidates", "candidates": clarification.get("candidates", [])},
                )
                open_draft.updated_at = helpers["_draft_now"]()
                open_draft.expires_at = helpers["_draft_now"]() + timedelta(seconds=helpers["ACTION_DRAFT_TTL_SECONDS"])
                await db.commit()
                await helpers["send_message"](chat_id, clarification["text"])
                return
            reminder_schedule = helpers["_missing_reminder_schedule_info"](extraction)
            if reminder_schedule:
                helpers["_draft_set_awaiting_edit_input"](open_draft, True)
                helpers["_draft_set_clarification_state"](open_draft, reminder_schedule.get("state"))
                open_draft.updated_at = helpers["_draft_now"]()
                open_draft.expires_at = helpers["_draft_now"]() + timedelta(seconds=helpers["ACTION_DRAFT_TTL_SECONDS"])
                await db.commit()
                await helpers["send_message"](chat_id, reminder_schedule["text"])
                return
        if not helpers["_has_actionable_entities"](extraction):
            helpers["_draft_set_awaiting_edit_input"](open_draft, True)
            open_draft.updated_at = helpers["_draft_now"]()
            open_draft.expires_at = helpers["_draft_now"]() + timedelta(seconds=helpers["ACTION_DRAFT_TTL_SECONDS"])
            await db.commit()
            await helpers["send_message"](
                chat_id,
                "I still need one more detail. Reply with the exact task name, and I will revise the change.",
            )
            return
        await helpers["_send_or_edit_draft_preview"](
            chat_id,
            open_draft,
            helpers["_format_action_draft_preview"](extraction),
        )
        await db.commit()
        return
    if open_draft and awaiting_edit_input and draft_action is None and speech_act in {"action", "clarification_answer"}:
        extraction = await helpers["_revise_action_draft"](
            draft=open_draft,
            user_id=user_id,
            request_id=request_id,
            edit_text=text,
            db=db,
        )
        await helpers["_send_or_edit_draft_preview"](
            chat_id,
            open_draft,
            helpers["_format_action_draft_preview"](extraction),
        )
        await db.commit()
        return
    if open_draft and draft_action is None and speech_act in {"action", "clarification_answer"} and requested_view is None:
        await helpers["send_message"](
            chat_id,
            "You already have a pending proposal. Reply <code>yes</code>, <code>edit ...</code>, or <code>no</code>.",
        )
        return

    if speech_act == "smalltalk":
        assistant_reply = turn.get("assistant_reply") if isinstance(turn, dict) else None
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="conversation",
            active_entity_refs=session_state.get("active_entity_refs", []),
            pending_draft_id=open_draft.id if open_draft else None,
            pending_clarification=clarification_state,
        )
        await helpers["send_message"](
            chat_id,
            assistant_reply
            if isinstance(assistant_reply, str) and assistant_reply.strip()
            else "Hi. Tell me what changed, or ask what needs attention today.",
        )
        return

    if (
        speech_act == "query"
        and requested_view in {"today", "due_today"}
        and _looks_like_structured_capture_message(text)
    ):
        rescue_grounding = await helpers["_build_extraction_grounding"](
            db=db,
            user_id=user_id,
            chat_id=chat_id,
            message=text,
        )
        rescue_grounding["session_state"] = session_state
        rescue_planned = await helpers["adapter"].plan_actions(
            text,
            context={
                "grounding": rescue_grounding,
                "chat_id": chat_id,
                "turn_interpretation": turn,
                "rescue_mode": "structured_capture",
            },
        )
        if isinstance(rescue_planned, dict) and rescue_planned.get("intent") == "action":
            speech_act = "action"
            requested_view = None

    if requested_view in {"today", "focus"}:
        payload, served_from_cache = await helpers["_load_today_plan_payload"](db, user_id, chat_id, require_fresh=True)
        await helpers["_send_today_plan_view"](
            db,
            user_id,
            chat_id,
            payload,
            served_from_cache=served_from_cache,
            view_name=requested_view,
        )
        return
    if requested_view == "due_today":
        await helpers["_send_due_today_view"](db, user_id, chat_id)
        return
    if requested_view == "due_next_week":
        await helpers["_send_due_next_week_view"](db, user_id, chat_id)
        return
    if requested_view == "open_tasks":
        await helpers["_send_open_task_view"](db, user_id, chat_id)
        return
    if requested_view == "urgent":
        await helpers["_send_urgent_task_view"](db, user_id, chat_id)
        return
    if speech_act == "confirmation":
        await helpers["send_message"](
            chat_id,
            "There is no pending proposal to confirm. Tell me what changed, and I will help.",
        )
        return
    if speech_act == "clarification_answer":
        await helpers["send_message"](
            chat_id,
            "I do not have a pending clarification right now. Say the full change you want, and I will help.",
        )
        return
    if speech_act == "query":
        grounding = await helpers["_build_extraction_grounding"](db=db, user_id=user_id, chat_id=chat_id, message=text)
        grounding["session_state"] = session_state
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="query",
            active_entity_refs=helpers["_active_entity_refs_from_grounding"](grounding),
            pending_draft_id=open_draft.id if open_draft else None,
            pending_clarification=clarification_state,
        )
        response = await helpers["query_ask"](
            helpers["QueryAskRequest"](chat_id=chat_id, query=text),
            user_id=user_id,
            db=db,
        )
        sent = await helpers["send_message"](
            chat_id,
            helpers["format_query_answer"](response.answer, response.follow_up_question),
        )
        if not (isinstance(sent, dict) and sent.get("ok") is True):
            return
        await helpers["_remember_query_surface_context"](
            db,
            user_id=user_id,
            chat_id=chat_id,
            response=response,
            grounding=grounding,
        )
        return

    grounding = rescue_grounding or await helpers["_build_extraction_grounding"](
        db=db,
        user_id=user_id,
        chat_id=chat_id,
        message=text,
    )
    grounding["session_state"] = session_state
    await helpers["_update_session_state"](
        db=db,
        session=session,
        current_mode="action",
        active_entity_refs=helpers["_active_entity_refs_from_grounding"](grounding),
        pending_draft_id=open_draft.id if open_draft else None,
        pending_clarification=clarification_state,
    )
    planned = rescue_planned or await helpers["adapter"].plan_actions(
        text,
        context={"grounding": grounding, "chat_id": chat_id},
    )
    intent = "action"
    actions = planned.get("actions") if isinstance(planned, dict) else None

    db.add(
        helpers["EventLog"](
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
            created_at=helpers["utc_now"](),
        )
    )
    await db.commit()

    planner_actions_valid = (
        isinstance(planned, dict)
        and planned.get("intent") == "action"
        and isinstance(actions, list)
        and len(actions) > 0
    )
    used_extract_fallback = False
    if planner_actions_valid:
        extraction = helpers["_actions_to_extraction"](actions)
        if not helpers["_has_actionable_entities"](extraction):
            used_extract_fallback = True
            db.add(
                helpers["EventLog"](
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    event_type="action_extract_fallback_used",
                    payload_json={"chat_id": chat_id, "reason": "planner_actions_unusable"},
                    created_at=helpers["utc_now"](),
                )
            )
            await db.commit()
            extraction = await helpers["adapter"].extract_structured_updates(text, grounding=grounding)
        else:
            requested_change_count = helpers["_estimated_requested_change_count"](text)
            extraction_mutation_count = helpers["_extraction_mutation_count"](extraction)
            if requested_change_count >= 2 and extraction_mutation_count < requested_change_count:
                recovery_extraction = await helpers["adapter"].extract_structured_updates(text, grounding=grounding)
                recovery_count = helpers["_extraction_mutation_count"](recovery_extraction)
                if recovery_count > extraction_mutation_count:
                    used_extract_fallback = True
                    db.add(
                        helpers["EventLog"](
                            id=str(uuid.uuid4()),
                            request_id=request_id,
                            user_id=user_id,
                            event_type="action_extract_fallback_used",
                            payload_json={
                                "chat_id": chat_id,
                                "reason": "planner_actions_incomplete_multi_action",
                            },
                            created_at=helpers["utc_now"](),
                        )
                    )
                    await db.commit()
                    extraction = recovery_extraction
    else:
        used_extract_fallback = True
        db.add(
            helpers["EventLog"](
                id=str(uuid.uuid4()),
                request_id=request_id,
                user_id=user_id,
                event_type="action_extract_fallback_used",
                payload_json={"chat_id": chat_id, "reason": "planner_invalid_or_empty"},
                created_at=helpers["utc_now"](),
            )
        )
        await db.commit()
        extraction = await helpers["adapter"].extract_structured_updates(text, grounding=grounding)

    if used_extract_fallback:
        critic = {
            "approved": True,
            "issues": [],
            "skipped": True,
            "reason": "extract_fallback",
        }
    else:
        critic = await helpers["adapter"].critique_actions(
            text,
            context={"grounding": grounding, "chat_id": chat_id},
            proposal={"intent": intent, "actions": actions},
        )
    db.add(
        helpers["EventLog"](
            id=str(uuid.uuid4()),
            request_id=request_id,
            user_id=user_id,
            event_type="telegram_action_critic_result",
            payload_json={
                "chat_id": chat_id,
                "approved": critic.get("approved"),
                "issues": critic.get("issues"),
                "skipped": critic.get("skipped"),
                "reason": critic.get("reason"),
            },
            created_at=helpers["utc_now"](),
        )
    )
    await db.commit()

    revised_actions = critic.get("revised_actions") if isinstance(critic, dict) else None
    if isinstance(revised_actions, list):
        revised_extraction = helpers["_actions_to_extraction"](revised_actions)
        if helpers["_has_actionable_entities"](revised_extraction):
            extraction = revised_extraction
        else:
            db.add(
                helpers["EventLog"](
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    event_type="action_extract_fallback_used",
                    payload_json={"chat_id": chat_id, "reason": "critic_revised_actions_unusable"},
                    created_at=helpers["utc_now"](),
                )
            )
            await db.commit()
    if isinstance(critic, dict) and critic.get("approved") is False:
        issues = critic.get("issues") if isinstance(critic.get("issues"), list) else []
        issue_text = "\n".join([f"• {helpers['escape_html'](str(i))}" for i in issues[:3]]) if issues else "• Proposal needs clarification."
        await helpers["send_message"](
            chat_id,
            "I need one clarification before applying changes:\n"
            f"{issue_text}\n\n"
            "Reply with more detail, and I will revise the proposal.",
        )
        return

    estimated_requested_change_count = helpers["_estimated_requested_change_count"](text)
    extraction_mutation_count = helpers["_extraction_mutation_count"](extraction)
    if used_extract_fallback or (
        estimated_requested_change_count >= 2
        and extraction_mutation_count < estimated_requested_change_count
    ):
        extraction = helpers["_apply_intent_fallbacks"](text, extraction, grounding)
    extraction = helpers["_sanitize_completion_extraction"](extraction, grounding)
    extraction = helpers["_sanitize_create_extraction"](extraction)
    extraction = helpers["_sanitize_targeted_task_actions"](text, extraction, grounding)
    extraction = helpers["_sanitize_targeted_reminder_actions"](text, extraction, grounding)
    extraction = helpers["_apply_displayed_task_reference_extraction"](extraction, grounding)
    extraction = helpers["_resolve_relative_due_date_overrides"](text, extraction)
    extraction_mutation_count = helpers["_extraction_mutation_count"](extraction)
    completion_request = helpers["_is_safe_completion_extraction"](extraction)
    unresolved_mutations = helpers["_unresolved_mutation_titles"](extraction)
    if (
        estimated_requested_change_count >= 2
        and extraction_mutation_count > 0
        and extraction_mutation_count < estimated_requested_change_count
    ):
        await helpers["send_message"](
            chat_id,
            "I think I only captured part of that request.\n"
            f"I found {extraction_mutation_count} change(s), but your message looks like {estimated_requested_change_count} requested changes.\n\n"
            "Please split that into shorter messages, or rephrase the missing part.",
        )
        return
    if unresolved_mutations:
        clarification_info = helpers["_candidate_task_clarification_info"](text, extraction, grounding)
        if not clarification_info:
            clarification_info = helpers["_candidate_reminder_clarification_info"](text, extraction, grounding)
        if clarification_info:
            await helpers["_stage_clarification_draft"](
                db=db,
                user_id=user_id,
                chat_id=chat_id,
                message=text,
                extraction=extraction,
                request_id=request_id,
                clarification_text=clarification_info["text"],
                clarification_candidates=clarification_info.get("candidates"),
                clarification_state=clarification_info.get("state"),
            )
            return
        reminder_schedule = helpers["_missing_reminder_schedule_info"](extraction)
        if reminder_schedule:
            await helpers["_stage_clarification_draft"](
                db=db,
                user_id=user_id,
                chat_id=chat_id,
                message=text,
                extraction=extraction,
                request_id=request_id,
                clarification_text=reminder_schedule["text"],
                clarification_state=reminder_schedule.get("state"),
            )
            return
        unresolved_preview = ", ".join(helpers["escape_html"](t) for t in unresolved_mutations[:3])
        await helpers["_stage_clarification_draft"](
            db=db,
            user_id=user_id,
            chat_id=chat_id,
            message=text,
            extraction=extraction,
            request_id=request_id,
            clarification_text=helpers["_generic_unresolved_clarification_text"](extraction, unresolved_preview),
        )
        return
    if not helpers["_has_actionable_entities"](extraction):
        if completion_request:
            clarification_info = helpers["_candidate_task_clarification_info"](text, extraction, grounding)
            if clarification_info:
                await helpers["_stage_clarification_draft"](
                    db=db,
                    user_id=user_id,
                    chat_id=chat_id,
                    message=text,
                    extraction=extraction,
                    request_id=request_id,
                    clarification_text=clarification_info["text"],
                    clarification_candidates=clarification_info.get("candidates"),
                )
                return
            await helpers["send_message"](
                chat_id,
                "I could not find open matching tasks to complete.\n"
                "Say <code>show open tasks</code> if you want the current list, then try again.",
            )
            return
        if used_extract_fallback:
            db.add(
                helpers["EventLog"](
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    event_type="action_extract_fallback_used",
                    payload_json={"chat_id": chat_id, "reason": "planner_and_extract_empty"},
                    created_at=helpers["utc_now"](),
                )
            )
            await db.commit()
        clarification_info = helpers["_candidate_task_clarification_info"](text, extraction, grounding)
        if clarification_info:
            await helpers["_stage_clarification_draft"](
                db=db,
                user_id=user_id,
                chat_id=chat_id,
                message=text,
                extraction=extraction,
                request_id=request_id,
                clarification_text=clarification_info["text"],
                clarification_candidates=clarification_info.get("candidates"),
            )
            return
        await helpers["send_message"](
            chat_id,
            "I did not find clear actions to apply yet.\n"
            "Reply with more details, or ask a question directly.",
        )
        return

    helpers["_validate_extraction_payload"](extraction)
    planner_confidence = helpers["_planner_confidence"](planned)
    explicit_displayed_mutation = helpers["_is_explicit_displayed_reference_mutation"](text, extraction, grounding)
    explicit_recent_named_mutation = helpers["_is_explicit_recent_named_reference_mutation"](text, extraction, grounding)
    if planner_confidence < helpers["CLARIFY_ACTION_CONFIDENCE"] and not explicit_displayed_mutation and not explicit_recent_named_mutation:
        await helpers["send_message"](chat_id, helpers["_build_low_confidence_clarification"](extraction))
        return
    auto_apply, auto_reason = helpers["_autopilot_decision"](text, extraction, planned)
    db.add(
        helpers["EventLog"](
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
            created_at=helpers["utc_now"](),
        )
    )
    await db.commit()
    if auto_apply:
        _, applied = await helpers["_apply_capture"](
            db=db,
            user_id=user_id,
            chat_id=chat_id,
            source=helpers["settings"].TELEGRAM_DEFAULT_SOURCE,
            message=text,
            extraction=extraction,
            request_id=request_id,
            client_msg_id=client_msg_id,
            commit=True,
            enqueue_summary=True,
        )
        await helpers["_send_capture_ack"](chat_id, applied)
        return

    draft = await helpers["_create_action_draft"](
        db=db,
        user_id=user_id,
        chat_id=chat_id,
        message=text,
        extraction=extraction,
        request_id=request_id,
    )
    await helpers["_send_or_edit_draft_preview"](
        chat_id,
        draft,
        helpers["_format_action_draft_preview"](extraction),
    )
    await db.commit()
