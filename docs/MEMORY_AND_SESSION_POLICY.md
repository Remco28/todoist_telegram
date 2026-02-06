# Memory and Session Policy

## Principles
- API providers are treated as stateless by default.
- App-level memory is owned by backend storage.
- Structured records are more important than raw transcript history.

## Session Model
- Session key: `user_id + chat_id`.
- Active session: configurable inactivity timeout.
- New message after timeout starts a new app session window.
- Session boundaries are metadata; they do not delete structured memory.

## Retention Model
- Structured entities (`tasks`, `problems`, `goals`, links): retained until archived/deleted by policy.
- Session summaries: retained long-term.
- Raw transcripts: retention window configurable per environment.
- Event/audit logs: retained for operational and traceability requirements.

## Memory Layers
- Hot: recent turns in current session.
- Warm: rolling daily/weekly summaries.
- Cold: full source records and event history.

## Context Assembly Rules
- Always include compact system policy.
- Always include operation instruction.
- Always include current user message.
- Add only relevant memory from latest summary.
- Add only top related entities by recency and graph relevance.
- Enforce hard token budget on assembled context.
- Trim raw turns first when over budget.
- Trim low-relevance entities next when over budget.
- Never drop core policy or operation instructions.

## Write Safety Rules
- LLM output is proposal only.
- Backend validates JSON schema and policy constraints.
- Backend performs transactional writes.
- All write decisions logged with source and prompt/model versions.

## Query Safety Rules
- Query mode is read-only by default.
- Any detected write intent must route to action mode.
- Ambiguous intents can return a clarification prompt or low-risk default behavior.

## Recent Context Cache (Optional)
- On read-only answers, store a short list of surfaced entity ids for quick follow-ups.
- Limit retention to a short window.
- Do not treat this cache as canonical memory; it only helps reference resolution.
