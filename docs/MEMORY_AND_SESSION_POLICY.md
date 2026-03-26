# Memory and Session Policy

## Principles
- Providers are stateless by default.
- Durable memory belongs to the app database.
- Structured state is more important than raw transcript replay.
- Recent visible context is part of the conversational contract, not just a retrieval hint.

## Session Model
- Session key: `user_id + chat_id`
- Telegram remains the primary session surface.
- Session boundaries help organize conversation and summarization, but they do not define durable work state.

## Retention Model
- Structured entities are retained until archived or explicitly deleted by policy.
- Action history and versions are retained for traceability and undo.
- Session summaries are retained long-term.
- Raw transcripts are policy-driven and may be compacted.
- Recent visible context is short-lived but important for follow-up grounding.

## Primary Structured Memory
The new memory model should prioritize:
- `work_items`
- `work_item_aliases`
- `work_item_links`
- `people`
- `areas`
- `reminders`
- `plan_snapshots`
- `action_batches`
- `work_item_versions`

## Memory Layers
- Hot: recent turns, pending draft state, recent visible items
- Warm: rolling summaries, recent plan snapshots, recent action batches
- Cold: full entity state, versions, reminders, conversation events

## Context Assembly Rules
- Always include the current user message.
- Always include the operation instruction.
- Include only relevant recent visible work items and aliases.
- Include parent/child hierarchy when it matters.
- Include related people/areas when they materially help grounding.
- Include reminders and plan context when the user is asking about time-sensitive work.
- Enforce a hard token budget.
- Trim low-value transcript text before trimming structured state.

## Write Safety Rules
- Model output is always a proposal.
- Backend validates schema and policy constraints.
- Backend resolves or rejects candidate targets.
- Backend writes transactionally.
- Every confirmed write creates durable history.

## Query Safety Rules
- Queries are read-only by default.
- Query answers may surface work items for follow-up grounding.
- Query mode must not silently mutate durable state.

## Recent Context
The app should preserve short-lived context for:
- recently displayed items
- recently mentioned items
- recently changed items
- pending clarification candidates

This is essential for follow-ups like:
- "that one"
- "the register task"
- "move it to next week"

## Explicit Subtask Policy
- The system should not auto-generate subtasks by default.
- If the user explicitly asks for a breakdown, that request becomes structured state in the draft.
- Suggested subtasks should be retained as part of the proposal until confirmed or discarded.

## No-Action Message Handling
- Non-action conversational text may still contribute to summaries and context.
- No-action retention must not bypass write safety.
- The point of retaining no-action text is better future understanding, not hidden automation.
