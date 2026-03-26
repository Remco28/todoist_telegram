import logging
import re
import httpx
from datetime import date, datetime, timezone
from html import escape as _html_escape
from typing import Optional, Tuple, Dict, Any, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
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
_TASK_TITLE_WRAPPER_PATTERNS = (
    re.compile(
        r"^(?:move|set|reschedule)\s+(?P<quote>['\"])?(?P<title>.+?)(?P=quote)?\s+(?:to|for)\s+"
        r"(?:today|tomorrow|tonight|this week|next week|this month|next month)\.?$",
        re.IGNORECASE,
    ),
)
PLAN_STALE_WARNING_SECONDS = 300
PROJECT_MARKER = "▣"


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


def user_facing_task_title(title: Any) -> str:
    text = re.sub(r"\s+", " ", str(title or "").strip())
    if not text:
        return ""
    for pattern in _TASK_TITLE_WRAPPER_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        inner = re.sub(r"\s+", " ", (match.group("title") or "").strip())
        if inner:
            return inner
    return text

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


def build_applied_reply_markup(applied: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    items = applied.get("items")
    normalized_items = items if isinstance(items, list) else []
    overflow = max(0, len(normalized_items) - 6)
    work_item_batch_id = str(applied.get("work_item_action_batch_id") or "").strip()
    reminder_batch_id = str(applied.get("reminder_action_batch_id") or "").strip()
    try:
        work_item_subtasks_count = max(0, int(applied.get("work_item_subtasks_count") or 0))
    except (TypeError, ValueError):
        work_item_subtasks_count = 0

    first_row: List[Dict[str, str]] = []
    if overflow > 0:
        if work_item_batch_id and reminder_batch_id:
            first_row.extend(
                [
                    {"text": "Show tasks", "callback_data": f"batch:show:{work_item_batch_id}"},
                    {"text": "Show reminders", "callback_data": f"batch:show:{reminder_batch_id}"},
                ]
            )
        else:
            batch_id = work_item_batch_id or reminder_batch_id
            if batch_id:
                first_row.append({"text": "Show more", "callback_data": f"batch:show:{batch_id}"})
    if work_item_subtasks_count > 0 and work_item_batch_id:
        first_row.append({"text": "Show subtasks", "callback_data": f"batch:subtasks:{work_item_batch_id}"})
    if not first_row:
        return None

    rows = [first_row[:2]]
    if len(first_row) > 2:
        rows.append(first_row[2:4])
    return {"inline_keyboard": rows}


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


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _localize_datetime(value: datetime) -> datetime:
    tz_name = (settings.APP_TIMEZONE or "").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    return value.astimezone(tz)


def _format_relative_seconds(seconds: int) -> str:
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = max(1, seconds // 60)
        return f"{minutes} min ago" if minutes == 1 else f"{minutes} mins ago"
    if seconds < 86400:
        hours = max(1, seconds // 3600)
        return f"{hours} hr ago" if hours == 1 else f"{hours} hrs ago"
    days = max(1, seconds // 86400)
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def _format_local_timestamp(value: datetime) -> str:
    localized = _localize_datetime(value)
    hour = localized.strftime("%I").lstrip("0") or "12"
    return f"{localized.strftime('%b')} {localized.day}, {hour}:{localized.strftime('%M %p')} local"


def _local_today() -> date:
    return _localize_datetime(_utc_now()).date()


def _parse_due_date_value(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return _localize_datetime(value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)).date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    parsed_dt = _parse_iso_datetime(text)
    if parsed_dt is not None:
        return _localize_datetime(parsed_dt).date()
    return None


def _format_us_date(value: date) -> str:
    return f"{value.month}/{value.day}/{value.year}"


def _format_due_date_text(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        original_text = value.strip()
    else:
        original_text = ""
    parsed = _parse_due_date_value(value)
    if parsed is None:
        if not original_text:
            return None
        return f"Due {original_text}"

    delta_days = (parsed - _local_today()).days
    relative: Optional[str] = None
    if delta_days == 0:
        relative = "today"
    elif delta_days == 1:
        relative = "tomorrow"
    elif delta_days > 1 and delta_days <= 14:
        relative = f"in {delta_days} days"
    elif delta_days < 0:
        overdue_days = abs(delta_days)
        relative = f"{overdue_days} day overdue" if overdue_days == 1 else f"{overdue_days} days overdue"

    formatted = f"Due {_format_us_date(parsed)}"
    if relative:
        formatted += f" ({relative})"
    return formatted


def _format_plan_freshness(plan_payload: Dict[str, Any]) -> Optional[str]:
    generated_at = _parse_iso_datetime(plan_payload.get("generated_at"))
    if not generated_at:
        return None
    age_seconds = max(0, int((_utc_now() - generated_at.astimezone(timezone.utc)).total_seconds()))
    freshness = f"Updated {_format_relative_seconds(age_seconds)}"
    if plan_payload.get("_served_from_cache") and age_seconds >= PLAN_STALE_WARNING_SECONDS:
        freshness += " from cached plan"
    return f"{freshness} ({_format_local_timestamp(generated_at)})"


def _work_item_kind_text(item: Dict[str, Any]) -> str:
    return str(item.get("kind") or "").strip().lower()


def _render_task_title(item: Dict[str, Any], *, nested: bool = False) -> str:
    title = user_facing_task_title(item.get("title"))
    kind = _work_item_kind_text(item)
    if kind == "project":
        return f"{PROJECT_MARKER} {title}"
    if kind == "subtask" and not nested:
        return f"- {title}"
    return title


def _indent_html(width: int) -> str:
    return "&nbsp;" * max(0, width)


def _work_item_detail_text(item: Dict[str, Any]) -> Optional[str]:
    details: List[str] = []
    status_value = str(item.get("status") or "").strip().lower()
    if status_value == "blocked":
        details.append("blocked")
    due_text = _format_due_date_text(item.get("due_date"))
    if due_text:
        details.append(due_text)
    if not details:
        return None
    return " • ".join(details)


def _append_nested_open_task_lines(
    lines: List[str],
    item: Dict[str, Any],
    children_by_parent: Dict[str, List[Dict[str, Any]]],
    *,
    depth: int,
) -> None:
    indent_width = depth * 3
    lines.append(f"{_indent_html(indent_width)}- {escape_html(_render_task_title(item, nested=True))}")
    details = _work_item_detail_text(item)
    if details:
        lines.append(f"{_indent_html(indent_width + 5)}<i>{escape_html(details)}</i>")
    item_id = str(item.get("id") or "").strip()
    for child in children_by_parent.get(item_id, []):
        _append_nested_open_task_lines(lines, child, children_by_parent, depth=depth + 1)


def _append_open_task_section(
    lines: List[str],
    heading: str,
    roots: List[Dict[str, Any]],
    children_by_parent: Dict[str, List[Dict[str, Any]]],
    *,
    start_index: int,
) -> int:
    if not roots:
        return start_index
    lines.append(f"<b>{escape_html(heading)}</b>")
    for item in roots:
        lines.append(f"{start_index}. {escape_html(_render_task_title(item))}")
        details = _work_item_detail_text(item)
        if details:
            lines.append(f"{_indent_html(5)}<i>{escape_html(details)}</i>")
        item_id = str(item.get('id') or "").strip()
        for child in children_by_parent.get(item_id, []):
            _append_nested_open_task_lines(lines, child, children_by_parent, depth=1)
        start_index += 1
    lines.append("")
    return start_index


def format_today_plan(plan_payload: Dict[str, Any]) -> str:
    """
    Converts PlanResponseV1 to human-friendly Telegram text.
    """
    lines = ["<b>📅 Your Today Plan</b>"]
    freshness = _format_plan_freshness(plan_payload)
    if freshness:
        lines.append(f"<i>{escape_html(freshness)}</i>")
    lines.append("")
    
    today_plan = plan_payload.get("today_plan", [])
    if not today_plan:
        lines.append("Nothing on your plan for today! Add a thought to get started.")
    else:
        for idx, item in enumerate(today_plan):
            lines.append(f"{idx+1}. {escape_html(_render_task_title(item))}")
            if item.get("reason"):
                lines.append(f"{_indent_html(5)}<i>{escape_html(item['reason'])}</i>")

    due_reminders = plan_payload.get("due_reminders", [])
    if due_reminders:
        lines.append("")
        lines.append("<b>⏰ Due Reminders</b>")
        for item in due_reminders[:8]:
            lines.append(f"• {escape_html(item['title'])}")
            remind_at = _parse_iso_datetime(item.get("remind_at"))
            if remind_at:
                lines.append(f"  <i>{escape_html(_format_local_timestamp(remind_at))}</i>")
            if item.get("message"):
                lines.append(f"  {escape_html(item['message'])}")

    blocked = plan_payload.get("blocked_items", [])
    if blocked:
        lines.append("")
        lines.append("<b>🚧 Blocked Items</b>")
        for item in blocked:
            lines.append(f"• {escape_html(user_facing_task_title(item['title']))} (Reason: {', '.join(escape_html(b) for b in item['blocked_by'])})")
            
    return "\n".join(lines)

def format_focus_mode(plan_payload: Dict[str, Any]) -> str:
    """
    Formats the top 1-3 items for /focus.
    """
    today_plan = plan_payload.get("today_plan", [])
    if not today_plan:
        return "Nothing to focus on right now."
    
    top_items = today_plan[:3]
    lines = ["<b>🎯 Current Focus</b>"]
    freshness = _format_plan_freshness(plan_payload)
    if freshness:
        lines.append(f"<i>{escape_html(freshness)}</i>")
    lines.append("")
    for idx, item in enumerate(top_items):
        lines.append(f"<b>{idx+1}. {escape_html(user_facing_task_title(item['title']))}</b>")
        
    return "\n".join(lines)


def format_urgent_tasks(tasks: List[Dict[str, Any]]) -> str:
    lines = ["<b>🚨 Urgent Items</b>", ""]
    if not tasks:
        lines.append("Nothing is marked high priority right now.")
        return "\n".join(lines)

    for idx, task in enumerate(tasks[:12], start=1):
        lines.append(f"{idx}. {escape_html(_render_task_title(task))}")
        details = _work_item_detail_text(task)
        if details:
            lines.append(f"{_indent_html(5)}<i>{escape_html(details)}</i>")
    return "\n".join(lines)


def format_open_tasks(tasks: List[Dict[str, Any]]) -> str:
    lines = ["<b>📝 Open Tasks</b>", ""]
    if not tasks:
        lines.append("You do not have any open tasks right now.")
        return "\n".join(lines)

    visible_tasks = [task for task in tasks[:60] if isinstance(task, dict)]
    by_id = {
        str(task.get("id") or "").strip(): task
        for task in visible_tasks
        if isinstance(task.get("id"), str) and task.get("id")
    }
    children_by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for task in visible_tasks:
        parent_id = str(task.get("parent_id") or "").strip()
        task_id = str(task.get("id") or "").strip()
        if not task_id or not parent_id or parent_id not in by_id:
            continue
        children_by_parent.setdefault(parent_id, []).append(task)

    roots_projects: List[Dict[str, Any]] = []
    roots_tasks: List[Dict[str, Any]] = []
    roots_subtasks: List[Dict[str, Any]] = []
    for task in visible_tasks:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        parent_id = str(task.get("parent_id") or "").strip()
        if parent_id and parent_id in by_id:
            continue
        kind = _work_item_kind_text(task)
        if kind == "project":
            roots_projects.append(task)
        elif kind == "subtask":
            roots_subtasks.append(task)
        else:
            roots_tasks.append(task)

    next_index = 1
    next_index = _append_open_task_section(lines, "Projects", roots_projects, children_by_parent, start_index=next_index)
    next_index = _append_open_task_section(lines, "Tasks", roots_tasks, children_by_parent, start_index=next_index)
    next_index = _append_open_task_section(lines, "Subtasks", roots_subtasks, children_by_parent, start_index=next_index)
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def format_due_today(tasks: List[Dict[str, Any]], reminders: Optional[List[Dict[str, Any]]] = None) -> str:
    lines = ["<b>🗓️ Due Today</b>", ""]
    reminders = reminders if isinstance(reminders, list) else []
    if not tasks and not reminders:
        lines.append("Nothing is due today.")
        return "\n".join(lines)

    if tasks:
        for idx, task in enumerate(tasks[:20], start=1):
            lines.append(f"{idx}. {escape_html(_render_task_title(task))}")
            details = _work_item_detail_text(task)
            if details:
                lines.append(f"{_indent_html(5)}<i>{escape_html(details)}</i>")

    if reminders:
        lines.append("")
        lines.append("<b>⏰ Due Reminders</b>")
        for item in reminders[:8]:
            lines.append(f"• {escape_html(str(item.get('title') or '').strip())}")
            remind_at = _parse_iso_datetime(item.get("remind_at"))
            if remind_at:
                lines.append(f"  <i>{escape_html(_format_local_timestamp(remind_at))}</i>")
            if item.get("message"):
                lines.append(f"  {escape_html(item['message'])}")
    return "\n".join(lines)


def format_due_next_week(
    tasks: List[Dict[str, Any]],
    reminders: Optional[List[Dict[str, Any]]] = None,
    *,
    week_label: Optional[str] = None,
) -> str:
    lines = ["<b>🗓️ Due Next Week</b>"]
    if isinstance(week_label, str) and week_label.strip():
        lines.extend([f"<i>{escape_html(week_label.strip())}</i>", ""])
    else:
        lines.append("")
    reminders = reminders if isinstance(reminders, list) else []
    if not tasks and not reminders:
        lines.append("Nothing is due next week.")
        return "\n".join(lines)

    if tasks:
        for idx, task in enumerate(tasks[:30], start=1):
            lines.append(f"{idx}. {escape_html(_render_task_title(task))}")
            details = _work_item_detail_text(task)
            if details:
                lines.append(f"{_indent_html(5)}<i>{escape_html(details)}</i>")

    if reminders:
        lines.append("")
        lines.append("<b>⏰ Due Reminders</b>")
        for item in reminders[:12]:
            lines.append(f"• {escape_html(str(item.get('title') or '').strip())}")
            remind_at = _parse_iso_datetime(item.get("remind_at"))
            if remind_at:
                lines.append(f"  <i>{escape_html(_format_local_timestamp(remind_at))}</i>")
            if item.get("message"):
                lines.append(f"  {escape_html(item['message'])}")
    return "\n".join(lines)


def format_capture_ack(applied: Dict[str, Any]) -> str:
    """
    Summarizes applied changes for capture/thought.
    """
    items = applied.get("items")
    if isinstance(items, list):
        normalized_items = [
            item
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("group"), str)
            and isinstance(item.get("label"), str)
            and item.get("label").strip()
        ]
        if normalized_items:
            headings = {
                "created": "Created",
                "updated": "Updated",
                "completed": "Completed",
                "archived": "Archived",
                "reminder_created": "Reminders created",
                "reminder_updated": "Reminders updated",
                "reminder_completed": "Reminders completed",
                "reminder_canceled": "Reminders canceled",
                "goal_created": "Goals",
                "problem_created": "Problems",
                "link_created": "Links",
            }
            shown = normalized_items[:6]
            lines = ["<b>Applied changes</b>"]
            seen_groups: List[str] = []
            for item in shown:
                if item["group"] not in seen_groups:
                    seen_groups.append(item["group"])
            for group in seen_groups:
                group_items = [item for item in shown if item["group"] == group]
                if not group_items:
                    continue
                lines.extend(["", f"<b>{headings.get(group, 'Changes')}</b>"])
                for item in group_items:
                    lines.append(f"• {escape_html(user_facing_task_title(item['label']).strip())}")
            overflow = len(normalized_items) - len(shown)
            if overflow > 0:
                lines.extend(["", f"<i>+{overflow} more change(s)</i>"])
            return "\n".join(lines)

    parts = []
    if applied.get("tasks_created"): parts.append(f"{applied['tasks_created']} task(s) created")
    if applied.get("tasks_updated"): parts.append(f"{applied['tasks_updated']} task(s) updated")
    if applied.get("reminders_created"): parts.append(f"{applied['reminders_created']} reminder(s) created")
    if applied.get("reminders_updated"): parts.append(f"{applied['reminders_updated']} reminder(s) updated")
    if applied.get("goals_created"): parts.append(f"{applied['goals_created']} goal(s) created")
    if applied.get("problems_created"): parts.append(f"{applied['problems_created']} problem(s) created")
    if applied.get("links_created"): parts.append(f"{applied['links_created']} link(s) created")
    
    if not parts:
        return "<i>Logged. No changes made.</i>"

    return "<b>" + escape_html(", ".join(parts)) + ".</b>"


def _action_batch_record_snapshot(record: Dict[str, Any]) -> Dict[str, Any]:
    after_json = record.get("after_json") if isinstance(record.get("after_json"), dict) else {}
    if after_json:
        return after_json
    before_json = record.get("before_json") if isinstance(record.get("before_json"), dict) else {}
    return before_json


def _action_batch_record_group(record: Dict[str, Any]) -> str:
    operation = str(record.get("operation") or "").strip().lower()
    if operation == "create":
        return "Created"
    if operation == "complete":
        return "Completed"
    if operation == "archive":
        return "Archived"
    if operation == "restore":
        return "Restored"
    return "Updated"


def _action_batch_record_label(record: Dict[str, Any]) -> str:
    snapshot = _action_batch_record_snapshot(record)
    title = str(snapshot.get("title") or "").strip()
    if not title:
        title = str(record.get("work_item_id") or record.get("reminder_id") or "Untitled").strip()
    kind = str(snapshot.get("kind") or "").strip().lower()
    if kind == "project":
        prefix = "Project"
    elif kind == "subtask":
        prefix = "Subtask"
    elif record.get("reminder_id"):
        prefix = "Reminder"
    else:
        prefix = "Task"
    return f"{prefix}: {user_facing_task_title(title)}"


def format_action_batch_details(
    records: List[Dict[str, Any]],
    *,
    heading: str,
    subtasks_only: bool = False,
) -> str:
    normalized_records = [record for record in records if isinstance(record, dict)]
    if subtasks_only:
        normalized_records = [
            record
            for record in normalized_records
            if str(_action_batch_record_snapshot(record).get("kind") or "").strip().lower() == "subtask"
        ]

    lines = [f"<b>{escape_html(heading)}</b>"]
    if not normalized_records:
        lines.extend(["", "Nothing to show."])
        return "\n".join(lines)

    if subtasks_only:
        lines.append("")
        for record in normalized_records[:40]:
            label = _action_batch_record_label(record)
            if label.startswith("Subtask: "):
                label = label[len("Subtask: "):]
            lines.append(f"• {escape_html(label)}")
        return "\n".join(lines)

    grouped_order = ["Created", "Updated", "Completed", "Archived", "Restored"]
    grouped: Dict[str, List[str]] = {name: [] for name in grouped_order}
    extras: Dict[str, List[str]] = {}
    for record in normalized_records[:40]:
        group = _action_batch_record_group(record)
        label = _action_batch_record_label(record)
        if group in grouped:
            grouped[group].append(label)
        else:
            extras.setdefault(group, []).append(label)

    for group in grouped_order:
        labels = grouped[group]
        if not labels:
            continue
        lines.extend(["", f"<b>{escape_html(group)}</b>"])
        for label in labels:
            lines.append(f"• {escape_html(label)}")
    for group, labels in extras.items():
        lines.extend(["", f"<b>{escape_html(group)}</b>"])
        for label in labels:
            lines.append(f"• {escape_html(label)}")
    return "\n".join(lines)


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
