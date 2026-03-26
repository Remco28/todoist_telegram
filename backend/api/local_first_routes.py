import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import select

from api.schemas import ReminderCreate, ReminderSnoozeRequest, ReminderUpdate, WorkItemCreate, WorkItemUpdate
from common.models import (
    ActionBatch,
    ActionBatchStatus,
    Reminder,
    ReminderKind,
    ReminderStatus,
    ReminderVersion,
    VersionOperation,
    WorkItem,
    WorkItemKind,
    WorkItemStatus,
    WorkItemVersion,
)


async def _attach_reminder_work_item_titles(reminders: List[Reminder], user_id: str, db) -> None:
    work_item_ids = {
        reminder.work_item_id
        for reminder in reminders
        if isinstance(getattr(reminder, "work_item_id", None), str) and reminder.work_item_id.strip()
    }
    if not work_item_ids:
        return
    linked_items = (
        await db.execute(
            select(WorkItem).where(
                WorkItem.user_id == user_id,
                WorkItem.id.in_(work_item_ids),
            )
        )
    ).scalars().all()
    title_by_id = {
        item.id: item.title
        for item in linked_items
        if isinstance(item.id, str) and item.id.strip()
    }
    for reminder in reminders:
        reminder.work_item_title = title_by_id.get(getattr(reminder, "work_item_id", None))


