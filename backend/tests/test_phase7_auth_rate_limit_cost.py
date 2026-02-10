import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from api.main import app, get_db
from common.config import settings
from common.models import PromptRun


class _FakeResult:
    def __init__(self, items=None, one_or_none=None, scalar=None):
        self._items = items or []
        self._one_or_none = one_or_none
        self._scalar = scalar

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar_one_or_none(self):
        return self._one_or_none

    def scalar(self):
        return self._scalar


def _db_override(fake_db):
    @asynccontextmanager
    async def _ctx():
        yield fake_db

    return _ctx


class _RateLimitRedis:
    def __init__(self):
        self.counts = {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, seconds):
        return True

    async def ttl(self, key):
        return 59

    async def get(self, key):
        return None

    async def rpush(self, *args, **kwargs):
        return 1

    def reset_key(self, key):
        self.counts.pop(key, None)


def test_auth_token_user_mapping_and_unknown_token_denied(mock_redis):
    async def _run():
        old_map = settings.APP_AUTH_TOKEN_USER_MAP
        old_tokens = settings.APP_AUTH_BEARER_TOKENS
        settings.APP_AUTH_TOKEN_USER_MAP = "token_a:usr_a,token_b:usr_b"
        settings.APP_AUTH_BEARER_TOKENS = "legacy_token"

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(return_value=_FakeResult(items=[]))

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch("api.main.redis_client", mock_redis):
                mock_redis.llen = AsyncMock(side_effect=[0, 0])
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    ok = await client.get("/health/metrics", headers={"Authorization": "Bearer token_b"})
                    bad = await client.get("/health/metrics", headers={"Authorization": "Bearer unknown"})
                assert ok.status_code == 200
                assert bad.status_code == 401
        finally:
            app.dependency_overrides.clear()
            settings.APP_AUTH_TOKEN_USER_MAP = old_map
            settings.APP_AUTH_BEARER_TOKENS = old_tokens

    asyncio.run(_run())


def test_auth_mixed_mode_falls_back_to_legacy_tokens(mock_redis):
    async def _run():
        old_map = settings.APP_AUTH_TOKEN_USER_MAP
        old_tokens = settings.APP_AUTH_BEARER_TOKENS
        settings.APP_AUTH_TOKEN_USER_MAP = "token_a:usr_a"
        settings.APP_AUTH_BEARER_TOKENS = "legacy_token"

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(return_value=_FakeResult(items=[]))

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch("api.main.redis_client", mock_redis):
                mock_redis.llen = AsyncMock(return_value=0)
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    via_map = await client.get("/health/metrics", headers={"Authorization": "Bearer token_a"})
                    via_legacy = await client.get("/health/metrics", headers={"Authorization": "Bearer legacy_token"})
                assert via_map.status_code == 200
                assert via_legacy.status_code == 200
        finally:
            app.dependency_overrides.clear()
            settings.APP_AUTH_TOKEN_USER_MAP = old_map
            settings.APP_AUTH_BEARER_TOKENS = old_tokens

    asyncio.run(_run())


