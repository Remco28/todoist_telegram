import copy
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from common.models import (
    ActionBatch,
    ActionBatchStatus,
    ConversationDirection,
    ConversationEvent,
    ConversationSource,
    EntityType,
    InboxItem,
    LinkType,
    Reminder,
    ReminderKind,
    ReminderStatus,
    ReminderVersion,
    VersionOperation,
    WorkItem,
    WorkItemKind,
    WorkItemStatus,
    WorkItemLink,
    WorkItemVersion,
)


def run_action_batch_view_payload(batch: ActionBatch) -> Dict[str, Any]:
    return {
        "id": batch.id,
        "user_id": batch.user_id,
        "conversation_event_id": batch.conversation_event_id,
        "source_message": batch.source_message,
        "status": getattr(batch.status, "value", batch.status),
        "proposal_json": batch.proposal_json,
        "applied_item_ids": list(batch.applied_item_ids_json or []),
        "before_summary": batch.before_summary,
        "after_summary": batch.after_summary,
        "undo_window_expires_at": batch.undo_window_expires_at,
        "reverted_at": batch.reverted_at,
        "created_at": batch.created_at,
    }


def run_work_item_version_view_payload(version: WorkItemVersion) -> Dict[str, Any]:
    return {
        "id": version.id,
        "user_id": version.user_id,
        "work_item_id": version.work_item_id,
        "action_batch_id": version.action_batch_id,
        "operation": getattr(version.operation, "value", version.operation),
        "before_json": version.before_json,
        "after_json": version.after_json,
        "created_at": version.created_at,
    }


def run_reminder_version_view_payload(version: ReminderVersion) -> Dict[str, Any]:
    return {
        "id": version.id,
        "user_id": version.user_id,
        "reminder_id": version.reminder_id,
        "action_batch_id": version.action_batch_id,
        "operation": getattr(version.operation, "value", version.operation),
        "before_json": version.before_json,
        "after_json": version.after_json,
        "created_at": version.created_at,
    }


def run_change_title_for_summary(record: Dict[str, Any]) -> str:
    after_json = record.get("after_json") if isinstance(record, dict) else {}
    before_json = record.get("before_json") if isinstance(record, dict) else {}
    for snapshot in (after_json, before_json):
        if isinstance(snapshot, dict):
            title = str(snapshot.get("title") or "").strip()
            if title:
                return title
    if isinstance(record, dict):
        return str(record.get("work_item_id") or record.get("reminder_id") or "work item").strip()
    return "work item"


def run_operation_summary_verb(operation: Any) -> str:
    value = str(getattr(operation, "value", operation) or "").strip().lower()
    if value == "create":
        return "Created"
    if value == "complete":
        return "Completed"
    if value == "archive":
        return "Archived"
    if value == "restore":
        return "Restored"
    return "Updated"


def run_action_batch_summary(records: List[Dict[str, Any]], fallback: str = "Applied changes") -> str:
    if not records:
        return fallback
    if len(records) == 1:
        record = records[0]
        return f"{run_operation_summary_verb(record.get('operation'))} {run_change_title_for_summary(record)}"
    return f"Applied {len(records)} work item changes"


def run_snapshot_datetime(value: Any, *, helpers: Dict[str, Any]) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    return helpers["_parse_due_at"](value)


def run_reminder_snapshot(reminder: Reminder) -> Dict[str, Any]:
    return {
        "id": getattr(reminder, "id", None),
        "work_item_id": getattr(reminder, "work_item_id", None),
        "person_id": getattr(reminder, "person_id", None),
        "kind": str(getattr(getattr(reminder, "kind", None), "value", getattr(reminder, "kind", None)) or ""),
        "status": str(getattr(getattr(reminder, "status", None), "value", getattr(reminder, "status", None)) or ""),
        "title": getattr(reminder, "title", None),
        "message": getattr(reminder, "message", None),
        "remind_at": getattr(reminder, "remind_at", None).isoformat()
        if isinstance(getattr(reminder, "remind_at", None), datetime)
        else None,
        "recurrence_rule": getattr(reminder, "recurrence_rule", None),
        "last_sent_at": getattr(reminder, "last_sent_at", None).isoformat()
        if isinstance(getattr(reminder, "last_sent_at", None), datetime)
        else None,
        "completed_at": getattr(reminder, "completed_at", None).isoformat()
        if isinstance(getattr(reminder, "completed_at", None), datetime)
        else None,
        "dismissed_at": getattr(reminder, "dismissed_at", None).isoformat()
        if isinstance(getattr(reminder, "dismissed_at", None), datetime)
        else None,
        "created_at": getattr(reminder, "created_at", None).isoformat()
        if isinstance(getattr(reminder, "created_at", None), datetime)
        else None,
        "updated_at": getattr(reminder, "updated_at", None).isoformat()
        if isinstance(getattr(reminder, "updated_at", None), datetime)
        else None,
    }