def register_local_first_routes(
    app: FastAPI,
    *,
    get_authenticated_user,
    get_db,
    check_idempotency,
    helpers: Dict[str, Any],
) -> None:
    @app.get("/v1/work_items")
    async def list_work_items(
        kind: Optional[WorkItemKind] = None,
        status: Optional[WorkItemStatus] = None,
        parent_id: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 100,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        query = select(WorkItem).where(WorkItem.user_id == user_id).order_by(WorkItem.id).limit(min(limit, 200))
        if kind:
            query = query.where(WorkItem.kind == kind)
        if status:
            query = query.where(WorkItem.status == status)
        if parent_id:
            query = query.where(WorkItem.parent_id == parent_id)
        if cursor:
            query = query.where(WorkItem.id > cursor)
        items = (await db.execute(query)).scalars().all()
        return [helpers["_work_item_view_payload"](item) for item in items]

    @app.post("/v1/work_items", dependencies=[Depends(check_idempotency)])
    async def create_work_item(
        request: Request,
        payload: WorkItemCreate,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        if hasattr(request.state, "idempotent_response"):
            return request.state.idempotent_response
        canonical_title = helpers["_canonical_task_title"](payload.title)
        item = WorkItem(
            id=helpers["_new_work_item_id"](payload.kind),
            user_id=user_id,
            kind=payload.kind,
            parent_id=payload.parent_id,
            area_id=payload.area_id,
            title=canonical_title,
            title_norm=canonical_title.lower().strip(),
            notes=payload.notes,
            status=helpers["_coerce_work_item_status"](payload.status),
            priority=payload.priority,
            due_at=helpers["_parse_due_at"](payload.due_at),
            scheduled_for=helpers["_parse_due_at"](payload.scheduled_for),
            snooze_until=helpers["_parse_due_at"](payload.snooze_until),
            estimated_minutes=payload.estimated_minutes,
            created_at=helpers["utc_now"](),
            updated_at=helpers["utc_now"](),
            completed_at=helpers["utc_now"]() if payload.status == WorkItemStatus.done else None,
            archived_at=helpers["utc_now"]() if payload.status == WorkItemStatus.archived else None,
        )
        db.add(item)
        await helpers["_record_work_item_action_batch"](
            db,
            user_id=user_id,
            source_message=f"API create work item: {canonical_title}",
            proposal_json=payload.model_dump(mode="json"),
            version_records=[
                {
                    "work_item_id": item.id,
                    "operation": VersionOperation.create,
                    "before_json": {},
                    "after_json": helpers["work_item_snapshot"](item),
                }
            ],
        )
        await db.commit()
        resp = helpers["_work_item_view_payload"](item)
        await helpers["save_idempotency"](user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
        return resp

    @app.patch("/v1/work_items/{item_id}", dependencies=[Depends(check_idempotency)])
    async def update_work_item(
        request: Request,
        item_id: str,
        payload: WorkItemUpdate,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        if hasattr(request.state, "idempotent_response"):
            return request.state.idempotent_response
        update_data = payload.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        item = await helpers["_get_work_item_by_id"](db, user_id, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Work item not found")
        before_snapshot = helpers["work_item_snapshot"](item)
        helpers["_apply_work_item_updates"](item, update_data)
        after_snapshot = helpers["work_item_snapshot"](item)
        operation = VersionOperation.update
        if item.status == WorkItemStatus.done and before_snapshot.get("status") != "done":
            operation = VersionOperation.complete
        elif item.status == WorkItemStatus.archived and before_snapshot.get("status") != "archived":
            operation = VersionOperation.archive
        await helpers["_record_work_item_action_batch"](
            db,
            user_id=user_id,
            source_message=f"API update work item: {item.id}",
            proposal_json=payload.model_dump(mode="json", exclude_unset=True),
            version_records=[
                {
                    "work_item_id": item.id,
                    "operation": operation,
                    "before_json": before_snapshot,
                    "after_json": after_snapshot,
                }
            ],
        )
        await db.commit()
        resp = helpers["_work_item_view_payload"](item)
        await helpers["save_idempotency"](user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
        return resp

    @app.get("/v1/reminders")
    async def list_reminders(
        status: Optional[ReminderStatus] = None,
        kind: Optional[ReminderKind] = None,
        due_before: Optional[str] = None,
        limit: int = 100,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        query = select(Reminder).where(Reminder.user_id == user_id).order_by(Reminder.remind_at.asc()).limit(min(limit, 200))
        if status:
            query = query.where(Reminder.status == status)
        if kind:
            query = query.where(Reminder.kind == kind)
        due_before_dt = helpers["_parse_due_at"](due_before) if due_before else None
        if due_before_dt is not None:
            query = query.where(Reminder.remind_at <= due_before_dt)
        reminders = (await db.execute(query)).scalars().all()
        await _attach_reminder_work_item_titles(reminders, user_id, db)
        return [helpers["_reminder_view_payload"](reminder) for reminder in reminders]

    @app.post("/v1/reminders", dependencies=[Depends(check_idempotency)])
    async def create_reminder(
        request: Request,
        payload: ReminderCreate,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        if hasattr(request.state, "idempotent_response"):
            return request.state.idempotent_response
        remind_at = helpers["_parse_due_at"](payload.remind_at)
        if remind_at is None:
            raise HTTPException(status_code=400, detail="Invalid remind_at")
        recurrence_rule = helpers["_validated_recurrence_rule"](payload.recurrence_rule)
        reminder_kind = helpers["_coerce_reminder_kind"](payload.kind)
        if recurrence_rule and reminder_kind == ReminderKind.one_off:
            reminder_kind = ReminderKind.recurring
        if reminder_kind == ReminderKind.recurring and not recurrence_rule:
            raise HTTPException(status_code=400, detail="Recurring reminders require recurrence_rule")
        reminder = Reminder(
            id=f"rem_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            work_item_id=payload.work_item_id,
            person_id=payload.person_id,
            kind=reminder_kind,
            status=helpers["_coerce_reminder_status"](payload.status),
            title=payload.title.strip(),
            message=payload.message,
            remind_at=remind_at,
            recurrence_rule=recurrence_rule,
            created_at=helpers["utc_now"](),
            updated_at=helpers["utc_now"](),
            last_sent_at=None,
            completed_at=helpers["utc_now"]() if payload.status == ReminderStatus.completed else None,
            dismissed_at=helpers["utc_now"]() if payload.status == ReminderStatus.dismissed else None,
        )
        db.add(reminder)
        await helpers["_record_reminder_action_batch"](
            db,
            user_id=user_id,
            source_message=f"API create reminder: {reminder.title}",
            proposal_json=payload.model_dump(mode="json"),
            version_records=[
                {
                    "reminder_id": reminder.id,
                    "operation": VersionOperation.create,
                    "before_json": {},
                    "after_json": helpers["_reminder_snapshot"](reminder),
                }
            ],
        )
        await db.commit()
        await _attach_reminder_work_item_titles([reminder], user_id, db)
        resp = helpers["_reminder_view_payload"](reminder)
        await helpers["save_idempotency"](user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
        return resp

    @app.patch("/v1/reminders/{reminder_id}", dependencies=[Depends(check_idempotency)])
    async def update_reminder(
        request: Request,
        reminder_id: str,
        payload: ReminderUpdate,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        if hasattr(request.state, "idempotent_response"):
            return request.state.idempotent_response
        update_data = payload.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        reminder = (
            await db.execute(select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user_id))
        ).scalar_one_or_none()
        if reminder is None:
            raise HTTPException(status_code=404, detail="Reminder not found")
        before_snapshot = helpers["_reminder_snapshot"](reminder)
        new_recurrence_rule = reminder.recurrence_rule
        if "title" in update_data and isinstance(update_data["title"], str):
            reminder.title = update_data["title"].strip()
        if "message" in update_data:
            reminder.message = update_data["message"]
        if "work_item_id" in update_data:
            reminder.work_item_id = update_data["work_item_id"]
        if "person_id" in update_data:
            reminder.person_id = update_data["person_id"]
        if "recurrence_rule" in update_data:
            new_recurrence_rule = helpers["_validated_recurrence_rule"](update_data["recurrence_rule"])
            reminder.recurrence_rule = new_recurrence_rule
        if "kind" in update_data and update_data["kind"] is not None:
            reminder.kind = helpers["_coerce_reminder_kind"](update_data["kind"])
        if new_recurrence_rule and reminder.kind == ReminderKind.one_off:
            reminder.kind = ReminderKind.recurring
        if not new_recurrence_rule and reminder.kind == ReminderKind.recurring:
            reminder.kind = ReminderKind.one_off
        if reminder.kind == ReminderKind.recurring and not new_recurrence_rule:
            raise HTTPException(status_code=400, detail="Recurring reminders require recurrence_rule")
        if "remind_at" in update_data:
            remind_at = helpers["_parse_due_at"](update_data["remind_at"])
            if remind_at is None:
                raise HTTPException(status_code=400, detail="Invalid remind_at")
            reminder.remind_at = remind_at
        if "status" in update_data and update_data["status"] is not None:
            reminder.status = helpers["_coerce_reminder_status"](update_data["status"])
            reminder.last_sent_at = helpers["utc_now"]() if reminder.status == ReminderStatus.sent else reminder.last_sent_at
            reminder.completed_at = helpers["utc_now"]() if reminder.status == ReminderStatus.completed else None
            reminder.dismissed_at = helpers["utc_now"]() if reminder.status == ReminderStatus.dismissed else None
        reminder.updated_at = helpers["utc_now"]()
        after_snapshot = helpers["_reminder_snapshot"](reminder)
        await helpers["_record_reminder_action_batch"](
            db,
            user_id=user_id,
            source_message=f"API update reminder: {reminder.id}",
            proposal_json=payload.model_dump(mode="json", exclude_unset=True),
            version_records=[
                {
                    "reminder_id": reminder.id,
                    "operation": VersionOperation.update,
                    "before_json": before_snapshot,
                    "after_json": after_snapshot,
                }
            ],
        )
        await db.commit()
        await _attach_reminder_work_item_titles([reminder], user_id, db)
        resp = helpers["_reminder_view_payload"](reminder)
        await helpers["save_idempotency"](user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
        return resp

    @app.post("/v1/reminders/{reminder_id}/snooze", dependencies=[Depends(check_idempotency)])
    async def snooze_reminder(
        request: Request,
        reminder_id: str,
        payload: ReminderSnoozeRequest,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        if hasattr(request.state, "idempotent_response"):
            return request.state.idempotent_response
        reminder = (
            await db.execute(select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user_id))
        ).scalar_one_or_none()
        if reminder is None:
            raise HTTPException(status_code=404, detail="Reminder not found")
        next_remind_at = helpers["compute_snooze_remind_at"](
            payload.preset,
            now=helpers["utc_now"](),
            current_remind_at=reminder.remind_at,
            timezone_name=helpers["settings"].APP_TIMEZONE,
        )
        if next_remind_at is None:
            supported = ", ".join(helpers["supported_snooze_presets"]())
            raise HTTPException(status_code=400, detail=f"Unsupported snooze preset. Use one of: {supported}")
        before_snapshot = helpers["_reminder_snapshot"](reminder)
        reminder.status = ReminderStatus.pending
        reminder.remind_at = next_remind_at
        reminder.completed_at = None
        reminder.dismissed_at = None
        reminder.updated_at = helpers["utc_now"]()
        after_snapshot = helpers["_reminder_snapshot"](reminder)
        await helpers["_record_reminder_action_batch"](
            db,
            user_id=user_id,
            source_message=f"API snooze reminder: {reminder.id}",
            proposal_json={"preset": payload.preset, "action": "snooze"},
            version_records=[
                {
                    "reminder_id": reminder.id,
                    "operation": VersionOperation.update,
                    "before_json": before_snapshot,
                    "after_json": after_snapshot,
                }
            ],
            after_summary=f"Snoozed reminder {reminder.title}",
        )
        await db.commit()
        await _attach_reminder_work_item_titles([reminder], user_id, db)
        resp = helpers["_reminder_view_payload"](reminder)
        await helpers["save_idempotency"](user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
        return resp

    @app.post("/v1/reminders/dispatch_due", dependencies=[Depends(check_idempotency)])
    async def dispatch_due_reminders(
        request: Request,
        user_id: str = Depends(get_authenticated_user),
    ):
        if hasattr(request.state, "idempotent_response"):
            return request.state.idempotent_response
        job_id = str(uuid.uuid4())
        await helpers["redis_client"].rpush(
            "default_queue",
            json.dumps({"job_id": job_id, "topic": "reminders.dispatch", "payload": {"user_id": user_id}}),
        )
        resp = {"status": "ok", "enqueued": True, "job_id": job_id}
        await helpers["save_idempotency"](user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
        return resp

    @app.get("/v1/history/action_batches")
    async def list_action_batches(
        limit: int = 50,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        query = (
            select(ActionBatch)
            .where(ActionBatch.user_id == user_id)
            .order_by(ActionBatch.created_at.desc())
            .limit(min(limit, 200))
        )
        batches = (await db.execute(query)).scalars().all()
        return [helpers["_action_batch_view_payload"](batch) for batch in batches]

    @app.post("/v1/history/action_batches/{batch_id}/undo", dependencies=[Depends(check_idempotency)])
    async def undo_action_batch(
        request: Request,
        batch_id: str,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        if hasattr(request.state, "idempotent_response"):
            return request.state.idempotent_response
        batch = (
            await db.execute(select(ActionBatch).where(ActionBatch.id == batch_id, ActionBatch.user_id == user_id))
        ).scalar_one_or_none()
        if batch is None:
            raise HTTPException(status_code=404, detail="Action batch not found")
        if batch.status == ActionBatchStatus.reverted or batch.reverted_at is not None:
            raise HTTPException(status_code=409, detail="Action batch already reverted")
        expires_at = batch.undo_window_expires_at
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < helpers["utc_now"]():
                raise HTTPException(status_code=409, detail="Undo window expired")
        versions = (
            await db.execute(
                select(WorkItemVersion)
                .where(WorkItemVersion.action_batch_id == batch.id, WorkItemVersion.user_id == user_id)
                .order_by(WorkItemVersion.created_at.desc())
            )
        ).scalars().all()
        reminder_versions: List[ReminderVersion] = []
        if not versions:
            reminder_versions = (
                await db.execute(
                    select(ReminderVersion)
                    .where(ReminderVersion.action_batch_id == batch.id, ReminderVersion.user_id == user_id)
                    .order_by(ReminderVersion.created_at.desc())
                )
            ).scalars().all()
        if not versions and not reminder_versions:
            raise HTTPException(status_code=409, detail="Action batch has no reversible history")

        restored_ids: List[str] = []
        undo_batch: Optional[ActionBatch] = None
        if versions:
            revert_records: List[Dict[str, Any]] = []
            for version in versions:
                item = (
                    await db.execute(
                        select(WorkItem).where(WorkItem.id == version.work_item_id, WorkItem.user_id == user_id)
                    )
                ).scalar_one_or_none()
                if item is None:
                    raise HTTPException(status_code=409, detail=f"Work item {version.work_item_id} no longer exists")
                current_snapshot = helpers["work_item_snapshot"](item)
                before_json = version.before_json if isinstance(version.before_json, dict) else {}
                if before_json:
                    helpers["_restore_work_item_from_snapshot"](item, before_json)
                else:
                    item.status = WorkItemStatus.archived
                    item.archived_at = helpers["utc_now"]()
                    item.completed_at = None
                    item.updated_at = helpers["utc_now"]()
                restored_snapshot = helpers["work_item_snapshot"](item)
                revert_records.append(
                    {
                        "work_item_id": item.id,
                        "operation": VersionOperation.restore,
                        "before_json": current_snapshot,
                        "after_json": restored_snapshot,
                    }
                )
                restored_ids.append(item.id)
            undo_batch = await helpers["_record_work_item_action_batch"](
                db,
                user_id=user_id,
                source_message=f"Undo action batch {batch.id}",
                proposal_json={"undo_of": batch.id},
                version_records=revert_records,
                status=ActionBatchStatus.reverted,
                after_summary=f"Undid {len(revert_records)} work item change{'s' if len(revert_records) != 1 else ''}",
            )
        else:
            reminder_revert_records: List[Dict[str, Any]] = []
            for version in reminder_versions:
                reminder = (
                    await db.execute(
                        select(Reminder).where(Reminder.id == version.reminder_id, Reminder.user_id == user_id)
                    )
                ).scalar_one_or_none()
                if reminder is None:
                    raise HTTPException(status_code=409, detail=f"Reminder {version.reminder_id} no longer exists")
                current_snapshot = helpers["_reminder_snapshot"](reminder)
                before_json = version.before_json if isinstance(version.before_json, dict) else {}
                if before_json:
                    helpers["_restore_reminder_from_snapshot"](reminder, before_json)
                else:
                    reminder.status = ReminderStatus.canceled
                    reminder.completed_at = None
                    reminder.dismissed_at = None
                    reminder.updated_at = helpers["utc_now"]()
                restored_snapshot = helpers["_reminder_snapshot"](reminder)
                reminder_revert_records.append(
                    {
                        "reminder_id": reminder.id,
                        "operation": VersionOperation.restore,
                        "before_json": current_snapshot,
                        "after_json": restored_snapshot,
                    }
                )
                restored_ids.append(reminder.id)
            undo_batch = await helpers["_record_reminder_action_batch"](
                db,
                user_id=user_id,
                source_message=f"Undo action batch {batch.id}",
                proposal_json={"undo_of": batch.id},
                version_records=reminder_revert_records,
                status=ActionBatchStatus.reverted,
                after_summary=f"Undid {len(reminder_revert_records)} reminder change{'s' if len(reminder_revert_records) != 1 else ''}",
            )

        batch.status = ActionBatchStatus.reverted
        batch.reverted_at = helpers["utc_now"]()
        if not batch.after_summary:
            batch.after_summary = f"Reverted {len(restored_ids)} item{'s' if len(restored_ids) != 1 else ''}"
        await db.commit()
        resp = {
            "status": "ok",
            "reverted_batch_id": batch.id,
            "undo_batch": helpers["_action_batch_view_payload"](undo_batch),
            "restored_item_ids": restored_ids,
        }
        await helpers["save_idempotency"](user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
        return resp

    @app.get("/v1/work_items/{item_id}/versions")
    async def list_work_item_versions(
        item_id: str,
        limit: int = 50,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        versions = (
            await db.execute(
                select(WorkItemVersion)
                .where(WorkItemVersion.user_id == user_id, WorkItemVersion.work_item_id == item_id)
                .order_by(WorkItemVersion.created_at.desc())
                .limit(min(limit, 100))
            )
        ).scalars().all()
        return [helpers["_work_item_version_view_payload"](version) for version in versions]

    @app.get("/v1/reminders/{reminder_id}/versions")
    async def list_reminder_versions(
        reminder_id: str,
        limit: int = 50,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        versions = (
            await db.execute(
                select(ReminderVersion)
                .where(ReminderVersion.user_id == user_id, ReminderVersion.reminder_id == reminder_id)
                .order_by(ReminderVersion.created_at.desc())
                .limit(min(limit, 100))
            )
        ).scalars().all()
        return [helpers["_reminder_version_view_payload"](version) for version in versions]
