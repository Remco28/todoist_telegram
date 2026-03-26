from datetime import datetime
from typing import Any, Dict


def run_external_preflight_required(*, helpers: Dict[str, Any]) -> bool:
    return helpers["settings"].APP_ENV.strip().lower() in {"staging", "prod", "production"}


def run_http_ok_status(code: int) -> bool:
    return 200 <= code < 300


async def run_check_llm_credentials(*, helpers: Dict[str, Any]) -> Dict[str, Any]:
    base = (helpers["settings"].LLM_API_BASE_URL or "").strip().rstrip("/")
    api_key = (helpers["settings"].LLM_API_KEY or "").strip()
    if not base:
        return {"ok": False, "reason": "llm_base_url_missing"}
    if not api_key:
        return {"ok": False, "reason": "llm_api_key_missing"}
    try:
        async with helpers["httpx"].AsyncClient(timeout=helpers["settings"].PREFLIGHT_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if run_http_ok_status(response.status_code):
            return {"ok": True}
        if response.status_code in {401, 403}:
            return {"ok": False, "reason": "llm_auth_failed"}
        return {"ok": False, "reason": f"llm_http_{response.status_code}"}
    except helpers["httpx"].HTTPError:
        return {"ok": False, "reason": "llm_unreachable"}


async def run_check_telegram_credentials(*, helpers: Dict[str, Any]) -> Dict[str, Any]:
    token = (helpers["settings"].TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        return {"ok": True, "skipped": True, "reason": "telegram_token_not_configured"}
    base = (helpers["settings"].TELEGRAM_API_BASE or "https://api.telegram.org").rstrip("/")
    try:
        async with helpers["httpx"].AsyncClient(timeout=helpers["settings"].PREFLIGHT_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{base}/bot{token}/getMe")
        if not run_http_ok_status(response.status_code):
            if response.status_code in {401, 403}:
                return {"ok": False, "reason": "telegram_auth_failed"}
            return {"ok": False, "reason": f"telegram_http_{response.status_code}"}
        payload = response.json() if response.content else {}
        if isinstance(payload, dict) and payload.get("ok") is True:
            return {"ok": True}
        return {"ok": False, "reason": "telegram_auth_failed"}
    except (helpers["httpx"].HTTPError, ValueError):
        return {"ok": False, "reason": "telegram_unreachable"}


async def run_compute_preflight_report(*, helpers: Dict[str, Any]) -> Dict[str, Any]:
    llm = await helpers["_check_llm_credentials"]()
    telegram = await helpers["_check_telegram_credentials"]()
    checks = {"llm": llm, "telegram": telegram}
    return {
        "ok": all(isinstance(item, dict) and item.get("ok") is True for item in checks.values()),
        "checks": checks,
        "checked_at": helpers["utc_now"]().isoformat(),
    }


async def run_get_preflight_report(force: bool = False, *, helpers: Dict[str, Any]) -> Dict[str, Any]:
    now = helpers["utc_now"]()
    async with helpers["_preflight_lock"]:
        checked_at = helpers["_preflight_cache"].get("checked_at")
        cached = helpers["_preflight_cache"].get("report")
        fresh = (
            isinstance(checked_at, datetime)
            and isinstance(cached, dict)
            and (now - checked_at).total_seconds() < max(1, helpers["settings"].PREFLIGHT_CACHE_SECONDS)
        )
        if not force and fresh:
            return cached
        report = await helpers["_compute_preflight_report"]()
        helpers["_preflight_cache"]["checked_at"] = now
        helpers["_preflight_cache"]["report"] = report
        return report
