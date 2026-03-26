import asyncio
import json
import logging
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

import httpx

from common.config import settings
from common.planner import render_fallback_plan_explanation

logger = logging.getLogger(__name__)


class LLMAdapter:
    @staticmethod
    def _normalize_extract_task_item(candidate: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(candidate, dict):
            return None
        title = candidate.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
        item: Dict[str, Any] = {"title": title.strip()}
        kind = candidate.get("kind")
        if isinstance(kind, str) and kind in {"project", "task", "subtask"}:
            item["kind"] = kind
        action = candidate.get("action")
        if isinstance(action, str) and action in {"create", "update", "complete", "archive", "noop"}:
            item["action"] = action
            if action == "complete":
                item["status"] = "done"
            elif action == "archive":
                item["status"] = "archived"
        status = candidate.get("status")
        if isinstance(status, str) and status in {"open", "blocked", "done", "archived"}:
            item["status"] = status
        notes = candidate.get("notes")
        if isinstance(notes, str) and notes.strip():
            item["notes"] = notes.strip()
        priority = candidate.get("priority")
        if isinstance(priority, int) and 1 <= priority <= 4:
            item["priority"] = priority
        impact_score = candidate.get("impact_score")
        if isinstance(impact_score, int) and 1 <= impact_score <= 5:
            item["impact_score"] = impact_score
        urgency_score = candidate.get("urgency_score")
        if isinstance(urgency_score, int) and 1 <= urgency_score <= 5:
            item["urgency_score"] = urgency_score
        due_date = candidate.get("due_date")
        if isinstance(due_date, str):
            try:
                parsed = date.fromisoformat(due_date.strip()[:10])
                item["due_date"] = parsed.isoformat()
            except ValueError:
                pass
        target_task_id = candidate.get("target_task_id")
        if isinstance(target_task_id, str) and target_task_id.strip():
            item["target_task_id"] = target_task_id.strip()
        parent_task_id = candidate.get("parent_task_id")
        if isinstance(parent_task_id, str) and parent_task_id.strip():
            item["parent_task_id"] = parent_task_id.strip()
        parent_title = candidate.get("parent_title")
        if isinstance(parent_title, str) and parent_title.strip():
            item["parent_title"] = parent_title.strip()
        confidence = candidate.get("confidence")
        if isinstance(confidence, (int, float)):
            item["confidence"] = float(confidence)
        return item

    @staticmethod
    def _normalize_extract_title_item(candidate: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(candidate, dict):
            return None
        title = candidate.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
        return {"title": title.strip()}

    @staticmethod
    def _normalize_extract_link_item(candidate: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(candidate, dict):
            return None
        link = {
            "from_type": candidate.get("from_type"),
            "from_title": candidate.get("from_title"),
            "to_type": candidate.get("to_type"),
            "to_title": candidate.get("to_title"),
            "link_type": candidate.get("link_type"),
        }
        if all(isinstance(v, str) and v.strip() for v in link.values()):
            return {k: v.strip() for k, v in link.items()}
        return None

    @staticmethod
    def _normalize_extract_reminder_item(candidate: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(candidate, dict):
            return None
        title = candidate.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
        item: Dict[str, Any] = {"title": title.strip()}
        action = candidate.get("action")
        if isinstance(action, str) and action in {"create", "update", "complete", "dismiss", "cancel", "noop"}:
            item["action"] = action
            if action == "complete":
                item["status"] = "completed"
            elif action == "dismiss":
                item["status"] = "dismissed"
            elif action == "cancel":
                item["status"] = "canceled"
        status = candidate.get("status")
        if isinstance(status, str) and status in {"pending", "sent", "completed", "dismissed", "canceled"}:
            item["status"] = status
        message = candidate.get("message")
        if isinstance(message, str) and message.strip():
            item["message"] = message.strip()
        remind_at = candidate.get("remind_at")
        if isinstance(remind_at, str) and remind_at.strip():
            text = remind_at.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                item["remind_at"] = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except ValueError:
                pass
        kind = candidate.get("kind")
        if isinstance(kind, str) and kind in {"one_off", "follow_up", "recurring"}:
            item["kind"] = kind
        recurrence_rule = candidate.get("recurrence_rule")
        if isinstance(recurrence_rule, str) and recurrence_rule.strip():
            item["recurrence_rule"] = recurrence_rule.strip()
        target_reminder_id = candidate.get("target_reminder_id")
        if isinstance(target_reminder_id, str) and target_reminder_id.strip():
            item["target_reminder_id"] = target_reminder_id.strip()
        work_item_id = candidate.get("work_item_id")
        if isinstance(work_item_id, str) and work_item_id.strip():
            item["work_item_id"] = work_item_id.strip()
        person_id = candidate.get("person_id")
        if isinstance(person_id, str) and person_id.strip():
            item["person_id"] = person_id.strip()
        return item

    @staticmethod
    def _normalize_usage(candidate: Any) -> Optional[Dict[str, int]]:
        if not isinstance(candidate, dict):
            return None
        usage = {}
        mapping = {
            "input_tokens": ("input_tokens", "prompt_tokens"),
            "output_tokens": ("output_tokens", "completion_tokens"),
            "cached_input_tokens": ("cached_input_tokens", "prompt_tokens_details.cached_tokens"),
        }
        for normalized_key, provider_keys in mapping.items():
            value = None
            for key in provider_keys:
                value = LLMAdapter._deep_get(candidate, key)
                if isinstance(value, int) and value >= 0:
                    break
                value = None
            if isinstance(value, int) and value >= 0:
                usage[normalized_key] = value
        return usage or None

    @staticmethod
    def _deep_get(payload: Any, path: str) -> Any:
        cur = payload
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    def _model_for(self, operation: str) -> str:
        if operation == "extract":
            return settings.LLM_MODEL_EXTRACT
        if operation in {"action_plan", "action_critic", "telegram_turn"}:
            return settings.LLM_MODEL_EXTRACT
        if operation == "query":
            return settings.LLM_MODEL_QUERY
        if operation == "plan":
            return settings.LLM_MODEL_PLAN
        if operation == "summarize":
            return settings.LLM_MODEL_SUMMARIZE
        raise ValueError(f"Unsupported operation: {operation}")

    def _base_url(self) -> str:
        base = settings.LLM_API_BASE_URL.strip()
        if not base:
            raise RuntimeError("LLM_API_BASE_URL is not configured")
        return base.rstrip("/")

    async def _post_with_retry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        retries = max(0, settings.LLM_MAX_RETRIES)
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{self._base_url()}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {settings.LLM_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, dict):
                        raise ValueError("Provider response is not a JSON object")
                    return body
            except (httpx.RequestError, httpx.HTTPStatusError, httpx.TimeoutException, ValueError) as exc:
                last_error = exc
                if attempt >= retries:
                    break
                delay = max(0.0, settings.LLM_RETRY_BACKOFF_SECONDS) * (2 ** attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _extract_content(payload: Dict[str, Any]) -> Any:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Provider response missing choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise ValueError("Provider choice is invalid")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ValueError("Provider message is invalid")
        content = message.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    text_value = part.get("text")
                    if isinstance(text_value, str):
                        parts.append(text_value)
            content = "\n".join(parts).strip()
        return content

    @staticmethod
    def _parse_content_object(content: Any) -> Dict[str, Any]:
        if isinstance(content, dict):
            return content
        if not isinstance(content, str):
            raise ValueError("Provider content is not JSON")
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Parsed provider content is not an object")
        return parsed

    def _build_payload(self, operation: str, prompt: str, user_text: str) -> Dict[str, Any]:
        return {
            "model": self._model_for(operation),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "Return only valid JSON. Do not include markdown fences.",
                },
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ],
        }

    async def _invoke_operation(self, operation: str, prompt: str, user_text: str) -> Dict[str, Any]:
        response = await self._post_with_retry(self._build_payload(operation, prompt, user_text))
        content_obj = self._parse_content_object(self._extract_content(response))
        usage = self._normalize_usage(response.get("usage"))
        if usage:
            content_obj["usage"] = usage
        return content_obj

    @staticmethod
    def _normalize_project_task_item(candidate: Any) -> Optional[Dict[str, Any]]:
        item = LLMAdapter._normalize_extract_title_item(candidate)
        if item is None:
            return None
        normalized: Dict[str, Any] = {"title": item["title"], "kind": "project"}
        description = candidate.get("description") if isinstance(candidate, dict) else None
        if isinstance(description, str) and description.strip():
            normalized["notes"] = description.strip()
        return normalized

    @staticmethod
    def _normalize_extract_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        task_actions = payload.get("task_actions")
        if isinstance(task_actions, list):
            tasks = []
            for candidate in task_actions:
                if not isinstance(candidate, dict):
                    continue
                normalized = LLMAdapter._normalize_extract_task_item(candidate)
                if normalized is not None:
                    tasks.append(normalized)
            normalized = {
                "tasks": tasks,
                "goals": [],
                "problems": [],
                "links": [],
                "reminders": [],
            }
        elif all(isinstance(payload.get(k), list) for k in ("tasks", "goals", "problems", "links")):
            tasks = [
                item
                for item in (
                    LLMAdapter._normalize_extract_task_item(task)
                    for task in payload.get("tasks", [])
                )
                if item is not None
            ]
            tasks.extend(
                item
                for item in (
                    LLMAdapter._normalize_project_task_item(goal)
                    for goal in payload.get("goals", [])
                )
                if item is not None
            )
            tasks.extend(
                item
                for item in (
                    LLMAdapter._normalize_project_task_item(problem)
                    for problem in payload.get("problems", [])
                )
                if item is not None
            )
            links = [
                item
                for item in (
                    LLMAdapter._normalize_extract_link_item(link)
                    for link in payload.get("links", [])
                )
                if item is not None
            ]
            reminders = [
                item
                for item in (
                    LLMAdapter._normalize_extract_reminder_item(reminder)
                    for reminder in payload.get("reminders", [])
                )
                if item is not None
            ]
            normalized = {"tasks": tasks, "goals": [], "problems": [], "links": links, "reminders": reminders}
        else:
            proposals = payload.get("proposals")
            if not isinstance(proposals, dict):
                raise ValueError("Missing extract proposals")
            tasks = []
            for task in proposals.get("tasks", []):
                if not isinstance(task, dict):
                    continue
                if task.get("action") == "ignore":
                    continue
                title = task.get("content")
                if not isinstance(title, str) or not title.strip():
                    continue
                raw_status = task.get("status")
                status = "done" if raw_status == "closed" else "open"
                item = {"title": title.strip(), "status": status}
                priority = task.get("priority")
                if isinstance(priority, int):
                    item["priority"] = priority
                tasks.append(item)
            for goal in proposals.get("goals", []):
                if isinstance(goal, dict) and goal.get("action") != "ignore" and isinstance(goal.get("title"), str):
                    tasks.append({"title": goal["title"].strip(), "kind": "project"})
            for problem in proposals.get("problems", []):
                if isinstance(problem, dict) and problem.get("action") != "ignore" and isinstance(problem.get("title"), str):
                    tasks.append({"title": problem["title"].strip(), "kind": "project"})
            links = []
            for link in proposals.get("links", []):
                if not isinstance(link, dict):
                    continue
                from_ref = link.get("from") or {}
                to_ref = link.get("to") or {}
                from_key = from_ref.get("key")
                to_key = to_ref.get("key")
                relation = link.get("relation")
                if not all(isinstance(v, str) and v.strip() for v in (from_key, to_key, relation)):
                    continue
                links.append(
                    {
                        "from_type": "task",
                        "from_title": from_key.strip(),
                        "to_type": "goal",
                        "to_title": to_key.strip(),
                        "link_type": relation.strip(),
                    }
                )
            reminders = []
            normalized = {"tasks": tasks, "goals": [], "problems": [], "links": links, "reminders": reminders}

        for key in ("tasks", "goals", "problems", "links", "reminders"):
            value = normalized.get(key, [])
            if not isinstance(value, list):
                raise ValueError(f"Extract field {key} is not a list")
            normalized[key] = value
        return normalized

    @staticmethod
    def _normalize_query_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        answer = payload.get("answer")
        confidence = payload.get("confidence")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Query payload missing answer")
        if not isinstance(confidence, (int, float)):
            raise ValueError("Query payload missing confidence")
        normalized = {
            "schema_version": "query.v1",
            "mode": "query",
            "answer": answer.strip(),
            "confidence": float(confidence),
        }
        for key in ("highlights", "citations", "suggested_actions", "surfaced_entity_ids"):
            value = payload.get(key)
            if isinstance(value, list):
                normalized[key] = value
        follow_up = payload.get("follow_up_question")
        if isinstance(follow_up, str):
            normalized["follow_up_question"] = follow_up
        return normalized

    @staticmethod
    def _normalize_turn_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        speech_act = payload.get("speech_act")
        if speech_act not in {"smalltalk", "query", "action", "confirmation", "clarification_answer", "unknown"}:
            raise ValueError("Turn payload missing valid speech_act")
        normalized: Dict[str, Any] = {"speech_act": speech_act}
        view_name = payload.get("view_name")
        if isinstance(view_name, str):
            normalized_view = view_name.strip().lower()
            if normalized_view in {"today", "due_today", "due_next_week", "focus", "urgent", "open_tasks"}:
                normalized["view_name"] = normalized_view
        draft_action = payload.get("draft_action")
        if isinstance(draft_action, str):
            normalized_action = draft_action.strip().lower()
            if normalized_action in {"confirm", "discard", "edit"}:
                normalized["draft_action"] = normalized_action
        draft_edit_text = payload.get("draft_edit_text")
        if isinstance(draft_edit_text, str) and draft_edit_text.strip():
            normalized["draft_edit_text"] = draft_edit_text.strip()
        confidence = payload.get("confidence")
        if isinstance(confidence, (int, float)):
            normalized["confidence"] = float(confidence)
        reply = payload.get("assistant_reply")
        if isinstance(reply, str) and reply.strip():
            normalized["assistant_reply"] = reply.strip()
        return normalized

    @staticmethod
    def _fallback_turn_interpretation(message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"speech_act": "unknown", "confidence": 0.0}

    async def extract_structured_updates(self, message: str, grounding: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        fallback = {"tasks": [], "goals": [], "problems": [], "links": [], "reminders": []}
        prompt = (
            "Operation: extract.\n"
            "Convert user text into JSON object with keys tasks/goals/problems/links/reminders.\n"
            "Use tasks for all normal local-first work items, including projects and subtasks. If the user talks about a goal or problem, represent it as a project-shaped task instead of using separate goal/problem buckets.\n"
            "Prefer updating/completing existing tasks from grounding before creating new ones.\n"
            "Prefer updating existing reminders from grounding.reminders before creating new ones.\n"
            "Each task supports optional action=create|update|complete|archive|noop, optional target_task_id, optional kind=project|task|subtask, and optional parent_task_id or parent_title for explicit subtask creation.\n"
            "Each reminder supports optional action=create|update|complete|dismiss|cancel|noop, optional target_reminder_id, optional message, optional remind_at, optional kind, and optional recurrence_rule.\n"
            "Task fields may include notes, priority (1 highest, 4 lowest), impact_score (1-5), urgency_score (1-5), due_date.\n"
            "Reminder create actions should include remind_at as an ISO datetime when the user provides a schedule.\n"
            "When dates are explicit or relative (for example tomorrow/next week/tonight), include ISO due_date (YYYY-MM-DD) resolved against grounding.current_date_local and grounding.timezone (fallback grounding.current_date_utc).\n"
            "Phrases like 'same day as the Vanguard task', 'same date as that project', or 'due the same day as X' mean due-date alignment with the referenced task, not completion intent, even if the sentence also includes the word done.\n"
            "When the user asks for a reminder at a specific time or relative time, include remind_at as an ISO datetime resolved against grounding.current_datetime_local and grounding.timezone (fallback grounding.current_datetime_utc).\n"
            "Do not create wrapper task titles like Move 'X' to today or Set X for next week; represent the real task X and use update metadata like due_date instead.\n"
            "If the user explicitly asks to create subtasks, break something into subtasks, or make a checklist, return one parent item first and then child items with kind=subtask and parent_task_id or parent_title.\n"
            "If the user explicitly asks to turn an existing task into a project, use action=update with target_task_id and kind=project.\n"
            "Question-form requests like 'can you delete the burpee task?' or 'could you move that to tomorrow?' are still action intent, not query intent.\n"
            "Completion statements like 'the Tuesday dinner plan is done', 'finished that already', or 'Amy handled that' are also action intent when they refer to a task.\n"
            "Status updates about a recent reminder being handled or resolved, such as 'we checked on Patrick, he's alright', are action intent and should usually complete or dismiss that reminder.\n"
            "If grounding.displayed_task_refs includes ordinal items from the latest /today or /focus list, resolve phrases like first task, second one, or item 3 against those task ids.\n"
            "If grounding.recent_task_refs includes recently discussed tasks from the assistant's latest answer, use those grounded task ids for named follow-ups like the burpee task, the backpack item, or that apartment task.\n"
            "If grounding.recent_reminder_refs includes recently discussed reminders, use those grounded reminder ids for follow-ups like that reminder, the payroll reminder, or move it to tomorrow.\n"
            "If grounding.session_state includes active_entity_refs or a pending clarification, use that session state to resolve short follow-ups like that one, move it to tomorrow, or change it to Wednesday.\n"
            "If user implies completion/cancellation, prefer action=complete/archive with status done/archived.\n"
            "If grounding includes clarification candidates from a prior unresolved turn, treat short replies like 'the one that says register' or 'that one' as clarification answers, not standalone queries.\n"
            "If the user gives multiple action clauses in one message, return multiple grounded task actions when appropriate.\n"
            "Do not create near-duplicate tasks when a grounded candidate is plausible.\n"
            "Return only JSON."
        )
        try:
            payload = {"message": message}
            if isinstance(grounding, dict):
                payload["grounding"] = grounding
            raw = await self._invoke_operation("extract", prompt, json.dumps(payload, ensure_ascii=True))
            usage = self._normalize_usage(raw.get("usage"))
            normalized = self._normalize_extract_payload(raw)
            if usage:
                normalized["usage"] = usage
            return normalized
        except Exception as exc:
            logger.warning("extract_structured_updates fallback: %s: %s", type(exc).__name__, exc)
            return fallback

    async def interpret_telegram_turn(self, message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        fallback = self._fallback_turn_interpretation(message, context)
        prompt = (
            "Operation: telegram_turn.\n"
            "Classify a Telegram message before any read or write side effects.\n"
            "Return JSON with keys speech_act, optional view_name, optional draft_action, optional draft_edit_text, optional confidence, and optional assistant_reply.\n"
            "speech_act must be one of: smalltalk, query, action, confirmation, clarification_answer, unknown.\n"
            "view_name may be omitted or one of: today, due_today, due_next_week, focus, urgent, open_tasks.\n"
            "Use action when the user is trying to change state, including polite question forms and conversational completion statements.\n"
            "Messages that provide a heading followed by a multi-line list of tasks or errands are action/capture, not query, even if the heading mentions today.\n"
            "Status updates about a recent reminder being handled or resolved are also action intent, not query intent.\n"
            "Use query when the user is asking for information.\n"
            "Use confirmation for yes/no/apply/cancel style replies to a pending proposal.\n"
            "Use clarification_answer for short disambiguation replies to a previous question, such as 'the one that says register' or 'that one'.\n"
            "If context.has_open_draft is true and the user wants to revise the pending proposal, set draft_action=edit.\n"
            "If they include the revision in the same message, also include draft_edit_text with only the revision content.\n"
            "If context.has_open_draft is true and the user is accepting or rejecting the pending proposal, set draft_action to confirm or discard.\n"
            "If the message is asking for a deterministic agenda/list view, set view_name accordingly.\n"
            "If context.session_state includes active_entity_refs or a pending clarification, use that session state to interpret follow-ups like that one, change it to Wednesday, or move it to tomorrow.\n"
            "Use today for today's agenda, due_today when the user explicitly asks what is due today or what remains due today, due_next_week when the user explicitly asks what is due next week, urgent for high-priority items, open_tasks for listing currently open tasks, and focus only if the user explicitly asks for top priorities.\n"
            "assistant_reply should only be included for smalltalk, and should be brief.\n"
            "Use unknown only if the message cannot be classified confidently from the provided context.\n"
            "Return only JSON."
        )
        try:
            payload: Dict[str, Any] = {"message": message}
            if isinstance(context, dict):
                payload["context"] = context
            raw = await self._invoke_operation("telegram_turn", prompt, json.dumps(payload, ensure_ascii=True))
            normalized = self._normalize_turn_payload(raw)
            usage = self._normalize_usage(raw.get("usage"))
            if usage:
                normalized["usage"] = usage
            return normalized
        except Exception as exc:
            logger.warning("interpret_telegram_turn fallback: %s", type(exc).__name__)
            return fallback

    async def plan_actions(self, message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        fallback = {
            "intent": "query" if "?" in (message or "") else "action",
            "scope": "single",
            "actions": [],
            "confidence": 0.0,
            "needs_confirmation": True,
        }
        prompt = (
            "Operation: action_plan.\n"
            "Given user message and context, decide if this is query or action intent.\n"
            "Return JSON with keys: intent, scope, actions, confidence, needs_confirmation.\n"
            "intent must be query or action.\n"
            "scope must be one of single|subset|all_open|all_matching.\n"
            "actions is an array of objects with entity_type/task-goal-problem-reminder, action, optional title, optional target_task_id, optional parent_task_id, optional parent_title, optional target_reminder_id, optional status, optional notes, optional message, optional priority (1 highest, 4 lowest), optional impact_score (1-5), optional urgency_score (1-5), optional due_date, optional remind_at, optional recurrence_rule, optional kind.\n"
            "Prefer entity_type=task with kind=project|task|subtask for normal local-first work. If the user describes a goal or problem, model it as a project-shaped task instead of using separate goal/problem entities.\n"
            "A heading followed by a multi-line list of tasks or errands is action intent to create or update work items, not query intent, even if the heading mentions today.\n"
            "Resolve relative dates against context.grounding.current_date_local and context.grounding.timezone (fallback context.grounding.current_date_utc) and output due_date as YYYY-MM-DD.\n"
            "Phrases like 'same day as the Vanguard task', 'same date as that project', or 'due the same day as X' mean due-date alignment with the referenced task, not completion intent, even if the sentence also includes the word done.\n"
            "Resolve reminder times against context.grounding.current_datetime_local and context.grounding.timezone (fallback context.grounding.current_datetime_utc) and output remind_at as ISO datetime.\n"
            "Do not create wrapper task titles like Move 'X' to today or Set X for next week; represent the real task X and use update metadata like due_date instead.\n"
            "If the user explicitly asks to create subtasks or a checklist, return one parent item first and then child actions with kind=subtask and parent_task_id or parent_title.\n"
            "If the user explicitly asks to make an existing task a project, use action=update with target_task_id and kind=project.\n"
            "Question-form requests like 'can you delete the burpee task?' or 'could you move that to tomorrow?' are still action intent, not query intent.\n"
            "Completion statements like 'the Tuesday dinner plan is done', 'finished that already', or 'Amy handled that' are also action intent when they refer to a task.\n"
            "Status updates about a recent reminder being handled or resolved, such as 'we checked on Patrick, he's alright', are action intent and should usually complete or dismiss that reminder.\n"
            "If context.grounding.displayed_task_refs includes ordinal items from the latest /today or /focus list, resolve phrases like first task, second one, or item 3 against those task ids.\n"
            "If context.grounding.recent_task_refs includes recently discussed tasks from the assistant's latest answer, use those grounded task ids for named follow-ups like the burpee task, the backpack item, or that apartment task.\n"
            "If context.grounding.recent_reminder_refs includes recently discussed reminders, use those grounded reminder ids for follow-ups like that reminder, the payroll reminder, or move it to tomorrow.\n"
            "If context.grounding.session_state includes active_entity_refs or a pending clarification, use that session state for short conversational follow-ups.\n"
            "If context.grounding includes clarification candidates from a prior unresolved turn, treat short replies like 'the one that says register' or 'that one' as clarification answers, not standalone queries.\n"
            "For broad completion statements, prefer action intent with scoped task actions using grounded task ids when possible.\n"
            "If the user gives multiple action clauses in one message, return multiple actions when each clause refers to a concrete task.\n"
            "Return only JSON."
        )
        try:
            payload: Dict[str, Any] = {"message": message}
            if isinstance(context, dict):
                payload["context"] = context
            raw = await self._invoke_operation("action_plan", prompt, json.dumps(payload, ensure_ascii=True))
            intent = raw.get("intent")
            scope = raw.get("scope")
            actions = raw.get("actions")
            confidence = raw.get("confidence")
            needs_confirmation = raw.get("needs_confirmation")
            if intent not in {"query", "action"}:
                raise ValueError("Invalid planner intent")
            if scope not in {"single", "subset", "all_open", "all_matching"}:
                scope = "single"
            if not isinstance(actions, list):
                actions = []
            if not isinstance(confidence, (int, float)):
                confidence = 0.0
            if not isinstance(needs_confirmation, bool):
                needs_confirmation = True
            return {
                "intent": intent,
                "scope": scope,
                "actions": actions,
                "confidence": float(confidence),
                "needs_confirmation": needs_confirmation,
            }
        except Exception as exc:
            logger.warning("plan_actions fallback: %s", type(exc).__name__)
            return fallback

    async def critique_actions(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        proposal: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        fallback = {"approved": True, "issues": []}
        prompt = (
            "Operation: action_critic.\n"
            "Review the proposed actions for correctness and safety.\n"
            "Return JSON with keys: approved (bool), issues (array of strings), optional revised_actions (array).\n"
            "Reject duplicates, unresolved targets, contradictory updates, and risky broad updates without clear scope.\n"
            "Return only JSON."
        )
        try:
            payload: Dict[str, Any] = {"message": message, "proposal": proposal or {}}
            if isinstance(context, dict):
                payload["context"] = context
            raw = await self._invoke_operation("action_critic", prompt, json.dumps(payload, ensure_ascii=True))
            approved = raw.get("approved")
            issues = raw.get("issues")
            revised_actions = raw.get("revised_actions")
            if not isinstance(approved, bool):
                approved = True
            if not isinstance(issues, list):
                issues = []
            out: Dict[str, Any] = {"approved": approved, "issues": [str(x) for x in issues[:10]]}
            if isinstance(revised_actions, list):
                out["revised_actions"] = revised_actions
            return out
        except Exception as exc:
            logger.warning("critique_actions fallback: %s", type(exc).__name__)
            return fallback

    async def summarize_memory(self, context: str) -> Dict[str, Any]:
        fallback = {"summary_text": "No summary available.", "facts": []}
        prompt = (
            "Operation: summarize.\n"
            "Summarize context into JSON with keys summary_text (string) and facts (array of strings).\n"
            "Return only JSON."
        )
        try:
            raw = await self._invoke_operation("summarize", prompt, context)
            summary_text = raw.get("summary_text")
            facts = raw.get("facts")
            if not isinstance(summary_text, str) or not summary_text.strip():
                raise ValueError("Invalid summary_text")
            if not isinstance(facts, list):
                facts = []
            normalized = {"summary_text": summary_text.strip(), "facts": [str(x) for x in facts][:20]}
            usage = self._normalize_usage(raw.get("usage"))
            if usage:
                normalized["usage"] = usage
            return normalized
        except Exception as exc:
            logger.warning("summarize_memory fallback: %s", type(exc).__name__)
            return fallback

    async def rewrite_plan(self, plan_state: Dict[str, Any]) -> Dict[str, Any]:
        prompt = (
            "Operation: plan.\n"
            "Given plan JSON, improve natural-language reasons only.\n"
            "Return full plan JSON with same structural fields."
        )
        baseline = deepcopy(plan_state)
        try:
            raw = await self._invoke_operation("plan", prompt, json.dumps(plan_state))
            if {"schema_version", "plan_window", "generated_at", "today_plan", "next_actions", "blocked_items"}.issubset(raw.keys()):
                normalized = raw
            else:
                today_plan = raw.get("today_plan")
                if not isinstance(today_plan, list):
                    raise ValueError("Invalid plan payload")
                reason_map = {}
                for item in today_plan:
                    if isinstance(item, dict) and isinstance(item.get("task_id"), str) and isinstance(item.get("reason"), str):
                        reason_map[item["task_id"]] = item["reason"]
                for item in baseline.get("today_plan", []):
                    task_id = item.get("task_id")
                    if isinstance(task_id, str) and task_id in reason_map:
                        item["reason"] = reason_map[task_id]
                normalized = baseline
            usage = self._normalize_usage(raw.get("usage"))
            if usage:
                normalized["usage"] = usage
            return normalized
        except Exception as exc:
            logger.warning("rewrite_plan fallback: %s", type(exc).__name__)
            return render_fallback_plan_explanation(baseline)

    async def answer_query(self, query: str, retrieved_context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = (
            "Operation: query.\n"
            "Answer based only on provided context.\n"
            "Keep the answer concise and directly responsive to the user's request.\n"
            "If the user is just greeting or making small talk without asking for state, reply briefly and do not enumerate tasks or goals.\n"
            "If the answer mentions concrete tasks, goals, or problems from context, include their ids in surfaced_entity_ids.\n"
            "Return JSON with schema_version=query.v1, mode=query, answer, confidence, and optional surfaced_entity_ids."
        )
        try:
            raw = await self._invoke_operation(
                "query",
                prompt,
                json.dumps({"query": query, "context": retrieved_context}, ensure_ascii=True),
            )
            usage = self._normalize_usage(raw.get("usage"))
            normalized = self._normalize_query_payload(raw)
            if usage:
                normalized["usage"] = usage
            return normalized
        except Exception as exc:
            logger.error("answer_query failed: %s", type(exc).__name__)
            raise


adapter = LLMAdapter()