def run_restore_work_item_from_snapshot(item: WorkItem, snapshot: Dict[str, Any], *, helpers: Dict[str, Any]) -> None:
    if not isinstance(snapshot, dict):
        return
    kind_value = snapshot.get("kind")
    if kind_value:
        item.kind = WorkItemKind(kind_value)
    item.parent_id = snapshot.get("parent_id")
    item.area_id = snapshot.get("area_id")
    title = str(snapshot.get("title") or "").strip()
    if title:
        item.title = title
        item.title_norm = str(snapshot.get("title_norm") or title.lower().strip())
    item.notes = snapshot.get("notes")
    item.attributes_json = (
        copy.deepcopy(snapshot.get("attributes_json")) if isinstance(snapshot.get("attributes_json"), dict) else {}
    )
    item.status = helpers["_coerce_work_item_status"](snapshot.get("status"))
    item.priority = snapshot.get("priority")
    item.due_at = run_snapshot_datetime(snapshot.get("due_at"), helpers=helpers)
    item.scheduled_for = run_snapshot_datetime(snapshot.get("scheduled_for"), helpers=helpers)
    item.snooze_until = run_snapshot_datetime(snapshot.get("snooze_until"), helpers=helpers)
    item.estimated_minutes = snapshot.get("estimated_minutes")
    item.source_inbox_item_id = snapshot.get("source_inbox_item_id")
    item.completed_at = run_snapshot_datetime(snapshot.get("completed_at"), helpers=helpers)
    item.archived_at = run_snapshot_datetime(snapshot.get("archived_at"), helpers=helpers)
    item.updated_at = helpers["utc_now"]()


def run_restore_reminder_from_snapshot(reminder: Reminder, snapshot: Dict[str, Any], *, helpers: Dict[str, Any]) -> None:
    if not isinstance(snapshot, dict):
        return
    reminder.work_item_id = snapshot.get("work_item_id")
    reminder.person_id = snapshot.get("person_id")
    reminder.kind = helpers["_coerce_reminder_kind"](snapshot.get("kind"))
    reminder.status = helpers["_coerce_reminder_status"](snapshot.get("status"))
    reminder.title = str(snapshot.get("title") or "").strip() or reminder.title
    reminder.message = snapshot.get("message")
    remind_at = run_snapshot_datetime(snapshot.get("remind_at"), helpers=helpers)
    if remind_at is not None:
        reminder.remind_at = remind_at
    reminder.recurrence_rule = snapshot.get("recurrence_rule")
    reminder.last_sent_at = run_snapshot_datetime(snapshot.get("last_sent_at"), helpers=helpers)
    reminder.completed_at = run_snapshot_datetime(snapshot.get("completed_at"), helpers=helpers)
    reminder.dismissed_at = run_snapshot_datetime(snapshot.get("dismissed_at"), helpers=helpers)
    reminder.updated_at = helpers["utc_now"]()


def run_operation_for_work_item_change(before_snapshot: Dict[str, Any], item: WorkItem) -> VersionOperation:
    before_status = str(before_snapshot.get("status") or "").strip().lower()
    current_status = str(getattr(getattr(item, "status", None), "value", getattr(item, "status", None)) or "").strip().lower()
    if current_status == "done" and before_status != "done":
        return VersionOperation.complete
    if current_status == "archived" and before_status != "archived":
        return VersionOperation.archive
    return VersionOperation.update


