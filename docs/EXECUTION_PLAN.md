# Execution Plan

## Current Execution Status (2026-03-25)
- The previous Todoist-integrated v1 proved the Telegram interface, confirmation flow, planning concepts, and operational baseline.
- The product direction has now changed.
- The current execution focus is a local-first rebuild around a stronger database and simpler product boundaries.
- The unified `work_items` schema is landed and active in the runtime.
- `/today`, `/urgent`, deterministic open-task views, recent task grounding, and `/done` now operate through `work_items`.
- Canonical maintenance API surface is now fully local-first: `/v1/work_items` for work and `/v1/reminders` for reminders.
- Todoist sync/reconcile is no longer part of the live runtime path: the API no longer enqueues Todoist jobs, the worker no longer handles Todoist topics, and the Todoist sync/status endpoints have been removed.
- First local reminder slice is now live: `/v1/reminders` create/list/update plus worker-backed due reminder dispatch to Telegram.
- Reminder-aware planning is live: `/today` payloads and formatting now surface due reminders from the local scheduler.
- First lightweight maintenance UI slice is live at `/app?token=<api_token>`, backed directly by `/v1/work_items` and `/v1/reminders`.
- Recent local audit visibility is live: `/v1/history/action_batches` and `/v1/work_items/{item_id}/versions`, and the maintenance UI now shows recent change batches.
- Undo is live for reversible work-item action batches via `POST /v1/history/action_batches/{batch_id}/undo`, and the maintenance UI can trigger it directly.
- Reminder version history is now live via `/v1/reminders/{reminder_id}/versions`, and the same undo route can now restore reminder snapshots as well as work-item snapshots.
- Reminder recurrence now has a bounded local contract (`daily`, `weekly`, `weekdays`, `monthly`), recurring reminders reschedule themselves after dispatch, and the maintenance UI can drill into both work-item and reminder version history.
- Conversational reminder writes are now threaded through the Telegram draft/apply path: grounding includes active reminders, planner/extraction actions can create/update/complete/cancel reminders, and Telegram previews/acks now render reminder changes directly.
- Telegram reminder clarification is now live for incomplete conversational reminder writes: missing reminder targets trigger reminder-name clarification, and missing reminder times trigger a direct scheduling clarification instead of a generic dead end.
- Recent reminder context is now part of grounding too: active reminder changes are remembered in `recent_context_items`, reminder candidate resolution prefers recent reminder refs, and the conversational path can reuse recent reminder context without leaking reminder ids to the user.
- `/today` and worker reminder dispatch now both feed reminder visibility back into recent context, and reminder-aware query answers do the same for follow-up grounding.
- Legacy slash `/plan`, `/focus`, and `/ask` are now fully removed from the live Telegram command handler in favor of the conversation-first flow; hidden `/done` remains as the single deterministic fallback.
- Dead Todoist adapter/config residue has been removed from the live codebase; remaining cleanup is now mostly archive/export support and doc tightening rather than active runtime code.
- Capture and memory no longer treat `Goal` / `Problem` rows as primary: new goal/problem entities are created as project-shaped `work_items` first and mirrored back only for compatibility.
- The legacy `/v1/tasks`, `/v1/goals`, and `/v1/problems` maintenance endpoints are no longer registered. The canonical local-first API is the only supported maintenance surface.
- The canonical local-first maintenance/history surface has now been split out of `backend/api/main.py` into dedicated route registration modules, reducing API bloat while keeping behavior unchanged.
- The app/ops/planning route layer is now split too: maintenance UI, health/preflight, and plan/read endpoints live outside `backend/api/main.py`, leaving the remaining API bloat concentrated mostly in Telegram/capture orchestration.
- The Telegram integration and interaction route layer is now split as well: webhook/link-token routes plus capture/query endpoints no longer live directly in `backend/api/main.py`, leaving the remaining bloat concentrated primarily in Telegram orchestration helpers rather than route registration.
- The Telegram command/link-token/message orchestration helpers are now split out too: `backend/api/telegram_orchestration.py` owns command handling plus link-token and message/callback routing wrappers, and `backend/api/main.py` is now down to the core draft/apply/query helper cluster.
- Telegram plan-view and clarification staging helpers are now split out as well: `backend/api/telegram_views.py` owns plan cache/view helpers plus clarification-draft staging, and the remaining `backend/api/main.py` bloat is now concentrated mainly in the single Telegram draft/apply flow and shared apply/query internals.
- The Telegram draft/apply flow itself is now split too: `backend/api/telegram_draft_flow.py` owns the model-first conversational draft/apply/query orchestration, and `backend/api/main.py` is now mainly shared apply/query helpers plus a smaller set of route-independent internals.
- The shared capture/apply/history helper block is now split as well: `backend/api/capture_apply.py` owns `_apply_capture(...)`, action-batch/version snapshot helpers, and reminder/work-item restore logic, leaving `backend/api/main.py` much smaller and focused mainly on shared grounding/query/auth helpers plus a few remaining route-independent internals.
- The shared request/auth/idempotency helper block is now split too: `backend/api/request_runtime.py` owns auth token resolution, rate limiting, extraction payload validation, and idempotency persistence, leaving `backend/api/main.py` focused mainly on shared grounding/reference-resolution helpers plus a smaller set of remaining route-independent internals.
- The shared grounding/reference-resolution helper block is now split too: `backend/api/grounding_runtime.py` owns extraction grounding, recent-context persistence, displayed-task resolution, query-surface follow-up context, and reminder/task answer inference, while `backend/api/main.py` keeps thin wrapper names so existing Telegram tests can still patch `api.main` safely. `backend/api/main.py` is now down to roughly 2.7k lines.
- The shared task/reminder candidate-resolution block is now split too: `backend/api/reference_resolution.py` owns task/reminder candidate scoring, target sanitization, clarification prompt building, and clarification target filling, while `backend/api/main.py` keeps thin wrapper names so the rest of the Telegram flow still resolves through `api.main`. `backend/api/main.py` is now down to roughly 2.0k lines.
- The shared draft lifecycle block is now split too: `backend/api/draft_runtime.py` owns planner confidence/autopilot decisions, extraction normalization, and the action-draft create/revise/confirm lifecycle, while `backend/api/main.py` keeps thin wrapper names so existing Telegram tests can still patch `api.main._create_action_draft`, `api.main._revise_action_draft`, and `api.main._confirm_action_draft`. `backend/api/main.py` is now down to roughly 1.6k lines.
- The shared maintenance/preflight helper block is now split too: `backend/api/maintenance_runtime.py` owns due parsing, work-item/reminder view payloads, recurrence validation, and work-item update helpers, while `backend/api/health_runtime.py` owns the external preflight/credential checks and cached report logic. `backend/api/main.py` is now down to roughly 1.4k lines.
- Legacy runtime mirroring is now removed: canonical reads/writes, `/done`, undo, grounding, memory, and compaction no longer depend on legacy `tasks / goals / problems / entity_links`. Current data preservation happens through explicit markdown export utilities (`cd backend && python3 ops/export_local_first_markdown.py` for the live local-first model, `cd backend && python3 ops/export_legacy_markdown.py` for archive-only legacy rows) when needed.
- Reminder maintenance is now more complete: the local-first API and `/app` workbench expose bounded snooze presets (`1h`, `tomorrow_morning`, `next_week`) and direct parent/work-item linkage fields instead of relying on vague manual edits.
- Explicit local-first hierarchy writes are now live in the conversational path: extraction/planning can create `project -> task -> subtask` structures when the user explicitly asks for subtasks, and can promote an existing task into a project without dropping out of the normal Telegram draft/apply flow.
- Hierarchy context is now surfaced more consistently too: task grounding and clarification scoring can use parent titles, and the `/app` workbench now renders work items in parent-aware order with parent names instead of raw parent ids.
- The maintenance workbench now supports bounded work-item edits directly from `/app`, which brings the web surface closer to the intended “light cleanup/editing” role without turning it into a second primary interface.
- Reminder follow-through is now tighter too: reminder grounding and clarification scoring can use linked work-item titles, reminder API payloads can expose those titles, and the `/app` workbench now supports bounded reminder edits instead of only status/snooze actions.
- Goal/problem compatibility buckets are now folded immediately into project-shaped `tasks[]` entries during validation/normalization, so the live write path no longer carries separate runtime branches for those legacy entity types.
- Telegram now has a distinct due-today read path: natural-language questions like “what is due today?” no longer collapse into the broader ranked agenda used by `/today`.
- Planner hierarchy deferral semantics are tighter too: future-dated parent work now suppresses child leakage into `/today` unless a child carries its own explicit earlier date.
- Telegram applied-change acknowledgements are now expandable too: long change sets can expose inline `Show more` and `Show subtasks` callbacks backed by recorded action-batch history instead of permanently hiding overflow behind `+N more change(s)`.
- Immediate next implementation phase: finish final local-first polish rather than more architectural churn, with emphasis on maintenance UX, reminder follow-through, and remaining repo/schema cleanup.
- Ongoing design constraint: keep Telegram interpretation model-first. Deterministic rescue logic is allowed only as a narrow grounding/safety layer and should not grow back into phrase-based intent routing.

