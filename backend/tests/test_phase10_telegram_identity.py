import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from api.main import (
    app,
    get_db,
    _consume_telegram_link_token,
    _hash_link_token,
    _issue_telegram_link_token,
)
from common.config import settings
from common.models import TelegramLinkToken, TelegramUserMap


class _FakeResult:
    def __init__(self, one_or_none=None):
        self._one_or_none = one_or_none

    def scalar_one_or_none(self):
        return self._one_or_none


def _db_override(fake_db):
    async def _ctx():
        yield fake_db

    return _ctx


def test_link_token_endpoint_requires_auth():
    async def _run():
        fake_db = AsyncMock()
        fake_db.commit = AsyncMock()

        app.dependency_overrides[get_db] = _db_override(fake_db)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/v1/integrations/telegram/link_token")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()

    asyncio.run(_run())


def test_link_token_endpoint_returns_token_and_stores_hash_only():
    async def _run():
        fake_db = AsyncMock()
        fake_db.add = MagicMock()
        fake_db.commit = AsyncMock()

        app.dependency_overrides[get_db] = _db_override(fake_db)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/v1/integrations/telegram/link_token",
                    headers={"Authorization": "Bearer test_token"},
                )
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["link_token"]
            assert "expires_at" in payload

            fake_db.add.assert_called_once()
            stored = fake_db.add.call_args.args[0]
            assert isinstance(stored, TelegramLinkToken)
            assert stored.token_hash != payload["link_token"]
            assert stored.token_hash == _hash_link_token(payload["link_token"])
        finally:
            app.dependency_overrides.clear()

    asyncio.run(_run())


def test_consume_link_token_marks_token_used_and_maps_chat():
    async def _run():
        raw_token = "abc123"
        token_row = TelegramLinkToken(
            id="tlt_1",
            token_hash=_hash_link_token(raw_token),
            user_id="usr_x",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            consumed_at=None,
            created_at=datetime.utcnow(),
        )
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                _FakeResult(one_or_none=token_row),
                _FakeResult(one_or_none=None),
            ]
        )
        fake_db.add = MagicMock()
        fake_db.commit = AsyncMock()

        ok = await _consume_telegram_link_token("12345", "tester", raw_token, fake_db)
        assert ok is True
        assert token_row.consumed_at is not None
        fake_db.add.assert_called_once()
        created_map = fake_db.add.call_args.args[0]
        assert isinstance(created_map, TelegramUserMap)
        assert created_map.chat_id == "12345"
        assert created_map.user_id == "usr_x"

    asyncio.run(_run())


def test_consume_link_token_rejects_expired_or_consumed():
    async def _run():
        raw_token = "abc123"
        expired = TelegramLinkToken(
            id="tlt_expired",
            token_hash=_hash_link_token(raw_token),
            user_id="usr_x",
            expires_at=datetime.utcnow() - timedelta(minutes=1),
            consumed_at=None,
            created_at=datetime.utcnow(),
        )
        fake_db_expired = AsyncMock()
        fake_db_expired.execute = AsyncMock(return_value=_FakeResult(one_or_none=expired))
        assert await _consume_telegram_link_token("12345", "tester", raw_token, fake_db_expired) is False

        consumed = TelegramLinkToken(
            id="tlt_used",
            token_hash=_hash_link_token(raw_token),
            user_id="usr_x",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            consumed_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        fake_db_consumed = AsyncMock()
        fake_db_consumed.execute = AsyncMock(return_value=_FakeResult(one_or_none=consumed))
        assert await _consume_telegram_link_token("12345", "tester", raw_token, fake_db_consumed) is False

    asyncio.run(_run())


def test_issue_link_token_supports_non_expiring_mode():
    async def _run():
        fake_db = AsyncMock()
        fake_db.add = MagicMock()
        fake_db.commit = AsyncMock()
        old_ttl = settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS
        settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS = 0
        try:
            response = await _issue_telegram_link_token("usr_dev", fake_db)
            assert response.link_token
            assert response.expires_at.year >= 2100
        finally:
            settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS = old_ttl

    asyncio.run(_run())
