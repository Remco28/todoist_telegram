# Architecture v1

## High-Level Components
- Telegram Bot Service
- Core API Service (HTTP + optional MCP surface)
- Planner/Memory Worker Service
- Postgres (source of truth)
- Redis (queue/cache; optional but recommended)
- Todoist Sync Worker
- LLM Provider Adapter Layer

## Interaction Modes
- Query mode (read-only): answer questions from stored graph + summaries.
- Draft action mode (no-write): parse intent and generate a proposed mutation plan.
- Apply action mode (write-enabled): apply previously confirmed proposal transactionally and sync.
- Mode selection is backend controlled using intent classification and policy rules.

## Telegram Conversational Contract (Target)
1. User sends free-form text.
2. Backend classifies message:
- `query`: answer directly, no writes.
- `action`: generate structured proposal and show confirmation summary.
 - natural-language routing is primary; slash commands are optional fallback controls.
3. Bot asks for confirmation (`yes`, `edit`, `no`):
- `yes`: commit DB writes and enqueue immediate Todoist sync.
- `edit`: regenerate proposal with user clarifications.
- `no`: discard draft.
4. All applied changes are logged with request id and proposal provenance.
5. Rule: no autonomous durable writes from ambiguous conversational text without confirmation.

## Runtime Model (Coolify)
- `api` container: request handling, business logic, auth, tool endpoints.
- `worker` container: async jobs (summarization, planning refresh, sync).
- `postgres` managed DB: private network only.
- `redis` container (optional): queue + idempotency/cache.
- `caddy/nginx` (or Coolify edge): TLS termination and routing.

## Todoist Synchronization
- Downstream sync (`sync.todoist`): pushes local task changes to Todoist.
- Reconciliation sync (`sync.todoist.reconcile`): pulls mapped remote task state back into local tasks.
- Reconcile applies deterministic rules:
- Remote completion sets local task to `done`.
- For open local tasks, remote `content/description/priority/due` updates local fields.
- Missing remote mapped tasks are marked as terminal drift errors and logged; local tasks are not deleted in v1.
- Every reconcile run emits explicit audit events for applied updates, remote-missing drift, per-task failures, and run completion.

## Core Data Model
- `inbox_items`: raw captured user messages and metadata.
- `tasks`: actionable items; status, due, priority, impact.
- `problems`: ongoing friction/opportunity areas.
- `goals`: higher-level outcomes with category/timeframe.
- `task_links`: typed relationships (`depends_on`, `blocks`, `supports_goal`, `related`).
- `entity_links`: task-to-problem and task-to-goal joins.
- `memory_summaries`: session/weekly summaries.
- `event_log`: append-only audit of AI and system actions.
- `sync_state`: Todoist mapping + watermark/version info.
- `sessions`: app-level conversation windows keyed by user/chat.
- `prompt_runs`: record prompt version, model, token usage, latency, and outcome.
- `recent_context_items`: short-lived list of recently shown entity ids for follow-up resolution.
- `telegram_user_map`: maps Telegram `chat_id` to internal `user_id` after secure onboarding.
- `telegram_link_tokens`: one-time short-lived token hashes used for Telegram account linking.

## Memory Engine
### Purpose
Keep long-term context accurate and compact.

### Layers
- Hot memory: active session context (small).
- Warm memory: rolling summaries (day/week level).
- Cold memory: full source records (messages + events).

### Flow
1. New message captured to `inbox_items`.
2. Extraction job creates/updates structured entities.
3. Summarization job updates session summary and durable facts.
4. Retrieval composes context by recency + semantic match + graph proximity.

### Session Semantics
- API calls are stateless by default; continuity is created by backend retrieval.
- App session windows are configurable (for example, inactivity timeout).
- Raw transcript retention and compaction are policy-driven.
- Structured entities persist independently of transcript retention.

### Controls
- Strict token budget for prompt context assembly.
- Deduplication of repeated facts.
- Provenance pointers from summaries to source events.

## Planning Refresh Engine
### Purpose
Produce ordered execution plans from structured state.

### Hybrid Design
- Deterministic scoring for rank/order.
- LLM layer for language rewrite, tie-breaking rationale, and ambiguity handling.

### Suggested Scoring Inputs
- Urgency (due/overdue)
- Impact
- Goal alignment strength
- Dependency/blocker status
- Age/staleness
- Effort/context fit (optional phase 2)

### Outputs
- `today_plan`
- `next_actions`
- `blocked_items`
- `why_this_order`

