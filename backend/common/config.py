from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Shared
    APP_ENV: str = "dev"
    APP_PORT: int = 8000
    DATABASE_URL: str
    REDIS_URL: str
    APP_AUTH_BEARER_TOKENS: str  # Comma-separated
    APP_AUTH_TOKEN_USER_MAP: Optional[str] = None  # token:user_id pairs, comma-separated
    SESSION_INACTIVITY_MINUTES: int = 120
    IDEMPOTENCY_TTL_HOURS: int = 24
    RECENT_CONTEXT_TTL_HOURS: int = 48

    # Provider
    LLM_PROVIDER: str = "grok"
    LLM_API_KEY: str
    LLM_API_BASE_URL: str = ""
    LLM_TIMEOUT_SECONDS: int = 30
    LLM_MAX_RETRIES: int = 2
    LLM_RETRY_BACKOFF_SECONDS: float = 1.0
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
    TELEGRAM_LINK_TOKEN_TTL_SECONDS: int = 900
    TELEGRAM_BOT_USERNAME: Optional[str] = None
    TELEGRAM_DEEP_LINK_BASE_URL: Optional[str] = None

    # Phase 5 Todoist Settings
    TODOIST_TOKEN: Optional[str] = None
    TODOIST_API_BASE: str = "https://api.todoist.com/rest/v2"

    # Phase 6 Hardening Settings
    OPERATIONS_METRICS_WINDOW_HOURS: int = 24
    WORKER_ALERT_FAILURE_THRESHOLD: int = 5
    BACKUP_RETENTION_DAYS: int = 14

    # Phase 7 Auth, Rate Limit, Cost Settings
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_CAPTURE_PER_WINDOW: int = 20
    RATE_LIMIT_QUERY_PER_WINDOW: int = 30
    RATE_LIMIT_PLAN_PER_WINDOW: int = 15
    COST_INPUT_PER_MILLION_USD: float = 0.20
    COST_CACHED_INPUT_PER_MILLION_USD: float = 0.05
    COST_OUTPUT_PER_MILLION_USD: float = 0.50

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def auth_tokens(self) -> List[str]:
        return [t.strip() for t in self.APP_AUTH_BEARER_TOKENS.split(",") if t.strip()]

    @property
    def token_user_map(self) -> dict:
        if not self.APP_AUTH_TOKEN_USER_MAP:
            return {}
        mapping = {}
        for pair in self.APP_AUTH_TOKEN_USER_MAP.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            token, user_id = pair.split(":", 1)
            token = token.strip()
            user_id = user_id.strip()
            if token and user_id:
                mapping[token] = user_id
        return mapping

settings = Settings()
