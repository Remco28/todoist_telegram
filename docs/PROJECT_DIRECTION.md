# Project Direction

## Mission
Build an AI-powered personal execution system where you can send free-form thoughts and the system organizes them into tasks, problems, goals, and prioritized plans.

## Product Direction
- Primary interface: Telegram bot.
- Core system: backend API + database + workers on Hetzner/Coolify.
- AI engine: LLM API provider (provider-agnostic; Grok/OpenAI/Anthropic/Gemini can be plugged in).
- Todoist role: downstream sync target, not source of truth.
- CLI role: optional clients/adapters only (not core infrastructure).
- Interaction model: one conversational UX with two backend modes:
- Query mode (read-only answers from stored state)
- Action mode (auto-structure and write updates)

## Non-Negotiable Requirements
- User ideas are the source of truth.
- AI can auto-create tasks from messages.
- Persistent memory must stay useful without prompt bloat.
- Relationships between tasks/problems/goals must be explicit and queryable.
- System must run reliably on VPS with backups, auth, and observability.
- LLM never writes directly to the database; backend validates and writes.

## Guiding Principles
- Backend-first: stable core, replaceable interfaces.
- Deterministic where possible: rules/scoring for priority, LLM for language and inference.
- Auditability: every important AI action is logged with source context.
- Safe automation: auto-create allowed, destructive/bulk changes require policy guardrails.
- Incremental delivery: ship vertical slices that are usable immediately.
- Prompt contract owned by backend and versioned in repo.

## v1 Scope
- Capture free-form messages and auto-structure them.
- Store tasks, problems, goals, and links in Postgres.
- Generate and refresh ordered plans.
- Summarize memory in compact layers.
- Sync selected tasks to Todoist.
- Expose API/MCP endpoints for future clients.
- Support provider-stateful continuation as an optimization, while treating DB memory as source of truth.

## Out of Scope for v1
- Multi-user collaboration.
- Full custom mobile app.
- Heavy analytics dashboards.
- Complex workflow automation marketplace.
