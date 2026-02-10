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

    # Phase 2 Memory Settings
    MEMORY_CONTEXT_MAX_TOKENS: int = 3000
    MEMORY_HOT_TURNS_LIMIT: int = 8
    MEMORY_RELATED_ENTITIES_LIMIT: int = 25
    TRANSCRIPT_RETENTION_DAYS: int = 30

    # Phase 3 Planning and Query Settings
    PLAN_TOP_N_TODAY: int = 6
    PLAN_TOP_N_NEXT: int = 8
    PLAN_WEIGHT_URGENCY: float = 4.0
    PLAN_WEIGHT_IMPACT: float = 3.0
    PLAN_WEIGHT_GOAL_ALIGNMENT: float = 2.0
    PLAN_WEIGHT_STALENESS: float = 1.0
    PLAN_WEIGHT_BLOCKER_PENALTY: float = 6.0
    QUERY_MAX_TOKENS: int = 2000

    # Phase 4 Telegram Settings
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = None
    TELEGRAM_API_BASE: str = "https://api.telegram.org"
    TELEGRAM_COMMAND_TIMEOUT_SECONDS: int = 20
    TELEGRAM_DEFAULT_SOURCE: str = "telegram"

    # Phase 5 Todoist Settings
    TODOIST_TOKEN: Optional[str] = None
    TODOIST_API_BASE: str = "https://api.todoist.com/rest/v2"

    # Phase 6 Hardening Settings
    OPERATIONS_METRICS_WINDOW_HOURS: int = 24
    WORKER_ALERT_FAILURE_THRESHOLD: int = 5
    BACKUP_RETENTION_DAYS: int = 14

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def auth_tokens(self) -> List[str]:
        return [t.strip() for t in self.APP_AUTH_BEARER_TOKENS.split(",") if t.strip()]

settings = Settings()
