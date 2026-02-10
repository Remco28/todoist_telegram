import asyncio
from unittest.mock import AsyncMock, patch

import httpx

from common.adapter import LLMAdapter
from common.config import settings


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _set_provider_settings():
    original = {
        "LLM_API_BASE_URL": settings.LLM_API_BASE_URL,
        "LLM_API_KEY": settings.LLM_API_KEY,
        "LLM_MAX_RETRIES": settings.LLM_MAX_RETRIES,
        "LLM_TIMEOUT_SECONDS": settings.LLM_TIMEOUT_SECONDS,
        "LLM_RETRY_BACKOFF_SECONDS": settings.LLM_RETRY_BACKOFF_SECONDS,
    }
    settings.LLM_API_BASE_URL = "https://provider.example/v1"
    settings.LLM_API_KEY = "test_api_key"
    settings.LLM_MAX_RETRIES = 2
    settings.LLM_TIMEOUT_SECONDS = 5
    settings.LLM_RETRY_BACKOFF_SECONDS = 0
    return original


def _restore_provider_settings(original):
    for key, value in original.items():
        setattr(settings, key, value)


def test_extract_success_normalization_and_usage():
    async def _run():
        adapter = LLMAdapter()
        original = _set_provider_settings()
        try:
            payload = {
                "choices": [
                    {
                        "message": {
                            "content": '{"tasks":[{"title":"Buy paint","status":"open","priority":2}],"goals":[],"problems":[],"links":[]}'
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "prompt_tokens_details": {"cached_tokens": 10},
                },
            }
            with patch("common.adapter.httpx.AsyncClient.post", new=AsyncMock(return_value=_FakeResponse(payload))):
                out = await adapter.extract_structured_updates("Need to buy paint")
            assert out["tasks"][0]["title"] == "Buy paint"
            assert out["usage"]["input_tokens"] == 123
            assert out["usage"]["output_tokens"] == 45
            assert out["usage"]["cached_input_tokens"] == 10
        finally:
            _restore_provider_settings(original)

    asyncio.run(_run())


def test_extract_malformed_payload_returns_safe_fallback():
    async def _run():
        adapter = LLMAdapter()
        original = _set_provider_settings()
        try:
            payload = {"choices": [{"message": {"content": '{"bad":"shape"}'}}], "usage": {"prompt_tokens": 9}}
            with patch("common.adapter.httpx.AsyncClient.post", new=AsyncMock(return_value=_FakeResponse(payload))):
                out = await adapter.extract_structured_updates("text")
            assert out == {"tasks": [], "goals": [], "problems": [], "links": []}
        finally:
            _restore_provider_settings(original)

    asyncio.run(_run())


def test_query_malformed_payload_raises_for_api_fallback():
    async def _run():
        adapter = LLMAdapter()
        original = _set_provider_settings()
        try:
            payload = {"choices": [{"message": {"content": '{"schema_version":"query.v1","mode":"query"}'}}]}
            with patch("common.adapter.httpx.AsyncClient.post", new=AsyncMock(return_value=_FakeResponse(payload))):
                raised = False
                try:
                    await adapter.answer_query("what now", {"context": "x"})
                except Exception:
                    raised = True
                assert raised
        finally:
            _restore_provider_settings(original)

    asyncio.run(_run())


def test_plan_malformed_payload_falls_back_to_deterministic_plan():
    async def _run():
        adapter = LLMAdapter()
        original = _set_provider_settings()
        try:
            payload = {"choices": [{"message": {"content": '{"today_plan":"bad"}'}}]}
            plan_state = {
                "schema_version": "plan.v1",
                "plan_window": "today",
                "generated_at": "2026-02-10T00:00:00Z",
                "today_plan": [{"task_id": "tsk_1", "rank": 1, "title": "Do x"}],
                "next_actions": [],
                "blocked_items": [],
            }
            with patch("common.adapter.httpx.AsyncClient.post", new=AsyncMock(return_value=_FakeResponse(payload))):
                out = await adapter.rewrite_plan(plan_state)
            assert out["schema_version"] == "plan.v1"
            assert isinstance(out["today_plan"], list)
        finally:
            _restore_provider_settings(original)

    asyncio.run(_run())


def test_summarize_success_shape():
    async def _run():
        adapter = LLMAdapter()
        original = _set_provider_settings()
        try:
            payload = {
                "choices": [{"message": {"content": '{"summary_text":"Summary ok","facts":["a","b"]}'}}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            }
            with patch("common.adapter.httpx.AsyncClient.post", new=AsyncMock(return_value=_FakeResponse(payload))):
                out = await adapter.summarize_memory("context")
            assert out["summary_text"] == "Summary ok"
            assert out["facts"] == ["a", "b"]
            assert out["usage"]["input_tokens"] == 5
        finally:
            _restore_provider_settings(original)

    asyncio.run(_run())


def test_retry_is_bounded_and_succeeds_after_transient_timeout():
    async def _run():
        adapter = LLMAdapter()
        original = _set_provider_settings()
        try:
            good = _FakeResponse(
                {"choices": [{"message": {"content": '{"summary_text":"ok","facts":[]}'}}], "usage": {}}
            )
            post = AsyncMock(side_effect=[httpx.TimeoutException("t1"), httpx.TimeoutException("t2"), good])
            with patch("common.adapter.httpx.AsyncClient.post", new=post):
                out = await adapter.summarize_memory("ctx")
            assert out["summary_text"] == "ok"
            assert post.await_count == 3
        finally:
            _restore_provider_settings(original)

    asyncio.run(_run())


def test_retry_exhaustion_uses_fallback_policy():
    async def _run():
        adapter = LLMAdapter()
        original = _set_provider_settings()
        try:
            post = AsyncMock(side_effect=httpx.TimeoutException("all failed"))
            with patch("common.adapter.httpx.AsyncClient.post", new=post):
                out = await adapter.extract_structured_updates("ctx")
            assert out == {"tasks": [], "goals": [], "problems": [], "links": []}
            assert post.await_count == settings.LLM_MAX_RETRIES + 1
        finally:
            _restore_provider_settings(original)

    asyncio.run(_run())
