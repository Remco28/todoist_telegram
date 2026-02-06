import json
import logging
import random
from typing import Dict, Any, List
from datetime import datetime
from common.config import settings
from common.models import EntityType, LinkType

logger = logging.getLogger(__name__)

class LLMAdapter:
    def __init__(self):
        self.should_fail_count = 0

    async def extract_structured_updates(self, message: str) -> Dict[str, Any]:
        """
        Extracts structured entities from a message.
        Guaranteed to return a dict with keys: tasks, goals, problems, links.
        """
        if self.should_fail_count > 0:
            self.should_fail_count -= 1
            raise ValueError("Simulated LLM Failure")

        fallback = {
            "tasks": [],
            "goals": [],
            "problems": [],
            "links": []
        }
        
        try:
            tasks = []
            goals = []
            problems = []
            links = []
            
            msg_lower = message.lower()
            
            # Simple mock extraction for Phase 1 testing
            if "task" in msg_lower:
                task_title = message.split("task")[-1].strip() or "Untitled Task"
                tasks.append({
                    "title": task_title,
                    "status": "open",
                    "priority": 3
                })
                
                if "goal" in msg_lower:
                    goal_title = message.split("goal")[-1].strip().split("task")[0].strip() or "Untitled Goal"
                    goals.append({
                        "title": goal_title,
                        "status": "active"
                    })
                    links.append({
                        "from_type": EntityType.task,
                        "from_title": task_title,
                        "to_type": EntityType.goal,
                        "to_title": goal_title,
                        "link_type": LinkType.supports_goal
                    })

            if "problem" in msg_lower or "friction" in msg_lower:
                problems.append({
                    "title": message.split("problem")[-1].strip() or "Untitled Problem",
                    "status": "active"
                })

            return {
                "tasks": tasks,
                "goals": goals,
                "problems": problems,
                "links": links
            }
        except Exception as e:
            logger.error(f"Extraction logic error: {e}")
            return fallback

    async def summarize_memory(self, context: str) -> Dict[str, Any]:
        """
        Summarizes session context.
        """
        try:
            return {
                "summary_text": f"User discussed: {context[:100]}...",
                "facts": ["Extracted from session context."]
            }
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            return {
                "summary_text": "Error generating summary.",
                "facts": []
            }

adapter = LLMAdapter()