async def run_record_work_item_action_batch(
    db,
    *,
    user_id: str,
    source_message: str,
    proposal_json: Optional[Dict[str, Any]],
    version_records: List[Dict[str, Any]],
    helpers: Dict[str, Any],
    conversation_event_id: Optional[str] = None,
    status: ActionBatchStatus = ActionBatchStatus.applied,
    after_summary: Optional[str] = None,
) -> ActionBatch:
    action_batch = ActionBatch(
        id=f"abt_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        conversation_event_id=conversation_event_id,
        source_message=source_message,
        status=status,
        proposal_json=proposal_json if isinstance(proposal_json, dict) else {},
        applied_item_ids_json=[record["work_item_id"] for record in version_records],
        before_summary=None,
        after_summary=after_summary or run_action_batch_summary(version_records),
        undo_window_expires_at=helpers["utc_now"]() + timedelta(hours=24)
        if status == ActionBatchStatus.applied
        else None,
        created_at=helpers["utc_now"](),
    )
    db.add(action_batch)
    for record in version_records:
        db.add(
            WorkItemVersion(
                id=f"wiv_{uuid.uuid4().hex[:12]}",
                user_id=user_id,
                work_item_id=record["work_item_id"],
                action_batch_id=action_batch.id,
                operation=record["operation"],
                before_json=record.get("before_json") if isinstance(record.get("before_json"), dict) else {},
                after_json=record.get("after_json") if isinstance(record.get("after_json"), dict) else {},
                created_at=helpers["utc_now"](),
            )
        )
    return action_batch


async def run_record_reminder_action_batch(
    db,
    *,
    user_id: str,
    source_message: str,
    proposal_json: Optional[Dict[str, Any]],
    version_records: List[Dict[str, Any]],
    helpers: Dict[str, Any],
    conversation_event_id: Optional[str] = None,
    status: ActionBatchStatus = ActionBatchStatus.applied,
    after_summary: Optional[str] = None,
) -> ActionBatch:
    action_batch = ActionBatch(
        id=f"abt_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        conversation_event_id=conversation_event_id,
        source_message=source_message,
        status=status,
        proposal_json=proposal_json if isinstance(proposal_json, dict) else {},
        applied_item_ids_json=[record["reminder_id"] for record in version_records],
        before_summary=None,
        after_summary=after_summary
        or run_action_batch_summary(
            [
                {
                    "operation": record.get("operation"),
                    "before_json": record.get("before_json"),
                    "after_json": record.get("after_json"),
                    "reminder_id": record.get("reminder_id"),
                }
                for record in version_records
            ],
            fallback="Applied reminder changes",
        ),
        undo_window_expires_at=helpers["utc_now"]() + timedelta(hours=24)
        if status == ActionBatchStatus.applied
        else None,
        created_at=helpers["utc_now"](),
    )
    db.add(action_batch)
    for record in version_records:
        db.add(
            ReminderVersion(
                id=f"rmv_{uuid.uuid4().hex[:12]}",
                user_id=user_id,
                reminder_id=record["reminder_id"],
                action_batch_id=action_batch.id,
                operation=record["operation"],
                before_json=record.get("before_json") if isinstance(record.get("before_json"), dict) else {},
                after_json=record.get("after_json") if isinstance(record.get("after_json"), dict) else {},
                created_at=helpers["utc_now"](),
            )
        )
    return action_batch


def run_infer_urgency_score(due: Optional[date], priority: Optional[int], *, helpers: Dict[str, Any]) -> Optional[int]:
    inferred: Optional[int] = None
    today = helpers["_local_today"]()
    if due is not None:
        days = (due - today).days
        if days <= 0:
            inferred = 5
        elif days <= 2:
            inferred = 4
        elif days <= 7:
            inferred = 3
        else:
            inferred = 2
    if priority is not None and 1 <= priority <= 4:
        priority_hint = {1: 4, 2: 3, 3: 2, 4: 1}[priority]
        inferred = max(inferred or 1, priority_hint)
    return inferred


def run_resolved_work_item_kind(task_data: Dict[str, Any], *, existing: Optional[WorkItem] = None) -> WorkItemKind:
    raw = str(task_data.get("kind") or "").strip().lower()
    if raw == "project":
        return WorkItemKind.project
    if raw == "subtask":
        return WorkItemKind.subtask
    if raw == "task":
        return WorkItemKind.task
    if existing is not None and getattr(existing, "kind", None) is not None:
        return existing.kind
    return WorkItemKind.task


def run_work_item_label(title: str, kind: WorkItemKind) -> str:
    cleaned = str(title or "").strip()
    if not cleaned:
        return cleaned
    if kind == WorkItemKind.project:
        return f"Project: {cleaned}"
    if kind == WorkItemKind.subtask:
        return f"Subtask: {cleaned}"
    return cleaned