## Active Implementation Tracks
- Track A: Data model and migrations
- Track B: Telegram and API behavior
- Track C: Planner, reminders, and worker jobs
- Track D: Web UI
- Track E: Operations, history, backups, and restore

## Priority Backlog (Now)
1. Remove or archive the remaining legacy schema/docs once any needed rows have been exported to markdown.
2. Keep polishing reminder semantics where needed, but stay within the bounded local-first model already in place.
3. Remove the last Todoist-era schema/docs remnants from the repo.
4. Extend the lightweight web UI from version drill-down into bounded edit/history navigation without turning it into the main product surface.
5. Add a one-time data cleanup path for any exported/re-entered legacy rows that should become canonical projects/tasks/subtasks.

## Priority Backlog (After Schema Approval)
1. Move Telegram write flow onto `work_items`.
2. Move planning and `/today` / `/urgent` onto the new planner inputs.
3. Add reminder scheduling and delivery.
4. Add action history and undo UI.
5. Remove remaining legacy Todoist data structures and dead code.

## Definition of Done (Rework)
- Telegram is the primary daily interface.
- Web UI is sufficient for cleanup, editing, browsing, and undo.
- Local Postgres is the only source of truth.
- No external task platform is required.
- The system supports projects, tasks, and subtasks.
- The assistant can resolve common conversational references against aliases, recent context, and hierarchy.
- Every confirmed write is versioned and reversible.
- Daily planning and reminders run locally.

