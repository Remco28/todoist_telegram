import logging
import httpx
from typing import Dict, Any, Optional
from common.config import settings

logger = logging.getLogger(__name__)

class TodoistAdapter:
    def __init__(self):
        self.base_url = settings.TODOIST_API_BASE
        self.token = settings.TODOIST_TOKEN

    def _get_headers(self) -> Dict[str, str]:
        if not self.token:
            raise RuntimeError("TODOIST_TOKEN not configured")
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    async def create_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates a task in Todoist.
        """
        url = f"{self.base_url}/tasks"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=self._get_headers(), json=payload)
            resp.raise_for_status()
            return resp.json()

    async def update_task(self, todoist_task_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates a task in Todoist.
        """
        url = f"{self.base_url}/tasks/{todoist_task_id}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=self._get_headers(), json=payload)
            resp.raise_for_status()
            if resp.status_code == 204:
                return {}
            return resp.json()

    async def close_task(self, todoist_task_id: str) -> bool:
        """
        Completes a task in Todoist.
        """
        url = f"{self.base_url}/tasks/{todoist_task_id}/close"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=self._get_headers())
            resp.raise_for_status()
            return True

todoist_adapter = TodoistAdapter()
