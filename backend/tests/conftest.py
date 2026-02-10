"""Stable shared fixtures for tests.

Design goal: avoid async fixture loop injection and keep test boundaries explicit.
"""
import os
from unittest.mock import AsyncMock, patch

import pytest

# Must be set before importing app modules.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["APP_AUTH_BEARER_TOKENS"] = "test_token"
os.environ["LLM_API_KEY"] = "test_key"
os.environ["LLM_MODEL_EXTRACT"] = "test-model"
os.environ["LLM_MODEL_QUERY"] = "test-model"
os.environ["LLM_MODEL_PLAN"] = "test-model"
os.environ["LLM_MODEL_SUMMARIZE"] = "test-model"
os.environ["TELEGRAM_BOT_TOKEN"] = "test_bot_token"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "test_secret"

from api.main import app, get_db


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.rpush = AsyncMock(return_value=1)
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock(return_value=True)
    r.ping = AsyncMock(return_value=True)
    return r


@pytest.fixture
def mock_send():
    with patch("api.main.send_message", new_callable=AsyncMock) as m:
        m.return_value = {"ok": True}
        yield m


@pytest.fixture
def mock_extract():
    with patch("api.main.adapter") as m:
        m.extract_structured_updates = AsyncMock(
            return_value={"tasks": [], "goals": [], "problems": [], "links": []}
        )
        yield m


@pytest.fixture
def mock_db():
    db = AsyncMock()
    result = AsyncMock()
    result.rowcount = 1
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock(return_value=None)
    return db


@pytest.fixture
def app_no_db(mock_redis, mock_send, mock_extract, mock_db):
    async def _stub_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _stub_get_db
    with patch("api.main.redis_client", mock_redis):
        yield app
    app.dependency_overrides.clear()
