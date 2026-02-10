import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from api.main import app, get_db
from common.models import EventLog
from worker.main import MAX_ATTEMPTS, process_job


class _FakeResult:
    def __init__(self, items=None):
        self._items = items or []

    def scalars(self):
        return self

    def all(self):
        return self._items


def _session_factory(fake_db):
    @asynccontextmanager
    async def _ctx():
        yield fake_db

    return lambda: _ctx()


def test_health_metrics_returns_operational_shape(mock_redis):
    async def _run():
        now = datetime(2026, 2, 10, 0, 0, 0)
        failure_events = [
            EventLog(
                id="ev1",
                request_id="r1",
                user_id="usr_dev",
                event_type="worker_retry_scheduled",
                payload_json={"topic": "memory.summarize"},
                created_at=now,
            ),
            EventLog(
                id="ev2",
                request_id="r2",
                user_id="usr_dev",
                event_type="worker_moved_to_dlq",
                payload_json={"topic": "sync.todoist"},
                created_at=now,
            ),
        ]
        completed_events = [
            EventLog(
                id="ev3",
                request_id="r3",
                user_id="usr_dev",
                event_type="worker_topic_completed",
                payload_json={"topic": "memory.summarize"},
                created_at=datetime(2026, 2, 10, 1, 0, 0),
            ),
            EventLog(
                id="ev4",
                request_id="r4",
                user_id="usr_dev",
                event_type="worker_topic_completed",
                payload_json={"topic": "plan.refresh"},
                created_at=datetime(2026, 2, 10, 2, 0, 0),
            ),
        ]

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                _FakeResult(items=failure_events),
                _FakeResult(items=completed_events),
            ]
        )

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch("api.main.redis_client", mock_redis):
                mock_redis.llen = AsyncMock(side_effect=[4, 1])
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(
                        "/health/metrics",
                        headers={"Authorization": "Bearer test_token"},
                    )
                assert resp.status_code == 200
                body = resp.json()
                assert body["queue_depth"]["default_queue"] == 4
                assert body["queue_depth"]["dead_letter_queue"] == 1
                assert body["failure_counters"]["retry_scheduled"] == 1
                assert body["failure_counters"]["moved_to_dlq"] == 1
                assert body["last_success_by_topic"]["memory.summarize"] is not None
                assert body["last_success_by_topic"]["plan.refresh"] is not None
                assert body["last_success_by_topic"]["sync.todoist"] is None
        finally:
            app.dependency_overrides.clear()

    asyncio.run(_run())


def test_process_job_logs_retry_event_and_requeues():
    async def _run():
        fake_db = AsyncMock()
        fake_db.add = MagicMock()
        fake_db.commit = AsyncMock()

        fake_redis = AsyncMock()
        fake_redis.rpush = AsyncMock(return_value=1)

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch(
            "worker.main.redis_client", fake_redis
        ), patch(
            "worker.main.handle_memory_summarize", AsyncMock(side_effect=RuntimeError("boom"))
        ), patch("worker.main.asyncio.sleep", AsyncMock()):
            await process_job(
                {
                    "job_id": "job_retry",
                    "topic": "memory.summarize",
                    "payload": {"user_id": "usr_dev"},
                    "attempt": 1,
                }
            )

        fake_redis.rpush.assert_awaited_once()
        queue_name, raw_payload = fake_redis.rpush.await_args.args
        assert queue_name == "default_queue"
        assert '"attempt": 2' in raw_payload

        assert fake_db.add.call_count == 1
        logged = fake_db.add.call_args.args[0]
        assert logged.event_type == "worker_retry_scheduled"
        assert logged.payload_json["topic"] == "memory.summarize"
        assert logged.payload_json["attempt"] == 1
        assert logged.payload_json["max_attempts"] == MAX_ATTEMPTS
        assert logged.payload_json["queue"] == "default_queue"

    asyncio.run(_run())


def test_process_job_logs_dlq_event_on_max_attempts():
    async def _run():
        fake_db = AsyncMock()
        fake_db.add = MagicMock()
        fake_db.commit = AsyncMock()

        fake_redis = AsyncMock()
        fake_redis.rpush = AsyncMock(return_value=1)

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch(
            "worker.main.redis_client", fake_redis
        ), patch(
            "worker.main.handle_memory_summarize", AsyncMock(side_effect=RuntimeError("fatal"))
        ):
            await process_job(
                {
                    "job_id": "job_dlq",
                    "topic": "memory.summarize",
                    "payload": {"user_id": "usr_dev"},
                    "attempt": MAX_ATTEMPTS,
                }
            )

        fake_redis.rpush.assert_awaited_once()
        queue_name, _ = fake_redis.rpush.await_args.args
        assert queue_name == "dead_letter_queue"

        assert fake_db.add.call_count == 1
        logged = fake_db.add.call_args.args[0]
        assert logged.event_type == "worker_moved_to_dlq"
        assert logged.payload_json["topic"] == "memory.summarize"
        assert logged.payload_json["attempt"] == MAX_ATTEMPTS
        assert logged.payload_json["max_attempts"] == MAX_ATTEMPTS
        assert logged.payload_json["queue"] == "dead_letter_queue"

    asyncio.run(_run())
