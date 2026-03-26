import time
import uuid
from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException, Request

from api.schemas import (
    QueryAskRequest,
    QueryResponseV1,
    TelegramLinkTokenCreateResponse,
    TelegramWebhookResponse,
    ThoughtCaptureRequest,
    ThoughtCaptureResponse,
)


async def run_create_telegram_link_token(user_id: str, db, *, helpers: Dict[str, Any]):
    return await helpers["_issue_telegram_link_token"](user_id, db)


async def run_telegram_webhook(request: Request, db, *, helpers: Dict[str, Any]):
    if not helpers["verify_telegram_secret"](request.headers):
        raise HTTPException(status_code=403, detail="Unauthorized webhook source")

    try:
        update_json = await request.json()
    except Exception:
        return {"status": "ignored"}

    data = helpers["parse_update"](update_json)
    if not data:
        return {"status": "ignored"}

    chat_id = data["chat_id"]
    text = data.get("text", "")
    username = data.get("username")
    client_msg_id = data.get("client_msg_id")
    update_kind = data.get("kind")
    if not helpers["_is_telegram_sender_allowed"](chat_id, username):
        helpers["logger"].warning(
            "Ignoring telegram message from disallowed sender chat_id=%s username=%s",
            chat_id,
            username,
        )
        return {"status": "ignored"}

    try:
        if update_kind == "callback":
            await helpers["_handle_telegram_callback_update"](data, db)
        else:
            await helpers["_handle_telegram_message_update"](data, db)
    except Exception as exc:
        helpers["logger"].error(f"Telegram routing failed: {exc}")
        await helpers["send_message"](chat_id, "Sorry, I had trouble processing that message. Please try again later.")

    return {"status": "ok"}


async def run_capture_thought(request: Request, payload: ThoughtCaptureRequest, user_id: str, db, *, helpers: Dict[str, Any]):
    if hasattr(request.state, "idempotent_response"):
        return request.state.idempotent_response
    await helpers["enforce_rate_limit"](user_id, "capture", helpers["settings"].RATE_LIMIT_CAPTURE_PER_WINDOW)
    request_id = request.state.request_id
    session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=payload.chat_id)
    await helpers["_update_session_state"](
        db=db,
        session=session,
        current_mode="action",
        active_entity_refs=helpers["_session_state_payload"](session).get("active_entity_refs", []),
        pending_draft_id=helpers["_session_state_payload"](session).get("pending_draft_id"),
        pending_clarification=helpers["_session_state_payload"](session).get("pending_clarification"),
    )

    extraction = None
    for attempt_num in range(1, 3):
        start_time = time.time()
        try:
            grounding = await helpers["_build_extraction_grounding"](
                db=db, user_id=user_id, chat_id=payload.chat_id, message=payload.message
            )
            extraction = await helpers["adapter"].extract_structured_updates(payload.message, grounding=grounding)
            extraction = helpers["_apply_intent_fallbacks"](payload.message, extraction, grounding)
            extraction = helpers["_sanitize_completion_extraction"](extraction, grounding)
            extraction = helpers["_sanitize_create_extraction"](extraction)
            extraction = helpers["_sanitize_targeted_task_actions"](payload.message, extraction, grounding)
            extraction = helpers["_resolve_relative_due_date_overrides"](payload.message, extraction)
            usage = helpers["_extract_usage"](extraction)
            latency = int((time.time() - start_time) * 1000)
            helpers["_validate_extraction_payload"](extraction)
            db.add(
                helpers["PromptRun"](
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    operation="extract",
                    provider=helpers["settings"].LLM_PROVIDER,
                    model=helpers["settings"].LLM_MODEL_EXTRACT,
                    prompt_version=helpers["settings"].PROMPT_VERSION_EXTRACT,
                    latency_ms=latency,
                    status="success",
                    input_tokens=usage["input_tokens"],
                    cached_input_tokens=usage["cached_input_tokens"],
                    output_tokens=usage["output_tokens"],
                    created_at=helpers["utc_now"](),
                )
            )
            break
        except Exception as exc:
            db.add(
                helpers["PromptRun"](
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    operation="extract",
                    provider=helpers["settings"].LLM_PROVIDER,
                    model=helpers["settings"].LLM_MODEL_EXTRACT,
                    prompt_version=helpers["settings"].PROMPT_VERSION_EXTRACT,
                    status="error",
                    error_code=type(exc).__name__,
                    created_at=helpers["utc_now"](),
                )
            )
            if attempt_num == 2:
                await db.commit()
                raise HTTPException(status_code=422, detail="Extraction failed after retries")

    inbox_item_id, applied = await helpers["_apply_capture"](
        db=db,
        user_id=user_id,
        chat_id=payload.chat_id,
        source=payload.source,
        message=payload.message,
        extraction=extraction,
        request_id=request_id,
        client_msg_id=payload.client_msg_id,
        session_id=session.id,
    )
    resp = ThoughtCaptureResponse(
        status="ok",
        inbox_item_id=inbox_item_id,
        applied=applied,
        summary_refresh_enqueued=True,
    )
    await helpers["save_idempotency"](
        user_id, request.state.idempotency_key, request.state.request_hash, 200, resp.model_dump()
    )
    return resp


