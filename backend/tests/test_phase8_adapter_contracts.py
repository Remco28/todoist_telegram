import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from api.main import app, get_db
from worker.main import handle_plan_refresh


class _FakeResult:
    def __init__(self, one_or_none=None):
        self._one_or_none = one_or_none

    def scalar_one_or_none(self):
        return self._one_or_none


def _session_factory(fake_db):
    @asynccontextmanager
    async def _ctx():
        yield fake_db

    return lambda: _ctx()


def _rate_limit_redis():
    mock = AsyncMock()
    mock.incr = AsyncMock(return_value=1)
    mock.expire = AsyncMock(return_value=True)
    mock.ttl = AsyncMock(return_value=59)
    mock.rpush = AsyncMock(return_value=1)
    return mock


def test_capture_rejects_non_dict_extraction_and_avoids_writes():
    async def _run():
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(return_value=_FakeResult(one_or_none=None))
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch("api.main.redis_client", _rate_limit_redis()), patch(
                "api.main.adapter.extract_structured_updates",
                AsyncMock(return_value="not-a-dict"),
            ), patch("api.main._apply_capture", AsyncMock()) as mock_apply_capture:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/v1/capture/thought",
                        headers={"Authorization": "Bearer test_token", "Idempotency-Key": "phase8-extract-1"},
                        json={"chat_id": "phase8_chat", "source": "api", "message": "hello"},
                    )
                assert resp.status_code == 422
                mock_apply_capture.assert_not_awaited()
        finally:
            app.dependency_overrides.clear()

    asyncio.run(_run())


def test_capture_rejects_invalid_scalar_fields_and_avoids_partial_writes():
    async def _run():
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(return_value=_FakeResult(one_or_none=None))
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        malformed = {
            "tasks": [{"title": 123, "status": "open", "priority": 2}],
            "goals": [],
            "problems": [],
            "links": [],
        }

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch("api.main.redis_client", _rate_limit_redis()), patch(
                "api.main.adapter.extract_structured_updates",
                AsyncMock(return_value=malformed),
            ), patch("api.main._apply_capture", AsyncMock()) as mock_apply_capture:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/v1/capture/thought",
                        headers={"Authorization": "Bearer test_token", "Idempotency-Key": "phase8-extract-2"},
                        json={"chat_id": "phase8_chat", "source": "api", "message": "hello"},
                    )
                assert resp.status_code == 422
                mock_apply_capture.assert_not_awaited()
        finally:
            app.dependency_overrides.clear()

    asyncio.run(_run())


def test_capture_rejects_missing_required_extraction_keys():
    async def _run():
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(return_value=_FakeResult(one_or_none=None))
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        malformed = {
            "tasks": [],
            "goals": [],
            # "problems" missing
            "links": [],
        }

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch("api.main.redis_client", _rate_limit_redis()), patch(
                "api.main.adapter.extract_structured_updates",
                AsyncMock(return_value=malformed),
            ), patch("api.main._apply_capture", AsyncMock()) as mock_apply_capture:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/v1/capture/thought",
                        headers={"Authorization": "Bearer test_token", "Idempotency-Key": "phase8-extract-3"},
                        json={"chat_id": "phase8_chat", "source": "api", "message": "hello"},
                    )
                assert resp.status_code == 422
                mock_apply_capture.assert_not_awaited()
        finally:
            app.dependency_overrides.clear()

    asyncio.run(_run())


def test_query_fallback_remains_contract_compliant_on_malformed_adapter_payload():
    async def _run():
        fake_db = AsyncMock()
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch("api.main.redis_client", _rate_limit_redis()), patch(
                "api.main.assemble_context",
                AsyncMock(return_value={"sources": {"entities": 0}}),
            ), patch(
                "api.main.adapter.answer_query",
                AsyncMock(return_value={"schema_version": "query.v1", "mode": "query", "confidence": "bad"}),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/v1/query/ask",
                        headers={"Authorization": "Bearer test_token"},
                        json={"chat_id": "phase8_chat", "query": "what is urgent?"},
                    )
                assert resp.status_code == 200
                body = resp.json()
                assert body["schema_version"] == "query.v1"
                assert body["mode"] == "query"
                assert isinstance(body["answer"], str) and body["answer"]
                assert isinstance(body["confidence"], float)
        finally:
            app.dependency_overrides.clear()

    asyncio.run(_run())


def test_plan_rewrite_malformed_payload_falls_back_to_valid_schema_before_cache():
    async def _run():
        fake_db = AsyncMock()
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        valid_plan_payload = {
            "schema_version": "plan.v1",
            "plan_window": "today",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "today_plan": [],
            "next_actions": [],
            "blocked_items": [],
            "why_this_order": [],
            "assumptions": [],
        }

        fake_redis = AsyncMock()
        fake_redis.setex = AsyncMock(return_value=True)

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch(
            "worker.main.redis_client", fake_redis
        ), patch(
            "worker.main.collect_planning_state",
            AsyncMock(side_effect=[{"ok": True}, {"ok": True}]),
        ), patch(
            "worker.main.build_plan_payload",
            return_value=valid_plan_payload,
        ), patch(
            "worker.main.adapter.rewrite_plan",
            AsyncMock(return_value={"schema_version": "plan.v1", "plan_window": "today", "today_plan": "bad"}),
        ):
            await handle_plan_refresh("job_phase8", {"user_id": "usr_dev", "chat_id": "phase8_chat"})

        fake_redis.setex.assert_awaited_once()
        _, _, cached_json = fake_redis.setex.await_args.args
        cached = json.loads(cached_json)
        assert cached["schema_version"] == "plan.v1"
        assert isinstance(cached["today_plan"], list)
        assert isinstance(cached["blocked_items"], list)
    asyncio.run(_run())


def test_plan_rewrite_ignores_extra_unexpected_keys_via_schema_validation():
    async def _run():
        fake_db = AsyncMock()
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        valid_plan_payload = {
            "schema_version": "plan.v1",
            "plan_window": "today",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "today_plan": [],
            "next_actions": [],
            "blocked_items": [],
            "why_this_order": [],
            "assumptions": [],
        }

        fake_redis = AsyncMock()
        fake_redis.setex = AsyncMock(return_value=True)

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch(
            "worker.main.redis_client", fake_redis
        ), patch(
            "worker.main.collect_planning_state",
            AsyncMock(return_value={"ok": True}),
        ), patch(
            "worker.main.build_plan_payload",
            return_value=valid_plan_payload,
        ), patch(
            "worker.main.adapter.rewrite_plan",
            AsyncMock(return_value={**valid_plan_payload, "unexpected_key": {"x": 1}}),
        ):
            await handle_plan_refresh("job_phase8_extra", {"user_id": "usr_dev", "chat_id": "phase8_chat"})

        fake_redis.setex.assert_awaited_once()
        _, _, cached_json = fake_redis.setex.await_args.args
        cached = json.loads(cached_json)
        assert cached["schema_version"] == "plan.v1"
        assert "unexpected_key" not in cached

    asyncio.run(_run())
