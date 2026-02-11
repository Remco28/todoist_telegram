import logging
import re
import httpx
from html import escape as _html_escape
from typing import Optional, Tuple, Dict, Any, List
from common.config import settings


def escape_html(text: str) -> str:
    """Escape <, >, & for Telegram HTML parse mode."""
    return _html_escape(str(text), quote=False)

logger = logging.getLogger(__name__)

TELEGRAM_TEXT_MAX_LEN = 4096
QUERY_PREFIXES = (
    "what",
    "which",
    "who",
    "when",
    "where",
    "why",
    "how",
    "show",
    "list",
    "summarize",
    "tell me",
    "do i",
    "can i",
    "am i",
    "is there",
    "are there",
)

def verify_telegram_secret(headers: Dict[str, str]) -> bool:
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        return True
    return headers.get("X-Telegram-Bot-Api-Secret-Token") == settings.TELEGRAM_WEBHOOK_SECRET

def parse_update(update_json: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extracts basic message info from a Telegram update.
    Returns dict with chat_id and text if it's a message, else None.
    """
    message = update_json.get("message")
    if not message:
        return None
    
    chat = message.get("chat")
    text = message.get("text")
    
    if chat and text:
        return {
            "chat_id": str(chat.get("id")),
            "text": text,
            "username": chat.get("username")
        }
    return None

def extract_command(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parses a string for a command like /start arg1 arg2.
    Returns (command, args_string).
    """
    if not text.startswith("/"):
        return None, None
    
    parts = text.split(maxsplit=1)
    command = parts[0].lower().split("@")[0]  # strip @botname suffix
    args = parts[1] if len(parts) > 1 else None
    return command, args


def is_query_like_text(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    if "?" in normalized:
        return True
    collapsed = re.sub(r"\s+", " ", normalized)
    return any(collapsed.startswith(prefix + " ") or collapsed == prefix for prefix in QUERY_PREFIXES)

async def send_message(chat_id: str, text: str) -> Dict[str, Any]:
    """
    Sends a message back to Telegram.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not configured.")
        return {"ok": False, "error": "token_missing"}

    url = f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    safe_text = (text or "")[:TELEGRAM_TEXT_MAX_LEN]

    try:
        async with httpx.AsyncClient(timeout=settings.TELEGRAM_COMMAND_TIMEOUT_SECONDS) as client:
            # First try with HTML formatting.
            payload = {
                "chat_id": chat_id,
                "text": safe_text,
                "parse_mode": "HTML",
            }
            resp = await client.post(url, json=payload)
            if resp.status_code < 400:
                return resp.json()

            # Common 400 case is parse issues; retry once with plain text.
            logger.warning(
                "Telegram send failed with HTML mode (status=%s, body=%s). Retrying without parse_mode.",
                resp.status_code,
                resp.text,
            )
            payload = {
                "chat_id": chat_id,
                "text": safe_text,
            }
            resp = await client.post(url, json=payload)
            if resp.status_code < 400:
                return resp.json()

            logger.error(
                "Failed to send Telegram message (status=%s, body=%s)",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()
            return {"ok": False, "error": "telegram_send_failed"}
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return {"ok": False, "error": str(e)}

def format_today_plan(plan_payload: Dict[str, Any]) -> str:
    """
    Converts PlanResponseV1 to human-friendly Telegram text.
    """
    lines = ["<b>📅 Your Today Plan</b>", ""]
    
    today_plan = plan_payload.get("today_plan", [])
    if not today_plan:
        lines.append("Nothing on your plan for today! Add a thought to get started.")
    else:
        for idx, item in enumerate(today_plan):
            lines.append(f"{idx+1}. <code>{escape_html(item['task_id'])}</code>: {escape_html(item['title'])}")
            if item.get("reason"):
                lines.append(f"   <i>{escape_html(item['reason'])}</i>")

    blocked = plan_payload.get("blocked_items", [])
    if blocked:
        lines.append("")
        lines.append("<b>🚧 Blocked Items</b>")
        for item in blocked:
            lines.append(f"• {escape_html(item['title'])} (Reason: {', '.join(escape_html(b) for b in item['blocked_by'])})")
            
    return "\n".join(lines)

def format_plan_refresh_ack(job_id: str) -> str:
    return f"🔄 Plan refresh enqueued. (ID: <code>{job_id}</code>)\nI'll update you when it's ready!"

def format_focus_mode(plan_payload: Dict[str, Any]) -> str:
    """
    Formats the top 1-3 items for /focus.
    """
    today_plan = plan_payload.get("today_plan", [])
    if not today_plan:
        return "Nothing to focus on right now. Use /plan to refresh."
    
    top_items = today_plan[:3]
    lines = ["<b>🎯 Current Focus</b>", ""]
    for idx, item in enumerate(top_items):
        lines.append(f"<b>{idx+1}. {escape_html(item['title'])}</b>")
        lines.append(f"   ID: <code>{escape_html(item['task_id'])}</code>")
        
    return "\n".join(lines)

def format_capture_ack(applied: Dict[str, int]) -> str:
    """
    Summarizes applied changes for capture/thought.
    """
    parts = []
    if applied.get("tasks_created"): parts.append(f"{applied['tasks_created']} task(s) created")
    if applied.get("tasks_updated"): parts.append(f"{applied['tasks_updated']} task(s) updated")
    if applied.get("goals_created"): parts.append(f"{applied['goals_created']} goal(s) created")
    if applied.get("problems_created"): parts.append(f"{applied['problems_created']} problem(s) created")
    if applied.get("links_created"): parts.append(f"{applied['links_created']} link(s) created")
    
    if not parts:
        return "Thought logged. No actionable entities extracted."
    
    return "✅ Captured: " + ", ".join(parts) + "."


def format_query_answer(answer: str, follow_up: Optional[str] = None) -> str:
    raw = (answer or "").strip()
    if not raw:
        return "I don't have an answer yet."

    # Break into readable lines by sentence boundaries.
    chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+", raw) if c.strip()]
    if not chunks:
        chunks = [raw]

    lines = ["<b>Answer</b>", ""]
    for chunk in chunks[:8]:
        lines.append(f"• {escape_html(chunk)}")
    if len(chunks) > 8:
        lines.append("• ...")
    if follow_up:
        lines.extend(["", f"<i>Follow-up:</i> {escape_html(follow_up)}"])
    return "\n".join(lines)