async def run_query_ask(payload: QueryAskRequest, user_id: str, db, *, helpers: Dict[str, Any]) -> QueryResponseV1:
    await helpers["enforce_rate_limit"](user_id, "query", helpers["settings"].RATE_LIMIT_QUERY_PER_WINDOW)
    session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=payload.chat_id)
    session_state = helpers["_session_state_payload"](session)
    await helpers["_update_session_state"](
        db=db,
        session=session,
        current_mode="query",
        active_entity_refs=session_state.get("active_entity_refs", []),
        pending_draft_id=session_state.get("pending_draft_id"),
        pending_clarification=session_state.get("pending_clarification"),
    )
    ctx = await helpers["assemble_context"](
        db=db,
        user_id=user_id,
        chat_id=payload.chat_id,
        query=payload.query,
        max_tokens=payload.max_tokens or helpers["settings"].QUERY_MAX_TOKENS,
        session_state=session_state,
    )
    start_time = time.time()
    request_id = str(uuid.uuid4())
    try:
        raw_resp = await helpers["adapter"].answer_query(payload.query, ctx)
        usage = helpers["_extract_usage"](raw_resp)
        query_response = QueryResponseV1(**raw_resp)
        db.add(
            helpers["PromptRun"](
                id=str(uuid.uuid4()),
                request_id=request_id,
                user_id=user_id,
                operation="query",
                provider=helpers["settings"].LLM_PROVIDER,
                model=helpers["settings"].LLM_MODEL_QUERY,
                prompt_version=helpers["settings"].PROMPT_VERSION_QUERY,
                latency_ms=int((time.time() - start_time) * 1000),
                input_tokens=usage["input_tokens"],
                cached_input_tokens=usage["cached_input_tokens"],
                output_tokens=usage["output_tokens"],
                status="success",
                created_at=helpers["utc_now"](),
            )
        )
    except Exception as exc:
        helpers["logger"].error(f"Query failure: {exc}")
        db.add(
            helpers["PromptRun"](
                id=str(uuid.uuid4()),
                request_id=request_id,
                user_id=user_id,
                operation="query",
                provider=helpers["settings"].LLM_PROVIDER,
                model=helpers["settings"].LLM_MODEL_QUERY,
                prompt_version=helpers["settings"].PROMPT_VERSION_QUERY,
                status="error",
                error_code=type(exc).__name__,
                created_at=helpers["utc_now"](),
            )
        )
        db.add(
            helpers["EventLog"](
                id=str(uuid.uuid4()),
                request_id=request_id,
                user_id=user_id,
                event_type="query_fallback_used",
                payload_json={"error": str(exc)},
            )
        )
        query_response = QueryResponseV1(answer="I'm sorry, I couldn't process your request.", confidence=0.0)
    await db.commit()
    return query_response


def register_interaction_routes(
    app: FastAPI,
    *,
    get_authenticated_user,
    get_db,
    check_idempotency,
    helpers: Dict[str, Any],
) -> None:
    @app.post("/v1/integrations/telegram/link_token", response_model=TelegramLinkTokenCreateResponse)
    async def create_telegram_link_token(
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        return await run_create_telegram_link_token(user_id, db, helpers=helpers)

    @app.post("/v1/integrations/telegram/webhook", response_model=TelegramWebhookResponse)
    async def telegram_webhook(request: Request, db=Depends(get_db)):
        return await run_telegram_webhook(request, db, helpers=helpers)

    @app.post("/v1/capture/thought", response_model=ThoughtCaptureResponse, dependencies=[Depends(check_idempotency)])
    async def capture_thought(
        request: Request,
        payload: ThoughtCaptureRequest,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        return await run_capture_thought(request, payload, user_id, db, helpers=helpers)

    @app.post("/v1/query/ask", response_model=QueryResponseV1, dependencies=[Depends(get_authenticated_user)])
    async def query_ask_endpoint(
        payload: QueryAskRequest,
        user_id: str = Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        return await helpers["query_ask"](payload, user_id=user_id, db=db)
