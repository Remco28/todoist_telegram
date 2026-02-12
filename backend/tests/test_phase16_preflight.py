import asyncio
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient


def _get(asgi_app, url):
    async def _call():
        transport = ASGITransport(app=asgi_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(url)

    return asyncio.run(_call())


def test_health_ready_returns_503_when_preflight_fails(app_no_db):
    report = {
        "ok": False,
        "checked_at": "2026-02-12T00:00:00+00:00",
        "checks": {"llm": {"ok": False, "reason": "llm_auth_failed"}, "telegram": {"ok": True}},
    }
    with patch("api.main._external_preflight_required", return_value=True), patch(
        "api.main._get_preflight_report", new_callable=AsyncMock, return_value=report
    ):
        response = _get(app_no_db, "/health/ready")
        assert response.status_code == 503
        assert "Preflight failed: llm:llm_auth_failed" in response.text


def test_health_ready_returns_ready_when_preflight_ok(app_no_db):
    report = {
        "ok": True,
        "checked_at": "2026-02-12T00:00:00+00:00",
        "checks": {"llm": {"ok": True}, "telegram": {"ok": True}},
    }
    with patch("api.main._external_preflight_required", return_value=True), patch(
        "api.main._get_preflight_report", new_callable=AsyncMock, return_value=report
    ):
        response = _get(app_no_db, "/health/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


def test_health_preflight_skipped_in_dev_like_env(app_no_db):
    with patch("api.main._external_preflight_required", return_value=False):
        response = _get(app_no_db, "/health/preflight")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "skipped"


def test_health_preflight_returns_checks(app_no_db):
    report = {
        "ok": True,
        "checked_at": "2026-02-12T00:00:00+00:00",
        "checks": {"llm": {"ok": True}, "telegram": {"ok": True}},
    }
    with patch("api.main._external_preflight_required", return_value=True), patch(
        "api.main._get_preflight_report", new_callable=AsyncMock, return_value=report
    ):
        response = _get(app_no_db, "/health/preflight")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["checks"]["llm"]["ok"] is True