## Key Risks and Mitigations
- Risk: the schema gets over-engineered.
  - Mitigation: keep the core centered on one entity type (`work_item`) plus a small set of supporting tables.
- Risk: removal of Todoist cuts off a useful fallback UI.
  - Mitigation: add the lightweight web interface early enough to replace the missing maintenance path.
- Risk: model autonomy causes wrong task targeting.
  - Mitigation: bounded candidate resolution, action history, undo, and version snapshots.
- Risk: repeated Telegram hotfixes slowly reintroduce heuristic-first behavior.
  - Mitigation: prefer prompt/grounding/session improvements first, keep rescue logic narrowly scoped to visible-context recovery, and periodically prune fallback code that starts carrying semantic interpretation.
- Risk: reminder logic becomes coupled to planner logic.
  - Mitigation: keep reminders as a separate model and scheduler layer.
- Risk: rework stalls because legacy code remains partially active too long.
  - Mitigation: phase the migration clearly and remove old paths aggressively once replaced.

## Immediate Next Session Plan
1. Keep polishing conversational follow-through, especially multi-turn task and reminder edits.
2. Use the new explicit session state to improve active-entity grounding and pending clarification recovery.
3. Add bounded maintenance UI affordances for version navigation, restore context, and hierarchy editing where they still feel thin.
4. Remove or archive the remaining legacy schema/docs once any needed rows have been exported to markdown.
