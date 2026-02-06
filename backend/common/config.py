from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Shared
    APP_ENV: str = "dev"
    APP_PORT: int = 8000
    DATABASE_URL: str
    REDIS_URL: str
    APP_AUTH_BEARER_TOKENS: str  # Comma-separated
    SESSION_INACTIVITY_MINUTES: int = 120
    IDEMPOTENCY_TTL_HOURS: int = 24
    RECENT_CONTEXT_TTL_HOURS: int = 48

    # Provider
    LLM_PROVIDER: str = "grok"
    LLM_API_KEY: str
    LLM_MODEL_EXTRACT: str
    LLM_MODEL_QUERY: str
    LLM_MODEL_PLAN: str
    LLM_MODEL_SUMMARIZE: str
    PROMPT_VERSION_EXTRACT: str = "v1"
    PROMPT_VERSION_QUERY: str = "v1"
    PROMPT_VERSION_PLAN: str = "v1"
    PROMPT_VERSION_SUMMARIZE: str = "v1"

    # Feature Flags
    FEATURE_PLAN_REFRESH: bool = False
    FEATURE_TODOIST_SYNC: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def auth_tokens(self) -> List[str]:
        return [t.strip() for t in self.APP_AUTH_BEARER_TOKENS.split(",") if t.strip()]

settings = Settings()
