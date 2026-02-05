# LLM Integration

Objectives
- Enable natural language control with minimal tokens and clear, reliable tools.
- Keep conversations lean: summaries first, then expand only selected items.

Usage patterns
- Summarize then act: list tasks in summary form; select by index or id; run batch updates.
- Classify on demand: when a user explains reasoning, classify into labels/problems/goals, then update tasks.
- Progressive disclosure: avoid dumping large lists; page with limit/offset.

Token efficiency
- Minimal fields by default; opt‑in heavy fields via `fields` or `format=detailed`.
- Use `limit=20` and page; avoid “list all” unless necessary.
- Handles: list returns a handle for the current selection. Subsequent calls use { handle, select } to operate without resending.
- Summaries: each item includes a compact `summary` string; LLM can display that instead of raw objects.

Prompts and instructions (for Claude or others)
- Stay focused on tasks/problems/goals; prefer tool calls over speculation.
- When the user provides reasoning, capture it as `why` and suggest labels/problems/goals.
- Confirm scope for bulk actions; operate via batch tools with clear selection.
- Hide internal ids in human output unless asked; refer by short indexes.

Common flows
- Overdue → today
  - list tasks with { overdue: true, limit: 20, format: "summary" }
  - show compact table and ask to confirm selection
  - batch_update { ids: [..], updates: { due_date: today } }

- Work → tomorrow
  - list tasks { label: "work", limit: 20 }
  - batch_update { ids: [..], updates: { due_date: tomorrow } }

- Reason‑driven categorization
  - user writes: “This helps reduce stress because …”
  - suggest_mappings(text) → predicted labels/problems/goals/impact/why
  - update_task with suggested fields (after confirmation if needed)

Error handling and retries
- Always check JSON‑RPC errors in responses; do not assume HTTP status.
- On partial failures in batch updates, report per‑item outcomes.

