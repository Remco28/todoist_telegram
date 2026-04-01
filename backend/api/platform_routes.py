import json
import uuid
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text

from api.schemas import PlanRefreshRequest, PlanRefreshResponse, PlanResponseV1
from common.models import EventLog, PromptRun, Session
from common.maintenance_ui import render_maintenance_ui


def register_platform_routes(
    app: FastAPI,
    *,
    get_authenticated_user,
    get_db,
    check_idempotency,
    helpers: Dict[str, Any],
) -> None:
    @app.get("/app", response_class=HTMLResponse)
    async def maintenance_workbench(token: Optional[str] = None):
        return HTMLResponse(render_maintenance_ui(token))

    @app.get("/health/live")
    async def health_live():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready(db=Depends(get_db)):
        try:
            await db.execute(text("SELECT 1"))
            await helpers["redis_client"].ping()
        except Exception:
            raise HTTPException(status_code=503, detail="Infrastructure unreachable")
        if helpers["_external_preflight_required"]():
            report = await helpers["_get_preflight_report"]()
            if not report.get("ok"):
                failing = [
                    name
                    for name, item in (report.get("checks") or {}).items()
                    if not (isinstance(item, dict) and item.get("ok") is True)
                ]
                fail_key = failing[0] if failing else "unknown"
                reason = ((report.get("checks") or {}).get(fail_key) or {}).get("reason", "preflight_failed")
                raise HTTPException(
                    status_code=503,
                    detail=f"Preflight failed: {fail_key}:{reason}",
                )
        return {"status": "ready"}

    @app.get("/health/preflight")
    async def health_preflight():
        if not helpers["_external_preflight_required"]():
            return {"status": "skipped", "reason": "preflight_not_required_in_env", "env": helpers["settings"].APP_ENV}
        report = await helpers["_get_preflight_report"]()
        return {
            "status": "ok" if report.get("ok") else "failed",
            "checked_at": report.get("checked_at"),
            "checks": report.get("checks", {}),
        }

    @app.get("/health/metrics", dependencies=[Depends(get_authenticated_user)])
    async def health_metrics(db=Depends(get_db)):
        window_hours = helpers["settings"].OPERATIONS_METRICS_WINDOW_HOURS
        window_cutoff = helpers["utc_now"]() - timedelta(hours=window_hours)

        queue_depth = {
            "default_queue": await helpers["redis_client"].llen("default_queue"),
            "dead_letter_queue": await helpers["redis_client"].llen("dead_letter_queue"),
        }

        failure_events = (await db.execute(
            select(EventLog).where(
                EventLog.created_at >= window_cutoff,
                EventLog.event_type.in_(["worker_retry_scheduled", "worker_moved_to_dlq"])
            )
        )).scalars().all()

        retry_count = 0
        dlq_count = 0
        for event in failure_events:
            if event.event_type == "worker_retry_scheduled":
                retry_count += 1
            elif event.event_type == "worker_moved_to_dlq":
                dlq_count += 1

        tracked_topics = ("memory.summarize", "memory.compact", "plan.refresh", "reminders.dispatch")
        last_success_by_topic: Dict[str, Optional[str]] = {topic: None for topic in tracked_topics}
        completed_events = (await db.execute(
            select(EventLog).where(
                EventLog.event_type == "worker_topic_completed"
            ).order_by(EventLog.created_at.desc()).limit(1000)
        )).scalars().all()
        for event in completed_events:
            payload = event.payload_json or {}
            topic = payload.get("topic")
            if topic not in last_success_by_topic or last_success_by_topic[topic] is not None:
                continue
            if event.created_at:
                last_success_by_topic[topic] = event.created_at.isoformat()
            if all(last_success_by_topic.values()):
                break

        total_failures = retry_count + dlq_count
        return {
            "window_hours": window_hours,
            "window_started_at": window_cutoff.isoformat(),
            "queue_depth": queue_depth,
            "failure_counters": {
                "retry_scheduled": retry_count,
                "moved_to_dlq": dlq_count,
                "total": total_failures,
                "alert_threshold": helpers["settings"].WORKER_ALERT_FAILURE_THRESHOLD,
                "alert_triggered": total_failures >= helpers["settings"].WORKER_ALERT_FAILURE_THRESHOLD,
            },
            "last_success_by_topic": last_success_by_topic,
        }

    @app.get("/health/costs/daily", dependencies=[Depends(get_authenticated_user)])
    async def health_costs_daily(user_id: str = Depends(get_authenticated_user), db=Depends(get_db)):
        day_start = helpers["utc_now"]().replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        rows = (await db.execute(
            select(PromptRun).where(
                PromptRun.user_id == user_id,
                PromptRun.created_at >= day_start,
                PromptRun.created_at < day_end
            )
        )).scalars().all()

        total_input_tokens = 0
        total_output_tokens = 0
        total_cached_input_tokens = 0
        by_operation_model: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            input_tokens = row.input_tokens or 0
            output_tokens = row.output_tokens or 0
            cached_input_tokens = row.cached_input_tokens or 0
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            total_cached_input_tokens += cached_input_tokens
            key = f"{row.operation}|{row.model}"
            entry = by_operation_model.setdefault(
                key,
                {
                    "operation": row.operation,
                    "model": row.model,
                    "runs": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cached_input_tokens": 0,
                },
            )
            entry["runs"] += 1
            entry["input_tokens"] += input_tokens
            entry["output_tokens"] += output_tokens
            entry["cached_input_tokens"] += cached_input_tokens

        def _estimate(input_t: int, output_t: int, cached_t: int) -> float:
            usd = (
                ((input_t - cached_t) / 1_000_000.0) * helpers["settings"].COST_INPUT_PER_MILLION_USD
                + (cached_t / 1_000_000.0) * helpers["settings"].COST_CACHED_INPUT_PER_MILLION_USD
                + (output_t / 1_000_000.0) * helpers["settings"].COST_OUTPUT_PER_MILLION_USD
            )
            return round(max(usd, 0.0), 8)

        breakdown = []
        for entry in by_operation_model.values():
            entry["estimated_usd"] = _estimate(
                entry["input_tokens"],
                entry["output_tokens"],
                entry["cached_input_tokens"],
            )
            breakdown.append(entry)
        breakdown.sort(key=lambda item: (item["operation"], item["model"]))

        return {
            "day_utc": day_start.date().isoformat(),
            "totals": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cached_input_tokens": total_cached_input_tokens,
                "estimated_usd": _estimate(total_input_tokens, total_output_tokens, total_cached_input_tokens),
            },
            "breakdown": breakdown,
        }

    @app.post("/v1/plan/refresh", response_model=PlanRefreshResponse, dependencies=[Depends(check_idempotency)])
    async def plan_refresh(
        request: Request,
        payload: PlanRefreshRequest,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        if hasattr(request.state, "idempotent_response"):
            return request.state.idempotent_response
        await helpers["enforce_rate_limit"](user_id, "plan", helpers["settings"].RATE_LIMIT_PLAN_PER_WINDOW)
        job_id = str(uuid.uuid4())
        await helpers["redis_client"].rpush(
            "default_queue",
            json.dumps({"job_id": job_id, "topic": "plan.refresh", "payload": {"user_id": user_id, "chat_id": payload.chat_id}}),
        )
        resp = PlanRefreshResponse(status="ok", enqueued=True, job_id=job_id)
        await helpers["save_idempotency"](user_id, request.state.idempotency_key, request.state.request_hash, 200, resp.model_dump())
        return resp

    @app.get("/v1/plan/get_today", response_model=PlanResponseV1, dependencies=[Depends(get_authenticated_user)])
    async def get_today_plan(chat_id: Optional[str] = None, user_id: str = Depends(get_authenticated_user), db=Depends(get_db)):
        resolved_chat_id = str(chat_id or "").strip()
        if not resolved_chat_id:
            latest_session = (
                await db.execute(
                    select(Session)
                    .where(Session.user_id == user_id)
                    .order_by(Session.last_activity_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not isinstance(latest_session, Session) or not str(latest_session.chat_id or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail="chat_id required because no recent Telegram session was found for this user",
                )
            resolved_chat_id = str(latest_session.chat_id).strip()
        payload, _ = await helpers["_load_today_plan_payload"](db, user_id, resolved_chat_id, require_fresh=True)
        return PlanResponseV1(**payload)

    @app.get("/v1/memory/context", dependencies=[Depends(get_authenticated_user)])
    async def get_memory_context(
        chat_id: str,
        query: str,
        max_tokens: Optional[int] = None,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        return await helpers["assemble_context"](db=db, user_id=user_id, chat_id=chat_id, query=query, max_tokens=max_tokens)
