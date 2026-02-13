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

_INTERNAL_ID_PATTERNS = (
    re.compile(r"\[(?:tsk|gol|prb|lnk)_[A-Za-z0-9]+\]"),
    re.compile(r"\((?:tsk|gol|prb|lnk)_[A-Za-z0-9]+\)"),
    re.compile(r"\b(?:tsk|gol|prb|lnk)_[A-Za-z0-9]+\b"),
)


def strip_internal_ids(text: str) -> str:
    cleaned = text or ""
    for pattern in _INTERNAL_ID_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    # Normalize spacing around punctuation after removal.
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    return cleaned.strip()


def render_markdownish_text(text: str) -> str:
    """Render a small markdown-like subset safely for Telegram HTML mode.

    Currently supports:
    - **bold**
    """
    if not text:
        return ""
    parts: List[str] = []
    tokens = re.split(r"(\*\*[^*\n][^*\n]*\*\*)", text)
    for token in tokens:
        if token.startswith("**") and token.endswith("**") and len(token) > 4:
            inner = token[2:-2]
            parts.append(f"<b>{escape_html(inner)}</b>")
        else:
            parts.append(escape_html(token))
    return "".join(parts)

def verify_telegram_secret(headers: Dict[str, str]) -> bool:
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        return True
    return headers.get("X-Telegram-Bot-Api-Secret-Token") == settings.TELEGRAM_WEBHOOK_SECRET