## Write Pipeline (LLM-Assisted, Backend-Enforced)
1. Capture raw message.
2. Build grounded context (active tasks/goals/problems/links + recent summaries).
3. Call provider action planner operation for strict JSON proposal (`intent`, `scope`, `actions[]`, `confidence`, `needs_confirmation`).
4. Call provider critic operation to detect unsafe or low-quality proposals (duplicates, contradictions, missing targets, risky bulk ops).
5. Validate against schema and policy constraints.
6. Present proposal to user for confirmation when policy requires.
7. Execute proposal deterministically after confirmation (no hidden semantic inference in executor).
8. Commit transactional DB updates.
9. Emit audit events, enqueue memory summarization, and enqueue immediate Todoist sync for changed tasks.

Rule: provider suggests, backend decides, backend writes.

## Action Intelligence Contract (v1.1 Direction)
- Primary behavior comes from LLM planning + critique, not phrase-to-action hardcoding.
- Deterministic code is limited to:
  - schema validation,
  - safety policy checks,
  - transactional execution,
  - retries/fallback handling.
- Phrase heuristics must not be used to guess destructive or mutating intent.
- Any fallback path may only recover from schema/format issues; it must not infer broad writes from token coincidence.
- Every applied write must be traceable to a concrete proposed action in stored draft payload.
- For task mutations (`update`, `complete`, `archive`), execution is ID-first (`target_task_id` required).
- Unresolved targets and low-confidence plans route to clarification mode, not guessed writes.

## Clarification Mode
- Clarification is a first-class response type for conversational action handling.
- Trigger conditions:
  - low planner confidence,
  - unresolved mutation targets,
  - non-actionable planner/critic outputs after sanitization.
- Behavior:
  - ask one concrete follow-up question,
  - do not create or apply ambiguous mutations,
  - preserve audit trace for operator review.

## Telegram Identity Flow
1. API user requests one-time Telegram link token.
2. Backend stores only token hash + TTL.
3. User sends `/start <token>` to Telegram bot.
4. Webhook validates token, consumes it, and stores `chat_id -> user_id`.
5. Only linked chats can run Telegram commands or free-text capture writes.

## LLM Provider Adapter
### Design
Abstract provider-specific APIs behind one interface:
- `extract_structured_updates(input)`
- `summarize_memory(context)`
- `rewrite_plan(plan_state)`
- `answer_query(query, retrieved_context)`

### Why
- Prevent lock-in.
- Swap Grok/OpenAI/Anthropic/Gemini without rewriting business logic.
- Keep retries, timeouts, and fallback policies consistent.

## Grok Compatibility
- Grok can be integrated as a provider behind the adapter.
- MCP support can be used where helpful, but core should still call your own API/DB logic.
- Treat provider tool features as optional acceleration, not architecture dependency.
- Grok stateful continuation can be used for short-term efficiency.
- Provider-side memory is optimization only; durable memory remains in app DB.

## Prompt Contract
- Layer 1: compact system policy (invariant guardrails).
- Layer 2: operation prompt (`extract`, `query`, `plan`, `summarize`).
- Layer 3: retrieved context (token-budgeted, relevance-ranked).
- Layer 4: user message.
- Prompt templates are versioned and logged per request.

## Token Efficiency Strategy
- Small invariant policy included every call.
- Operation-specific prompts kept short and purpose-built.
- Context from retrieval, not full transcript replay.
- Deterministic code handles scoring/filtering/linking to reduce LLM tokens.
- Cache-friendly repeated context where provider supports caching.

## API/MCP Surface (v1)
- `capture/thought`
- `tasks/list`, `tasks/create`, `tasks/update`, `tasks/close`
- `problems/list`, `problems/create`, `problems/update`
- `goals/list`, `goals/create`, `goals/update`
- `links/create`, `links/delete`
- `memory/refresh`
- `plan/refresh`, `plan/get_today`
- `sync/todoist/run`

## Recent Context Items (Optional but Recommended)
- Store ids of entities shown in recent query responses (for example, last 20).
- Keep short retention (for example, 24-72 hours).
- Use for follow-up references like "those", "the second one", or "show me more on that task".
- Keep database records as source of truth; this cache is only a convenience layer.

## Reliability and Security
- API auth required (token/JWT).
- Postgres private-only.
- Idempotency keys for capture/update endpoints.
- Job retries with backoff + dead-letter queue.
- Encrypted backups + restore drills.
- Structured logs and health endpoints.
- Provider call budgets and alerts (token, latency, error rates).
