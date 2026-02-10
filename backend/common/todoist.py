import logging
import httpx
from typing import Dict, Any, Optional, List
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

    async def get_task(self, todoist_task_id: str) -> Optional[Dict[str, Any]]:
        """Fetches a single Todoist task by id.

        Returns None when the remote task is not found.
        """
        url = f"{self.base_url}/tasks/{todoist_task_id}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=self._get_headers())
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def list_tasks(self) -> List[Dict[str, Any]]:
        """Lists active Todoist tasks for the configured token."""
        url = f"{self.base_url}/tasks"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=self._get_headers())
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, list):
                return payload
            return []

todoist_adapter = TodoistAdapter()