def test_rate_limit_enforced_per_endpoint_class():
    async def _run():
        old_map = settings.APP_AUTH_TOKEN_USER_MAP
        old_capture = settings.RATE_LIMIT_CAPTURE_PER_WINDOW
        old_query = settings.RATE_LIMIT_QUERY_PER_WINDOW
        old_plan = settings.RATE_LIMIT_PLAN_PER_WINDOW

        settings.APP_AUTH_TOKEN_USER_MAP = "token_a:usr_a"
        settings.RATE_LIMIT_CAPTURE_PER_WINDOW = 1
        settings.RATE_LIMIT_QUERY_PER_WINDOW = 1
        settings.RATE_LIMIT_PLAN_PER_WINDOW = 1

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(return_value=_FakeResult(items=[], one_or_none=None))
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db

        limiter_redis = _RateLimitRedis()

        with patch("api.main.redis_client", limiter_redis), patch(
            "api.main.adapter.extract_structured_updates",
            AsyncMock(return_value={"tasks": [], "goals": [], "problems": [], "links": []}),
        ), patch(
            "api.main._apply_capture",
            AsyncMock(return_value=("inb_test", {"tasks_created": 0, "tasks_updated": 0, "goals_created": 0, "problems_created": 0, "links_created": 0})),
        ), patch(
            "api.main.save_idempotency", AsyncMock()
        ), patch(
            "api.main.assemble_context",
            AsyncMock(return_value={"sources": {"entities": 0}, "usage": {"input_tokens": 2, "output_tokens": 3}}),
        ), patch(
            "api.main.adapter.answer_query",
            AsyncMock(return_value={"schema_version": "query.v1", "mode": "query", "answer": "ok", "confidence": 0.8}),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                h = {"Authorization": "Bearer token_a", "Idempotency-Key": "k1"}
                c1 = await client.post("/v1/capture/thought", headers=h, json={"chat_id": "c1", "source": "api", "message": "hello"})
                c2 = await client.post("/v1/capture/thought", headers={**h, "Idempotency-Key": "k2"}, json={"chat_id": "c1", "source": "api", "message": "hello2"})
                q1 = await client.post("/v1/query/ask", headers={"Authorization": "Bearer token_a"}, json={"chat_id": "c1", "query": "what?"})
                q2 = await client.post("/v1/query/ask", headers={"Authorization": "Bearer token_a"}, json={"chat_id": "c1", "query": "again?"})
                p1 = await client.post("/v1/plan/refresh", headers={"Authorization": "Bearer token_a", "Idempotency-Key": "p1"}, json={"chat_id": "c1"})
                p2 = await client.post("/v1/plan/refresh", headers={"Authorization": "Bearer token_a", "Idempotency-Key": "p2"}, json={"chat_id": "c1"})

            assert c1.status_code == 200
            assert c2.status_code == 429
            assert q1.status_code == 200
            assert q2.status_code == 429
            assert p1.status_code == 200
            assert p2.status_code == 429

        app.dependency_overrides.clear()
        settings.APP_AUTH_TOKEN_USER_MAP = old_map
        settings.RATE_LIMIT_CAPTURE_PER_WINDOW = old_capture
        settings.RATE_LIMIT_QUERY_PER_WINDOW = old_query
        settings.RATE_LIMIT_PLAN_PER_WINDOW = old_plan

    asyncio.run(_run())


def test_rate_limit_resets_after_window_simulated_expiry():
    async def _run():
        old_map = settings.APP_AUTH_TOKEN_USER_MAP
        old_capture = settings.RATE_LIMIT_CAPTURE_PER_WINDOW
        settings.APP_AUTH_TOKEN_USER_MAP = "token_a:usr_a"
        settings.RATE_LIMIT_CAPTURE_PER_WINDOW = 1

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(return_value=_FakeResult(items=[], one_or_none=None))
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        limiter_redis = _RateLimitRedis()

        with patch("api.main.redis_client", limiter_redis), patch(
            "api.main.adapter.extract_structured_updates",
            AsyncMock(return_value={"tasks": [], "goals": [], "problems": [], "links": []}),
        ), patch(
            "api.main._apply_capture",
            AsyncMock(return_value=("inb_test", {"tasks_created": 0, "tasks_updated": 0, "goals_created": 0, "problems_created": 0, "links_created": 0})),
        ), patch("api.main.save_idempotency", AsyncMock()):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                h1 = {"Authorization": "Bearer token_a", "Idempotency-Key": "r1"}
                h2 = {"Authorization": "Bearer token_a", "Idempotency-Key": "r2"}
                h3 = {"Authorization": "Bearer token_a", "Idempotency-Key": "r3"}
                first = await client.post("/v1/capture/thought", headers=h1, json={"chat_id": "c1", "source": "api", "message": "hello"})
                second = await client.post("/v1/capture/thought", headers=h2, json={"chat_id": "c1", "source": "api", "message": "again"})
                limiter_redis.reset_key("rate_limit:capture:usr_a")
                third = await client.post("/v1/capture/thought", headers=h3, json={"chat_id": "c1", "source": "api", "message": "after window"})
                assert first.status_code == 200
                assert second.status_code == 429
                assert third.status_code == 200

        app.dependency_overrides.clear()
        settings.APP_AUTH_TOKEN_USER_MAP = old_map
        settings.RATE_LIMIT_CAPTURE_PER_WINDOW = old_capture

    asyncio.run(_run())


def test_daily_cost_summary_aggregation(mock_redis):
    async def _run():
        old_map = settings.APP_AUTH_TOKEN_USER_MAP
        settings.APP_AUTH_TOKEN_USER_MAP = "token_cost:usr_dev"

        rows = [
            PromptRun(
                id="p1",
                request_id="r1",
                user_id="usr_dev",
                operation="query",
                provider="grok",
                model="m1",
                prompt_version="v1",
                input_tokens=1000,
                cached_input_tokens=250,
                output_tokens=200,
                status="success",
                created_at=datetime.utcnow(),
            ),
            PromptRun(
                id="p2",
                request_id="r2",
                user_id="usr_dev",
                operation="extract",
                provider="grok",
                model="m2",
                prompt_version="v1",
                input_tokens=500,
                cached_input_tokens=100,
                output_tokens=0,
                status="success",
                created_at=datetime.utcnow(),
            ),
            PromptRun(
                id="p3",
                request_id="r3",
                user_id="usr_other",
                operation="query",
                provider="grok",
                model="m1",
                prompt_version="v1",
                input_tokens=99999,
                cached_input_tokens=50000,
                output_tokens=9999,
                status="success",
                created_at=datetime.utcnow(),
            ),
        ]

        fake_db = AsyncMock()

        async def _execute(stmt):
            _ = stmt
            return _FakeResult(items=[row for row in rows if row.user_id == "usr_dev"])

        fake_db.execute = AsyncMock(side_effect=_execute)

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch("api.main.redis_client", mock_redis):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/health/costs/daily", headers={"Authorization": "Bearer token_cost"})
                assert resp.status_code == 200
                body = resp.json()
                assert body["totals"]["input_tokens"] == 1500
                assert body["totals"]["cached_input_tokens"] == 350
                assert body["totals"]["output_tokens"] == 200
                assert body["totals"]["estimated_usd"] > 0
                assert len(body["breakdown"]) == 2
        finally:
            app.dependency_overrides.clear()
            settings.APP_AUTH_TOKEN_USER_MAP = old_map

    asyncio.run(_run())