async def run_resolve_parent_work_item_id(
    db,
    *,
    user_id: str,
    parent_task_id: Optional[str],
    parent_title: Optional[str],
    entity_map: Dict[Any, str],
    helpers: Dict[str, Any],
) -> Optional[str]:
    if isinstance(parent_task_id, str) and parent_task_id.strip():
        stmt = select(WorkItem).where(
            WorkItem.user_id == user_id,
            WorkItem.id == parent_task_id.strip(),
            WorkItem.status != WorkItemStatus.archived,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        return existing.id if existing is not None else None
    if isinstance(parent_title, str) and parent_title.strip():
        parent_norm = helpers["_canonical_task_title"](parent_title).lower().strip()
        mapped = entity_map.get((EntityType.task, parent_norm))
        if isinstance(mapped, str) and mapped.strip():
            return mapped.strip()
        stmt = select(WorkItem).where(
            WorkItem.user_id == user_id,
            WorkItem.title_norm == parent_norm,
            WorkItem.status != WorkItemStatus.archived,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        return existing.id if existing is not None else None
    return None


async def run_apply_capture(
    db,
    user_id: str,
    chat_id: str,
    source: str,
    message: str,
    extraction: dict,
    request_id: str,
    *,
    helpers: Dict[str, Any],
    client_msg_id: Optional[str] = None,
    session_id: Optional[str] = None,
    commit: bool = True,
    enqueue_summary: bool = True,
) -> tuple:
    applied = helpers["AppliedChanges"]()
    inbox_item_id = f"inb_{uuid.uuid4().hex[:12]}"
    touched_task_ids: List[str] = []
    touched_reminder_ids: List[str] = []
    version_records: List[Dict[str, Any]] = []
    reminder_version_records: List[Dict[str, Any]] = []
    session = None
    if session_id is None and "_get_or_create_session" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
        session_id = session.id
    db.add(
        InboxItem(
            id=inbox_item_id,
            user_id=user_id,
            chat_id=chat_id,
            session_id=session_id,
            source=source,
            client_msg_id=client_msg_id,
            message_raw=message,
            message_norm=message.strip(),
            received_at=helpers["utc_now"](),
        )
    )
    conversation_source = ConversationSource.telegram
    if source not in {helpers["settings"].TELEGRAM_DEFAULT_SOURCE, "telegram"}:
        conversation_source = ConversationSource.system if source == "system" else ConversationSource.web
    conversation_event = ConversationEvent(
        id=f"cev_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        chat_id=chat_id,
        source=conversation_source,
        direction=ConversationDirection.inbound,
        content_text=message,
        normalized_text=message.strip(),
        metadata_json={"request_id": request_id, "source": source, "client_msg_id": client_msg_id},
        created_at=helpers["utc_now"](),
    )
    db.add(conversation_event)

    entity_map = {}
    for t_data in extraction.get("tasks", []):
        canonical_title = helpers["_canonical_task_title"](t_data.get("title"))
        title_norm = canonical_title.lower().strip()
        action = str(t_data.get("action") or "").strip().lower()
        status_hint = str(t_data.get("status") or "").strip().lower()
        requires_target = action in {"update", "complete", "archive"} or status_hint in {"done", "archived"}
        existing = None
        target_task_id = t_data.get("target_task_id")
        if isinstance(target_task_id, str) and target_task_id.strip():
            target_stmt = select(WorkItem).where(
                WorkItem.user_id == user_id,
                WorkItem.id == target_task_id.strip(),
                WorkItem.status != WorkItemStatus.archived,
            )
            existing = (await db.execute(target_stmt)).scalar_one_or_none()
        resolved_kind = run_resolved_work_item_kind(t_data, existing=existing)
        if existing is None and not requires_target and action != "create":
            kind_filter = [WorkItemKind.task, WorkItemKind.subtask]
            if resolved_kind == WorkItemKind.project:
                kind_filter = [WorkItemKind.project]
            stmt = select(WorkItem).where(
                WorkItem.user_id == user_id,
                WorkItem.title_norm == title_norm,
                WorkItem.kind.in_(kind_filter),
                WorkItem.status != WorkItemStatus.archived,
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            resolved_kind = run_resolved_work_item_kind(t_data, existing=existing)

        parent_task_id = t_data.get("parent_task_id")
        parent_title = t_data.get("parent_title")
        has_parent_directive = (
            isinstance(parent_task_id, str)
            and parent_task_id.strip()
        ) or (
            isinstance(parent_title, str)
            and parent_title.strip()
        )
        resolved_parent_id: Optional[str] = None
        if resolved_kind == WorkItemKind.project:
            resolved_parent_id = None
        elif has_parent_directive:
            resolved_parent_id = await run_resolve_parent_work_item_id(
                db,
                user_id=user_id,
                parent_task_id=parent_task_id if isinstance(parent_task_id, str) else None,
                parent_title=parent_title if isinstance(parent_title, str) else None,
                entity_map=entity_map,
                helpers=helpers,
            )
            if resolved_parent_id is None:
                db.add(
                    helpers["EventLog"](
                        id=str(uuid.uuid4()),
                        request_id=request_id,
                        user_id=user_id,
                        event_type="task_action_skipped_missing_parent",
                        payload_json={
                            "title": t_data.get("title"),
                            "action": action,
                            "parent_task_id": parent_task_id,
                            "parent_title": parent_title,
                        },
                        created_at=helpers["utc_now"](),
                    )
                )
                continue
        elif resolved_kind == WorkItemKind.subtask and existing is None:
            db.add(
                helpers["EventLog"](
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    event_type="task_action_skipped_missing_parent",
                    payload_json={"title": t_data.get("title"), "action": action},
                    created_at=helpers["utc_now"](),
                )
            )
            continue
        if existing:
            before_snapshot = helpers["work_item_snapshot"](existing)
            existing_canonical_title = helpers["_canonical_task_title"](existing.title)
            if existing_canonical_title and existing.title != existing_canonical_title:
                existing.title = existing_canonical_title
                existing.title_norm = existing_canonical_title.lower().strip()
            if action not in {"complete", "archive"}:
                existing.title = canonical_title
                existing.title_norm = title_norm
            if t_data.get("kind") is not None:
                existing.kind = resolved_kind
            if resolved_kind == WorkItemKind.project:
                existing.parent_id = None
            elif has_parent_directive:
                existing.parent_id = resolved_parent_id
            if "priority" in t_data:
                existing.priority = t_data.get("priority")
            if "notes" in t_data and isinstance(t_data.get("notes"), str):
                existing.notes = t_data.get("notes")
            if "due_date" in t_data:
                due_raw = t_data.get("due_date")
                if isinstance(due_raw, str) and due_raw.strip():
                    existing.due_at = helpers["_parse_due_at"](due_raw)
                elif due_raw is None:
                    existing.due_at = None
            if action == "archive":
                existing.status = WorkItemStatus.archived
                existing.archived_at = helpers["utc_now"]()
            elif action == "complete":
                existing.status = WorkItemStatus.done
                existing.completed_at = helpers["utc_now"]()
            elif "status" in t_data and t_data.get("status"):
                existing.status = helpers["_coerce_work_item_status"](t_data.get("status"))
                if existing.status == WorkItemStatus.done:
                    existing.completed_at = helpers["utc_now"]()
                else:
                    existing.completed_at = None
            existing.source_inbox_item_id = inbox_item_id
            existing.updated_at = helpers["utc_now"]()
            after_snapshot = helpers["work_item_snapshot"](existing)
            target_entity_id = existing.id

            entity_map[(EntityType.task, title_norm)] = target_entity_id
            touched_task_ids.append(target_entity_id)
            applied.tasks_updated += 1
            label = run_work_item_label(existing.title, existing.kind)
            if action == "archive" or status_hint == "archived":
                helpers["_append_applied_item"](applied, "archived", label)
                operation = VersionOperation.archive
            elif action == "complete" or status_hint == "done":
                helpers["_append_applied_item"](applied, "completed", label)
                operation = VersionOperation.complete
            else:
                helpers["_append_applied_item"](applied, "updated", label)
                if before_snapshot.get("parent_id") != after_snapshot.get("parent_id"):
                    operation = VersionOperation.reparent
                else:
                    operation = VersionOperation.update
            version_records.append(
                {
                    "work_item_id": target_entity_id,
                    "operation": operation,
                    "before_json": before_snapshot,
                    "after_json": after_snapshot,
                }
            )
        else:
            if requires_target or action in {"noop"}:
                db.add(
                    helpers["EventLog"](
                        id=str(uuid.uuid4()),
                        request_id=request_id,
                        user_id=user_id,
                        event_type="task_action_skipped_missing_target",
                        payload_json={"title": t_data.get("title"), "action": action},
                        created_at=helpers["utc_now"](),
                    )
                )
                continue
            task_id = helpers["_new_work_item_id"](resolved_kind)
            created_item = WorkItem(
                id=task_id,
                user_id=user_id,
                kind=resolved_kind,
                parent_id=resolved_parent_id,
                area_id=None,
                title=canonical_title,
                title_norm=title_norm,
                notes=t_data.get("notes") if isinstance(t_data.get("notes"), str) else None,
                status=helpers["_coerce_work_item_status"](t_data.get("status")),
                priority=t_data.get("priority"),
                due_at=helpers["_parse_due_at"](t_data.get("due_date")),
                scheduled_for=None,
                snooze_until=None,
                estimated_minutes=None,
                source_inbox_item_id=inbox_item_id,
                created_at=helpers["utc_now"](),
                updated_at=helpers["utc_now"](),
                completed_at=helpers["utc_now"]()
                if str(t_data.get("status") or "").strip().lower() == "done"
                else None,
                archived_at=helpers["utc_now"]()
                if str(t_data.get("status") or "").strip().lower() == "archived"
                else None,
            )
            db.add(created_item)
            entity_map[(EntityType.task, title_norm)] = task_id
            touched_task_ids.append(task_id)
            applied.tasks_created += 1
            helpers["_append_applied_item"](applied, "created", run_work_item_label(canonical_title, resolved_kind))
            version_records.append(
                {
                    "work_item_id": task_id,
                    "operation": VersionOperation.create,
                    "before_json": {},
                    "after_json": helpers["work_item_snapshot"](created_item),
                }
            )

    for l_data in extraction.get("links", []):
        try:
            from_type = EntityType(l_data["from_type"])
            to_type = EntityType(l_data["to_type"])
            link_type = LinkType(l_data["link_type"])
            from_id = entity_map.get((from_type, l_data["from_title"].lower().strip()))
            to_id = entity_map.get((to_type, l_data["to_title"].lower().strip()))
            work_item_link_type = helpers["_work_item_link_type_from_legacy"](link_type)
            if from_id and to_id and work_item_link_type is not None:
                db.add(
                    WorkItemLink(
                        id=f"lnk_{uuid.uuid4().hex[:12]}",
                        user_id=user_id,
                        from_work_item_id=from_id,
                        to_work_item_id=to_id,
                        link_type=work_item_link_type,
                        created_at=helpers["utc_now"](),
                    )
                )
                applied.links_created += 1
                helpers["_append_applied_item"](
                    applied,
                    "link_created",
                    f"{l_data['from_title'].strip()} {l_data['link_type'].strip()} {l_data['to_title'].strip()}",
                )
        except Exception as exc:
            db.add(
                helpers["EventLog"](
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    event_type="link_validation_failed",
                    payload_json={"entry": l_data, "error": str(exc)},
                )
            )

    for r_data in extraction.get("reminders", []):
        canonical_title = helpers["_canonical_task_title"](r_data.get("title"))
        action = str(r_data.get("action") or "").strip().lower()
        status_hint = str(r_data.get("status") or "").strip().lower()
        requires_target = action in {"update", "complete", "dismiss", "cancel"} or status_hint in {
            "completed",
            "dismissed",
            "canceled",
        }
        existing_reminder = None
        target_reminder_id = r_data.get("target_reminder_id")
        if isinstance(target_reminder_id, str) and target_reminder_id.strip():
            reminder_stmt = select(Reminder).where(
                Reminder.user_id == user_id,
                Reminder.id == target_reminder_id.strip(),
            )
            existing_reminder = (await db.execute(reminder_stmt)).scalar_one_or_none()

        if existing_reminder:
            before_snapshot = helpers["_reminder_snapshot"](existing_reminder)
            if action not in {"complete", "dismiss", "cancel"} and canonical_title:
                existing_reminder.title = canonical_title
            message_value = r_data.get("message")
            if isinstance(message_value, str):
                existing_reminder.message = message_value.strip() or None
            remind_at_value = r_data.get("remind_at")
            if isinstance(remind_at_value, str) and remind_at_value.strip():
                parsed_remind_at = helpers["_parse_due_at"](remind_at_value)
                if parsed_remind_at is not None:
                    existing_reminder.remind_at = parsed_remind_at
            if "kind" in r_data and r_data.get("kind") is not None:
                existing_reminder.kind = helpers["_coerce_reminder_kind"](r_data.get("kind"))
            if "recurrence_rule" in r_data:
                existing_reminder.recurrence_rule = helpers["_validated_recurrence_rule"](r_data.get("recurrence_rule"))
            if existing_reminder.recurrence_rule and existing_reminder.kind == ReminderKind.one_off:
                existing_reminder.kind = ReminderKind.recurring
            if not existing_reminder.recurrence_rule and existing_reminder.kind == ReminderKind.recurring:
                existing_reminder.kind = ReminderKind.one_off
            work_item_id = r_data.get("work_item_id")
            if isinstance(work_item_id, str) and work_item_id.strip():
                existing_reminder.work_item_id = work_item_id.strip()
            person_id = r_data.get("person_id")
            if isinstance(person_id, str) and person_id.strip():
                existing_reminder.person_id = person_id.strip()
            if action == "complete":
                existing_reminder.status = ReminderStatus.completed
            elif action == "dismiss":
                existing_reminder.status = ReminderStatus.dismissed
            elif action == "cancel":
                existing_reminder.status = ReminderStatus.canceled
            elif "status" in r_data and r_data.get("status"):
                existing_reminder.status = helpers["_coerce_reminder_status"](r_data.get("status"))
            existing_reminder.last_sent_at = (
                helpers["utc_now"]() if existing_reminder.status == ReminderStatus.sent else existing_reminder.last_sent_at
            )
            existing_reminder.completed_at = helpers["utc_now"]() if existing_reminder.status == ReminderStatus.completed else None
            existing_reminder.dismissed_at = helpers["utc_now"]() if existing_reminder.status == ReminderStatus.dismissed else None
            existing_reminder.updated_at = helpers["utc_now"]()
            after_snapshot = helpers["_reminder_snapshot"](existing_reminder)
            applied.reminders_updated += 1
            if action == "complete" or status_hint == "completed":
                helpers["_append_applied_item"](applied, "reminder_completed", existing_reminder.title)
                reminder_operation = VersionOperation.complete
            elif action in {"dismiss", "cancel"} or status_hint in {"dismissed", "canceled"}:
                helpers["_append_applied_item"](applied, "reminder_canceled", existing_reminder.title)
                reminder_operation = VersionOperation.update
            else:
                helpers["_append_applied_item"](applied, "reminder_updated", existing_reminder.title)
                reminder_operation = VersionOperation.update
            reminder_version_records.append(
                {
                    "reminder_id": existing_reminder.id,
                    "operation": reminder_operation,
                    "before_json": before_snapshot,
                    "after_json": after_snapshot,
                }
            )
            touched_reminder_ids.append(existing_reminder.id)
            continue

        if requires_target or action in {"noop", "complete", "dismiss", "cancel"}:
            db.add(
                helpers["EventLog"](
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    event_type="reminder_action_skipped_missing_target",
                    payload_json={"title": r_data.get("title"), "action": action},
                    created_at=helpers["utc_now"](),
                )
            )
            continue

        remind_at = helpers["_parse_due_at"](r_data.get("remind_at"))
        if remind_at is None:
            db.add(
                helpers["EventLog"](
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    event_type="reminder_action_skipped_missing_schedule",
                    payload_json={"title": r_data.get("title"), "action": action},
                    created_at=helpers["utc_now"](),
                )
            )
            continue
        recurrence_rule = helpers["_validated_recurrence_rule"](r_data.get("recurrence_rule"))
        reminder_kind = helpers["_coerce_reminder_kind"](r_data.get("kind"))
        if recurrence_rule and reminder_kind == ReminderKind.one_off:
            reminder_kind = ReminderKind.recurring
        if reminder_kind == ReminderKind.recurring and not recurrence_rule:
            reminder_kind = ReminderKind.one_off
        reminder_status = helpers["_coerce_reminder_status"](r_data.get("status"))
        reminder = Reminder(
            id=f"rem_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            work_item_id=r_data.get("work_item_id")
            if isinstance(r_data.get("work_item_id"), str) and r_data.get("work_item_id").strip()
            else None,
            person_id=r_data.get("person_id")
            if isinstance(r_data.get("person_id"), str) and r_data.get("person_id").strip()
            else None,
            kind=reminder_kind,
            status=reminder_status,
            title=canonical_title,
            message=r_data.get("message")
            if isinstance(r_data.get("message"), str) and r_data.get("message").strip()
            else None,
            remind_at=remind_at,
            recurrence_rule=recurrence_rule,
            last_sent_at=helpers["utc_now"]() if reminder_status == ReminderStatus.sent else None,
            completed_at=helpers["utc_now"]() if reminder_status == ReminderStatus.completed else None,
            dismissed_at=helpers["utc_now"]() if reminder_status == ReminderStatus.dismissed else None,
            created_at=helpers["utc_now"](),
            updated_at=helpers["utc_now"](),
        )
        db.add(reminder)
        applied.reminders_created += 1
        helpers["_append_applied_item"](applied, "reminder_created", canonical_title)
        reminder_version_records.append(
            {
                "reminder_id": reminder.id,
                "operation": VersionOperation.create,
                "before_json": {},
                "after_json": helpers["_reminder_snapshot"](reminder),
            }
        )
        touched_reminder_ids.append(reminder.id)

    await helpers["_remember_recent_tasks"](
        db=db,
        user_id=user_id,
        chat_id=chat_id,
        task_ids=touched_task_ids,
        reason="capture_apply",
    )
    await helpers["_remember_recent_reminders"](
        db=db,
        user_id=user_id,
        chat_id=chat_id,
        reminder_ids=touched_reminder_ids,
        reason="capture_apply",
    )

    if version_records:
        await helpers["_record_work_item_action_batch"](
            db,
            user_id=user_id,
            conversation_event_id=conversation_event.id,
            source_message=message,
            proposal_json=extraction if isinstance(extraction, dict) else {},
            version_records=version_records,
        )
    if reminder_version_records:
        await helpers["_record_reminder_action_batch"](
            db,
            user_id=user_id,
            conversation_event_id=conversation_event.id,
            source_message=message,
            proposal_json=extraction if isinstance(extraction, dict) else {},
            version_records=reminder_version_records,
        )

    if session is None and session_id and "_get_latest_session" in helpers:
        session = await helpers["_get_latest_session"](db=db, user_id=user_id, chat_id=chat_id)
    if session is not None and "_update_session_state" in helpers:
        active_entity_refs: List[Dict[str, Any]] = []
        for record in version_records[:8]:
            after_json = record.get("after_json") if isinstance(record.get("after_json"), dict) else {}
            title = str(after_json.get("title") or "").strip()
            if not title:
                continue
            active_entity_refs.append(
                {
                    "entity_type": "work_item",
                    "entity_id": record["work_item_id"],
                    "title": title,
                    "status": str(after_json.get("status") or "").strip().lower() or None,
                    "source": "apply",
                }
            )
        for record in reminder_version_records[:8]:
            after_json = record.get("after_json") if isinstance(record.get("after_json"), dict) else {}
            title = str(after_json.get("title") or "").strip()
            if not title:
                continue
            item: Dict[str, Any] = {
                "entity_type": "reminder",
                "entity_id": record["reminder_id"],
                "title": title,
                "status": str(after_json.get("status") or "").strip().lower() or None,
                "source": "apply",
            }
            work_item_title = str(after_json.get("work_item_title") or "").strip()
            if work_item_title:
                item["work_item_title"] = work_item_title
            active_entity_refs.append(item)
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="action",
            active_entity_refs=active_entity_refs,
            pending_draft_id=None,
            pending_clarification=None,
            touch=False,
        )

    if commit:
        await db.commit()
        if chat_id and "_invalidate_today_plan_cache" in helpers:
            try:
                await helpers["_invalidate_today_plan_cache"](user_id, chat_id)
            except Exception as exc:
                helpers["logger"].warning(
                    "Failed to invalidate today plan cache after apply_capture for user %s chat %s: %s",
                    user_id,
                    chat_id,
                    exc,
                )
    if enqueue_summary:
        await helpers["_enqueue_summary_job"](user_id=user_id, chat_id=chat_id, inbox_item_id=inbox_item_id)
    return inbox_item_id, applied