def parse_update(update_json: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract basic update info from Telegram payload.
    Supports message and callback_query updates.
    """
    message = update_json.get("message")
    if message:
        chat = message.get("chat")
        text = message.get("text")
        if chat and text:
            message_id = message.get("message_id")
            client_msg_id = None
            if message_id is not None:
                client_msg_id = f"tg:{chat.get('id')}:{message_id}"
            return {
                "kind": "message",
                "chat_id": str(chat.get("id")),
                "text": text,
                "username": chat.get("username"),
                "client_msg_id": client_msg_id,
            }

    callback = update_json.get("callback_query")
    if callback and isinstance(callback, dict):
        cb_message = callback.get("message") or {}
        cb_chat = cb_message.get("chat") or {}
        data = callback.get("data")
        if cb_chat and isinstance(data, str):
            from_user = callback.get("from") or {}
            return {
                "kind": "callback",
                "chat_id": str(cb_chat.get("id")),
                "username": from_user.get("username") or cb_chat.get("username"),
                "callback_query_id": callback.get("id"),
                "callback_data": data,
                "text": "",
            }

    return None


def build_draft_reply_markup(draft_id: str) -> Dict[str, Any]:
    # Keep labels short for compact mobile rendering.
    return {
        "inline_keyboard": [
            [
                {"text": "Yes", "callback_data": f"draft:confirm:{draft_id}"},
                {"text": "Edit", "callback_data": f"draft:edit:{draft_id}"},
                {"text": "No", "callback_data": f"draft:discard:{draft_id}"},
            ]
        ]
    }


async def answer_callback_query(callback_query_id: str, text: Optional[str] = None) -> Dict[str, Any]:
    if not settings.TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "token_missing"}
    url = f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]
    try:
        async with httpx.AsyncClient(timeout=settings.TELEGRAM_COMMAND_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code < 400:
                return resp.json()
            logger.error(
                "Failed to answer callback query (status=%s, body=%s)",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()
            return {"ok": False, "error": "telegram_callback_failed"}
    except Exception as e:
        logger.error(f"Failed to answer callback query: {e}")
        return {"ok": False, "error": str(e)}


async def edit_message(chat_id: str, message_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not settings.TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "token_missing"}
    url = f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/editMessageText"
    safe_text = (text or "")[:TELEGRAM_TEXT_MAX_LEN]
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": safe_text,
        "parse_mode": "HTML",
    }
    if isinstance(reply_markup, dict):
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=settings.TELEGRAM_COMMAND_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code < 400:
                return resp.json()
            logger.warning(
                "Telegram edit failed (status=%s, body=%s).",
                resp.status_code,
                resp.text,
            )
            return {"ok": False, "error": f"status_{resp.status_code}"}
    except Exception as e:
        logger.error(f"Failed to edit Telegram message: {e}")
        return {"ok": False, "error": str(e)}


async def send_message(chat_id: str, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Sends a message back to Telegram.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not configured.")
        return {"ok": False, "error": "token_missing"}

    url = f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = split_telegram_text(text or "", TELEGRAM_TEXT_MAX_LEN)
    if not chunks:
        chunks = [""]

    try:
        async with httpx.AsyncClient(timeout=settings.TELEGRAM_COMMAND_TIMEOUT_SECONDS) as client:
            # Send in chunks to avoid Telegram hard length cap.
            last_json: Dict[str, Any] = {"ok": True}
            total_chunks = len(chunks)
            for idx, chunk in enumerate(chunks):
                prefix = f"<i>Part {idx + 1}/{total_chunks}</i>\n\n" if total_chunks > 1 else ""
                safe_text = prefix + chunk

                payload: Dict[str, Any] = {
                    "chat_id": chat_id,
                    "text": safe_text,
                    "parse_mode": "HTML",
                }
                # Keep inline controls on the final chunk only.
                if isinstance(reply_markup, dict) and idx == total_chunks - 1:
                    payload["reply_markup"] = reply_markup
                resp = await client.post(url, json=payload)
                if resp.status_code < 400:
                    last_json = resp.json()
                    continue

                # Common 400 case is parse issues; retry once with plain text.
                logger.warning(
                    "Telegram send failed with HTML mode (status=%s, body=%s). Retrying without parse_mode.",
                    resp.status_code,
                    resp.text,
                )
                payload = {
                    "chat_id": chat_id,
                    "text": re.sub(r"</?i>", "", prefix) + chunk,
                }
                if isinstance(reply_markup, dict) and idx == total_chunks - 1:
                    payload["reply_markup"] = reply_markup
                resp = await client.post(url, json=payload)
                if resp.status_code < 400:
                    last_json = resp.json()
                    continue

                logger.error(
                    "Failed to send Telegram message (status=%s, body=%s)",
                    resp.status_code,
                    resp.text,
                )
                resp.raise_for_status()
                return {"ok": False, "error": "telegram_send_failed"}
            return last_json
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return {"ok": False, "error": str(e)}

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
            lines.append(f"{idx+1}. {escape_html(item['title'])}")
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
    return "🔄 Plan refresh enqueued.\nI'll update you when it's ready!"

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
    raw = strip_internal_ids((answer or "").strip())
    if not raw:
        return "I don't have an answer yet."

    lines = ["<b>Answer</b>", ""]

    # Keep model line structure when present; otherwise split into sentence bullets.
    structured_lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(structured_lines) > 1:
        for line in structured_lines:
            lines.append(render_markdownish_text(line))
    else:
        chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+", raw) if c.strip()]
        for chunk in chunks:
            lines.append(f"• {render_markdownish_text(chunk)}")

    if follow_up:
        lines.extend(["", f"<i>Follow-up:</i> {escape_html(strip_internal_ids(follow_up))}"])
    return "\n".join(lines)


def split_telegram_text(text: str, max_len: int = TELEGRAM_TEXT_MAX_LEN) -> List[str]:
    """Split long text into Telegram-safe chunks while preferring line boundaries."""
    if len(text) <= max_len:
        return [text]

    lines = text.splitlines(keepends=True)
    chunks: List[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for line in lines:
        if len(line) > max_len:
            flush()
            remaining = line
            while len(remaining) > max_len:
                split_at = remaining.rfind(" ", 0, max_len)
                if split_at <= 0:
                    split_at = max_len
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:]
            if remaining:
                current = remaining
            continue

        if len(current) + len(line) > max_len:
            flush()
        current += line

    flush()
    return chunks if chunks else [text[:max_len]]
