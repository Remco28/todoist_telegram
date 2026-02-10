import os
import uuid
from datetime import datetime

import httpx
import pytest


RUN_SMOKE = os.getenv("RUN_STAGING_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_SMOKE,
    reason="Set RUN_STAGING_SMOKE=1 to run staging smoke tests.",
)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.fail(f"Missing required staging env var: {name}")
    return value


def _headers(token: str, idempotency_key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def test_phase8_staging_smoke_core_paths():
    base_url = _required_env("STAGING_API_BASE_URL")
    auth_token = _required_env("STAGING_AUTH_TOKEN")
    _required_env("DATABASE_URL")
    _required_env("REDIS_URL")

    suffix = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    chat_id = f"phase8-smoke-{suffix}"

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        capture_resp = client.post(
            "/v1/capture/thought",
            headers=_headers(auth_token, idempotency_key=f"phase8-capture-{suffix}"),
            json={
                "chat_id": chat_id,
                "source": "api",
                "message": f"phase8 smoke thought {suffix}",
            },
        )
        assert capture_resp.status_code == 200, capture_resp.text
        capture_json = capture_resp.json()
        assert capture_json.get("status") == "ok"
        assert isinstance(capture_json.get("inbox_item_id"), str) and capture_json["inbox_item_id"]

        query_resp = client.post(
            "/v1/query/ask",
            headers=_headers(auth_token),
            json={"chat_id": chat_id, "query": "What should I do next?"},
        )
        assert query_resp.status_code == 200, query_resp.text
        query_json = query_resp.json()
        assert query_json.get("schema_version") == "query.v1"
        assert isinstance(query_json.get("answer"), str) and query_json["answer"]
        assert isinstance(query_json.get("confidence"), (int, float))

        plan_refresh_resp = client.post(
            "/v1/plan/refresh",
            headers=_headers(auth_token, idempotency_key=f"phase8-plan-{suffix}"),
            json={"chat_id": chat_id},
        )
        assert plan_refresh_resp.status_code == 200, plan_refresh_resp.text
        plan_refresh_json = plan_refresh_resp.json()
        assert plan_refresh_json.get("status") == "ok"
        assert isinstance(plan_refresh_json.get("job_id"), str) and plan_refresh_json["job_id"]

        plan_get_resp = client.get(
            "/v1/plan/get_today",
            headers=_headers(auth_token),
            params={"chat_id": chat_id},
        )
        assert plan_get_resp.status_code == 200, plan_get_resp.text
        plan_get_json = plan_get_resp.json()
        assert plan_get_json.get("schema_version") == "plan.v1"
        assert isinstance(plan_get_json.get("today_plan"), list)
        assert isinstance(plan_get_json.get("blocked_items"), list)

        sync_trigger_resp = client.post(
            "/v1/sync/todoist",
            headers=_headers(auth_token, idempotency_key=f"phase8-sync-{suffix}"),
        )
        assert sync_trigger_resp.status_code == 200, sync_trigger_resp.text
        sync_trigger_json = sync_trigger_resp.json()
        assert sync_trigger_json.get("status") == "ok"
        assert isinstance(sync_trigger_json.get("job_id"), str) and sync_trigger_json["job_id"]

        sync_status_resp = client.get(
            "/v1/sync/todoist/status",
            headers=_headers(auth_token),
        )
        assert sync_status_resp.status_code == 200, sync_status_resp.text
        sync_status_json = sync_status_resp.json()
        assert "total_mapped" in sync_status_json
        assert "pending_sync" in sync_status_json
        assert "error_count" in sync_status_json
