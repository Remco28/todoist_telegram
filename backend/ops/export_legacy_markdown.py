#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
os.chdir(BACKEND_ROOT)
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from common.config import settings  # noqa: E402
from common.legacy_models import EntityLink, Goal, Problem, Task  # noqa: E402


def _fmt_dt(value) -> str:
    if not isinstance(value, datetime):
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _fmt_date(value) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _section(title: str, lines: list[str]) -> str:
    if not lines:
        return f"## {title}\n\nNone.\n"
    return f"## {title}\n\n" + "\n".join(lines) + "\n"


async def _render_markdown(user_id: str | None) -> str:
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as db:
            task_stmt = select(Task).order_by(Task.created_at.asc(), Task.id.asc())
            goal_stmt = select(Goal).order_by(Goal.created_at.asc(), Goal.id.asc())
            problem_stmt = select(Problem).order_by(Problem.created_at.asc(), Problem.id.asc())
            link_stmt = select(EntityLink).order_by(EntityLink.created_at.asc(), EntityLink.id.asc())
            if user_id:
                task_stmt = task_stmt.where(Task.user_id == user_id)
                goal_stmt = goal_stmt.where(Goal.user_id == user_id)
                problem_stmt = problem_stmt.where(Problem.user_id == user_id)
                link_stmt = link_stmt.where(EntityLink.user_id == user_id)

            tasks = (await db.execute(task_stmt)).scalars().all()
            goals = (await db.execute(goal_stmt)).scalars().all()
            problems = (await db.execute(problem_stmt)).scalars().all()
            links = (await db.execute(link_stmt)).scalars().all()
    finally:
        await engine.dispose()

    now = datetime.now(timezone.utc).isoformat()
    user_scope = user_id or "all users"
    parts = [
        "# Legacy Data Export",
        "",
        f"- Generated at: `{now}`",
        f"- Scope: `{user_scope}`",
        "- Purpose: preserve legacy rows for manual re-entry into the local-first app.",
        "",
    ]

    task_lines = []
    for task in tasks:
        task_lines.extend(
            [
                f"### `{task.id}` {task.title}",
                f"- User: `{task.user_id}`",
                f"- Status: `{getattr(task.status, 'value', task.status)}`",
                f"- Priority: `{task.priority}`",
                f"- Due date: `{_fmt_date(task.due_date)}`",
                f"- Notes: {task.notes or '-'}",
                f"- Source inbox item: `{task.source_inbox_item_id or '-'}`",
                f"- Created: `{_fmt_dt(task.created_at)}`",
                f"- Updated: `{_fmt_dt(task.updated_at)}`",
                "",
            ]
        )

    goal_lines = []
    for goal in goals:
        goal_lines.extend(
            [
                f"### `{goal.id}` {goal.title}",
                f"- User: `{goal.user_id}`",
                f"- Status: `{getattr(goal.status, 'value', goal.status)}`",
                f"- Horizon: `{goal.horizon or '-'}`",
                f"- Target date: `{_fmt_date(goal.target_date)}`",
                f"- Description: {goal.description or '-'}",
                f"- Created: `{_fmt_dt(goal.created_at)}`",
                f"- Updated: `{_fmt_dt(goal.updated_at)}`",
                "",
            ]
        )

    problem_lines = []
    for problem in problems:
        problem_lines.extend(
            [
                f"### `{problem.id}` {problem.title}",
                f"- User: `{problem.user_id}`",
                f"- Status: `{getattr(problem.status, 'value', problem.status)}`",
                f"- Severity: `{problem.severity}`",
                f"- Horizon: `{problem.horizon or '-'}`",
                f"- Description: {problem.description or '-'}",
                f"- Created: `{_fmt_dt(problem.created_at)}`",
                f"- Updated: `{_fmt_dt(problem.updated_at)}`",
                "",
            ]
        )

    link_lines = []
    for link in links:
        link_lines.append(
            f"- `{link.id}` `{link.user_id}`: "
            f"`{getattr(link.from_entity_type, 'value', link.from_entity_type)}` `{link.from_entity_id}` "
            f"`{getattr(link.link_type, 'value', link.link_type)}` "
            f"`{getattr(link.to_entity_type, 'value', link.to_entity_type)}` `{link.to_entity_id}` "
            f"(created `{_fmt_dt(link.created_at)}`)"
        )

    parts.append(_section("Legacy Tasks", task_lines))
    parts.append(_section("Legacy Goals", goal_lines))
    parts.append(_section("Legacy Problems", problem_lines))
    parts.append(_section("Legacy Links", link_lines))
    return "\n".join(parts).rstrip() + "\n"


def _default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    export_dir = REPO_ROOT / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir / f"legacy-export-{stamp}.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export legacy tasks/goals/problems/links to markdown.")
    parser.add_argument("--user-id", help="Optional user id scope for the export.")
    parser.add_argument("--output", help="Output markdown file path.")
    args = parser.parse_args()

    output_path = Path(args.output).expanduser().resolve() if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = asyncio.run(_render_markdown(args.user_id))
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote legacy markdown export to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
