import asyncio
import json
import logging
from copy import deepcopy
from datetime import date
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
        priority = candidate.get("priority")
        if isinstance(priority, int) and 1 <= priority <= 4:
            item["priority"] = priority
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
        if operation in {"action_plan", "action_critic"}:
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
            goals = [
                item
                for item in (
                    LLMAdapter._normalize_extract_title_item(goal)
                    for goal in payload.get("goals", [])
                )
                if item is not None
            ]
            problems = [
                item
                for item in (
                    LLMAdapter._normalize_extract_title_item(problem)
                    for problem in payload.get("problems", [])
                )
                if item is not None
            ]
            links = [
                item
                for item in (
                    LLMAdapter._normalize_extract_link_item(link)
                    for link in payload.get("links", [])
                )
                if item is not None
            ]
            normalized = {"tasks": tasks, "goals": goals, "problems": problems, "links": links}
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
            goals = []
            for goal in proposals.get("goals", []):
                if isinstance(goal, dict) and goal.get("action") != "ignore" and isinstance(goal.get("title"), str):
                    goals.append({"title": goal["title"].strip(), "status": "active"})
            problems = []
            for problem in proposals.get("problems", []):
                if isinstance(problem, dict) and problem.get("action") != "ignore" and isinstance(problem.get("title"), str):
                    problems.append({"title": problem["title"].strip(), "status": "active"})
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
            normalized = {"tasks": tasks, "goals": goals, "problems": problems, "links": links}

        for key in ("tasks", "goals", "problems", "links"):
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

    async def extract_structured_updates(self, message: str, grounding: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        fallback = {"tasks": [], "goals": [], "problems": [], "links": []}
        prompt = (
            "Operation: extract.\n"
            "Convert user text into JSON object with keys tasks/goals/problems/links.\n"
            "Prefer updating/completing existing tasks from grounding before creating new ones.\n"
            "Each task supports optional action=create|update|complete|archive|noop and target_task_id.\n"
            "When dates are explicit or relative (for example tomorrow/next week), include ISO due_date (YYYY-MM-DD) resolved against grounding.current_date_utc.\n"
            "If user implies completion/cancellation, prefer action=complete/archive with status done/archived.\n"
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
            logger.warning("extract_structured_updates fallback: %s", type(exc).__name__)
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
            "actions is an array of objects with entity_type/task-goal-problem, action, optional title, optional target_task_id, optional status, optional priority, optional due_date.\n"
            "Resolve relative dates against context.grounding.current_date_utc and output due_date as YYYY-MM-DD.\n"
            "For broad completion statements, prefer action intent with scoped task actions using grounded task ids when possible.\n"
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
            "Return JSON with schema_version=query.v1, mode=query, answer, confidence."
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
