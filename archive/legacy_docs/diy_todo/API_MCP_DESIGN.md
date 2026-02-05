# API and MCP Design

Goals
- Simple tools that map natural language intents to small, explicit operations.
- Token‑efficient by default; summaries, paging, field selection, and handles.
- Consistent errors and small, predictable response shapes.

Content conventions
- All list results return `structuredContent` as an object with `{ items: [...] }`.
- Include a `summary` field when `format=summary` to compress output.
- Provide `handle` identifiers for large selections to avoid resending full payloads.

Common parameters
- limit: integer (default 20; max e.g. 200)
- offset: integer (default 0)
- fields: array<string> (whitelist; default minimal: ["id","content","labels","priority","due_date","status","problem_ids","goal_ids"]) 
- format: string ("summary" | "detailed"; default "summary")

Tools (MVP)
- tasks/list
  - description: List tasks with filters and paging.
  - arguments: { label?, problem_id?, goal_id?, status?, overdue?, search?, limit?, offset?, fields?, format? }
  - returns: { items: Task[], handle?: string, total?: integer }

- tasks/create
  - arguments: { content, description?, why?, labels?, priority?, due_date?, parent_id?, problem_ids?, goal_ids?, impact? }
  - returns: { task: Task }

- tasks/update
  - arguments: { id, content?, description?, why?, labels?, priority?, due_date?, status?, parent_id?, problem_ids?, goal_ids?, impact? }
  - returns: { task: Task }

- tasks/close, tasks/reopen
  - arguments: { id }
  - returns: { ok: true, task?: Task }

- tasks/delete
  - arguments: { id }
  - returns: { ok: true }

- tasks/batch_update
  - description: Apply the same or per‑item updates to many tasks.
  - arguments: { ids?: string[], updates?: object, items?: array<{id, updates}> }
  - safety: require at least one id; cap size; optionally dry_run flag.
  - returns: { updated: array<{id, ok: boolean, error?: string}> }

- problems/list
  - arguments: { active?, search?, limit?, offset?, fields?, format? }
  - returns: { items: Problem[], handle?: string, total?: integer }

- problems/create, problems/update, problems/delete
  - arguments: standard CRUD
  - returns: entity or { ok: true }

- problems/link_task, problems/unlink_task
  - arguments: { task_id, problem_id }
  - returns: { ok: true }

- goals/* (optional in MVP; same pattern as problems)

- classify/suggest_mappings (optional helper)
  - description: Suggest labels, problems, goals, priority, due_date, and impact for text or task ids.
  - arguments: { text?, task_ids? }
  - returns: { suggestions: array<{ target: 'task'|'text', id?: string, labels?, problem_ids?, goal_ids?, priority?, due_date?, impact?, why? }> }

JSON‑RPC/MCP behavior
- initialize returns capabilities with tools support and simple instructions.
- tools/list returns tool metadata with inputSchema per tool (JSON Schema 2020‑12).
- tools/call returns `structuredContent` + `content: [{type:"text", text:"…"}]`.
- errors: always HTTP 200; include { error: { code, message } }.

Token efficiency techniques
- Minimal fields by default; client opts into heavy fields with `fields` or `format=detailed`.
- Pagination with `limit/offset` keeps lists small.
- Handles: list endpoints can return a `handle` token referencing the current selection; future calls accept { handle, select: indices | ids } to operate without resending the list.
- Summaries: include a compressed `summary` string for human display; omit null/empty fields.

Input validation
- Validate types and allowed ranges; collect errors per field with helpful messages.
- On batch operations, report per‑item results; do not fail the whole batch when possible.

Example response (summary list)
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "structuredContent": {
      "items": [
        {"id": "01J7…", "content": "Schedule dentist", "labels": ["health","admin"], "priority": 3, "due_date": "2025-09-05", "status": "open", "problem_ids": ["01J7…"], "goal_ids": ["01J7…"], "summary": "Schedule dentist (P3, 2025-09-05) [health, admin]"}
      ],
      "handle": "h_abc123",
      "total": 42
    },
    "content": [{"type": "text", "text": "1 items (showing 1 of 42)."}],
    "isError": false
  }
}
```

