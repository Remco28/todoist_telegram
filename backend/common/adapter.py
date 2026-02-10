import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from common.config import settings
from common.models import EntityType, LinkType

logger = logging.getLogger(__name__)

class LLMAdapter:
    @staticmethod
    def _normalize_usage(candidate: Any) -> Optional[Dict[str, int]]:
        if not isinstance(candidate, dict):
            return None
        usage = {}
        for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
            value = candidate.get(key)
            if isinstance(value, int) and value >= 0:
                usage[key] = value
        return usage or None

    async def extract_structured_updates(self, message: str) -> Dict[str, Any]:
        """
        Extracts structured entities from a message.
        """
        fallback = {"tasks": [], "goals": [], "problems": [], "links": []}
        try:
            tasks = []
            goals = []
            problems = []
            links = []
            msg_lower = message.lower()
            
            if "task" in msg_lower:
                task_title = message.split("task")[-1].strip() or "Untitled Task"
                tasks.append({"title": task_title, "status": "open", "priority": 3})
                if "goal" in msg_lower:
                    goal_title = message.split("goal")[-1].strip().split("task")[0].strip() or "Untitled Goal"
                    goals.append({"title": goal_title, "status": "active"})
                    links.append({
                        "from_type": "task", "from_title": task_title,
                        "to_type": "goal", "to_title": goal_title,
                        "link_type": "supports_goal"
                    })
            if "problem" in msg_lower or "friction" in msg_lower:
                problems.append({"title": message.split("problem")[-1].strip() or "Untitled Problem", "status": "active"})

            result = {"tasks": tasks, "goals": goals, "problems": problems, "links": links}
            usage = self._normalize_usage(None)
            if usage:
                result["usage"] = usage
            return result
        except Exception as e:
            logger.error(f"Extraction logic error: {e}")
            return fallback

    async def summarize_memory(self, context: str) -> Dict[str, Any]:
        """
        Summarizes session context.
        """
        result = {
            "summary_text": f"User discussed items in context: {context[:50]}...",
            "facts": ["Context processed."]
        }
        usage = self._normalize_usage(None)
        if usage:
            result["usage"] = usage
        return result

    async def rewrite_plan(self, plan_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adds natural language reasons to the deterministic plan.
        LLM may update 'reason' field in plan items but must not add extra keys.
        """
        try:
            # Mock LLM rewrite - only update allowed fields
            for item in plan_state.get("today_plan", []):
                item["reason"] = f"Top priority based on score {item.get('score', 0):.1f}."
            usage = self._normalize_usage(plan_state.get("usage"))
            if usage:
                plan_state["usage"] = usage
            return plan_state
        except Exception as e:
            logger.error(f"Plan rewrite failed: {e}")
            from common.planner import render_fallback_plan_explanation
            return render_fallback_plan_explanation(plan_state)

    async def answer_query(self, query: str, retrieved_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Answers a user query using the retrieved context.
        """
        try:
            # Requirement 2: Query Response Contract Alignment
            result = {
                "schema_version": "query.v1",
                "mode": "query",
                "answer": f"Based on your memory, you have {retrieved_context['sources']['entities']} entities related to your query '{query}'.",
                "confidence": 0.9,
                "citations": [
                    {"entity_type": "summary", "entity_id": "latest", "label": "Recent Summary"}
                ],
                "suggested_actions": [
                    {"kind": "refresh_plan", "description": "Would you like to refresh your daily plan?"}
                ]
            }
            usage = self._normalize_usage(retrieved_context.get("usage"))
            if usage:
                result["usage"] = usage
            return result
        except Exception as e:
            logger.error(f"Query answer failed: {e}")
            raise # Let caller handle fallback
            
adapter = LLMAdapter()
