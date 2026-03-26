#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
os.chdir(BACKEND_ROOT)
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from common.config import settings  # noqa: E402
from common.models import (  # noqa: E402
    Area,
    Person,
    Reminder,
    ReminderStatus,
    WorkItem,
    WorkItemKind,
    WorkItemStatus,
)


def _fmt_dt(value: Any) -> str:
    if not isinstance(value, datetime):
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _status_checkbox(status: Any) -> str:
    value = str(getattr(status, "value", status) or "").strip().lower()
    if value in {"done", "completed", "dismissed", "canceled"}:
        return "[x]"
    if value in {"blocked"}:
        return "[-]"
    if value in {"archived"}:
        return "[~]"
    return "[ ]"


def _kind_value(kind: Any) -> str:
    return str(getattr(kind, "value", kind) or "").strip().lower()


def _priority_text(priority: Any) -> str | None:
    if isinstance(priority, int):
        return f"P{priority}"
    return None


def _work_item_sort_key(item: WorkItem) -> tuple[int, str, str]:
    kind_rank = {"project": 0, "task": 1, "subtask": 2}
    kind = _kind_value(getattr(item, "kind", None))
    return (kind_rank.get(kind, 9), (item.title or "").lower(), item.id)


def _work_item_line(item: WorkItem, *, depth: int) -> list[str]:
    kind = _kind_value(item.kind)
    checkbox = _status_checkbox(item.status)
    extras: list[str] = [kind]
    priority = _priority_text(getattr(item, "priority", None))
    if priority:
        extras.append(priority)
    if isinstance(getattr(item, "due_at", None), datetime):
        extras.append(f"due {_fmt_dt(item.due_at)}")
    if isinstance(getattr(item, "scheduled_for", None), datetime):
        extras.append(f"scheduled {_fmt_dt(item.scheduled_for)}")
    if isinstance(getattr(item, "snooze_until", None), datetime):
        extras.append(f"snoozed until {_fmt_dt(item.snooze_until)}")
    if getattr(item, "estimated_minutes", None):
        extras.append(f"{item.estimated_minutes}m")
    suffix = f" ({', '.join(extras)})" if extras else ""
    indent = "  " * depth
    lines = [f"{indent}- {checkbox} {item.title}{suffix}"]
    if isinstance(getattr(item, "notes", None), str) and item.notes.strip():
        lines.append(f"{indent}  - note: {item.notes.strip()}")
    return lines


def _render_work_item_tree(item: WorkItem, children_by_parent: dict[str, list[WorkItem]], *, depth: int = 0) -> list[str]:
    lines = _work_item_line(item, depth=depth)
    for child in sorted(children_by_parent.get(item.id, []), key=_work_item_sort_key):
        lines.extend(_render_work_item_tree(child, children_by_parent, depth=depth + 1))
    return lines


def _render_reminder(reminder: Reminder, work_item_titles: dict[str, str]) -> str:
    checkbox = _status_checkbox(reminder.status)
    extras: list[str] = []
    kind = _kind_value(reminder.kind)
    if kind:
        extras.append(kind)
    if isinstance(getattr(reminder, "remind_at", None), datetime):
        extras.append(f"at {_fmt_dt(reminder.remind_at)}")
    if isinstance(getattr(reminder, "recurrence_rule", None), str) and reminder.recurrence_rule.strip():
        extras.append(f"repeat {reminder.recurrence_rule.strip()}")
    linked_title = work_item_titles.get(reminder.work_item_id or "")
    if linked_title:
        extras.append(f"for {linked_title}")
    suffix = f" ({', '.join(extras)})" if extras else ""
    line = f"- {checkbox} {reminder.title}{suffix}"
    if isinstance(getattr(reminder, "message", None), str) and reminder.message.strip():
        line += f"\n  - message: {reminder.message.strip()}"
    return line


def _section(title: str, lines: list[str]) -> str:
    if not lines:
        return f"## {title}\n\nNone.\n"
    return f"## {title}\n\n" + "\n".join(lines) + "\n"


async def _render_markdown(user_id: str | None, include_archived: bool) -> str:
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as db:
            work_item_stmt = select(WorkItem).order_by(WorkItem.created_at.asc(), WorkItem.id.asc())
            reminder_stmt = select(Reminder).order_by(Reminder.remind_at.asc(), Reminder.created_at.asc(), Reminder.id.asc())
            area_stmt = select(Area).order_by(Area.name.asc(), Area.id.asc())
            person_stmt = select(Person).order_by(Person.name.asc(), Person.id.asc())
            if user_id:
                work_item_stmt = work_item_stmt.where(WorkItem.user_id == user_id)
                reminder_stmt = reminder_stmt.where(Reminder.user_id == user_id)
                area_stmt = area_stmt.where(Area.user_id == user_id)
                person_stmt = person_stmt.where(Person.user_id == user_id)

            work_items = (await db.execute(work_item_stmt)).scalars().all()
            reminders = (await db.execute(reminder_stmt)).scalars().all()
            areas = (await db.execute(area_stmt)).scalars().all()
            people = (await db.execute(person_stmt)).scalars().all()
    finally:
        await engine.dispose()

    if not include_archived:
        work_items = [
            item
            for item in work_items
            if getattr(item, "status", None) != WorkItemStatus.archived and getattr(item, "archived_at", None) is None
        ]
        reminders = [
            reminder
            for reminder in reminders
            if getattr(reminder, "status", None) not in {ReminderStatus.canceled}
        ]
        areas = [area for area in areas if getattr(area, "archived_at", None) is None]
        people = [person for person in people if getattr(person, "archived_at", None) is None]

    work_items_by_id = {item.id: item for item in work_items}
    children_by_parent: dict[str, list[WorkItem]] = {}
    root_items: list[WorkItem] = []
    for item in work_items:
        parent_id = getattr(item, "parent_id", None)
        if isinstance(parent_id, str) and parent_id in work_items_by_id:
            children_by_parent.setdefault(parent_id, []).append(item)
        else:
            root_items.append(item)

    work_item_lines: list[str] = []
    for item in sorted(root_items, key=_work_item_sort_key):
        work_item_lines.extend(_render_work_item_tree(item, children_by_parent, depth=0))

    work_item_titles = {item.id: item.title for item in work_items}
    reminder_lines = [_render_reminder(reminder, work_item_titles) for reminder in reminders]
    area_lines = [f"- {area.name}" for area in areas]
    person_lines = [f"- {person.name}" for person in people]

    now = datetime.now(timezone.utc).isoformat()
    user_scope = user_id or "all users"
    parts = [
        "# Local-First Data Export",
        "",
        f"- Generated at: `{now}`",
        f"- Scope: `{user_scope}`",
        f"- Included archived/canceled items: `{'yes' if include_archived else 'no'}`",
        "- Purpose: preserve current local-first data for manual re-entry into a fresh database.",
        "",
        _section("Work Items", work_item_lines),
        _section("Reminders", reminder_lines),
        _section("Areas", area_lines),
        _section("People", person_lines),
    ]
    return "\n".join(parts).rstrip() + "\n"


def _default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    export_dir = REPO_ROOT / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir / f"local-first-export-{stamp}.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export local-first work items/reminders to markdown.")
    parser.add_argument("--user-id", help="Optional user id scope for the export.")
    parser.add_argument("--output", help="Output markdown file path.")
    parser.add_argument("--include-archived", action="store_true", help="Include archived/canceled rows.")
    args = parser.parse_args()

    output_path = Path(args.output).expanduser().resolve() if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = asyncio.run(_render_markdown(args.user_id, args.include_archived))
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote local-first markdown export to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
