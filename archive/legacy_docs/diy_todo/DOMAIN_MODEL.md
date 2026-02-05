# Domain Model

Overview
- Focus on a small set of entities with clear links so LLMs can reason simply.
- Prefer explicit fields and normalized relationships; allow light denormalization for performance.

Entities
- Task
  - id: string (ULID/UUID)
  - content: string (required)
  - description: string (optional)
  - why: string (optional, short motivation)
  - labels: array<string>
  - priority: integer (1–4, 4 highest)
  - due_date: string (YYYY-MM-DD) or null
  - status: string (‘open’ | ‘closed’)
  - parent_id: string | null (subtasks)
  - problem_ids: array<string> (links)
  - goal_ids: array<string> (links)
  - impact: integer (0–5, subjective impact toward linked problems/goals)
  - created_at: ISO datetime
  - updated_at: ISO datetime

- Problem
  - id: string
  - title: string (required)
  - description: string
  - area: string (e.g., ‘stress’, ‘productivity’, ‘home’, ‘work’)
  - label_hints: array<string> (labels that tend to relate)
  - active: boolean (default true)
  - created_at, updated_at
  - computed: actions_taken_count (completed linked tasks); momentum (recent cadence)

- Goal (optional in MVP or simple tag variant)
  - id: string
  - title: string (required)
  - category: string (e.g., ‘financial’, ‘health’, ‘family’, ‘stress’)
  - timeframe: string (e.g., ‘2025-Q4’, ‘this_year’)
  - success_criteria: string
  - active: boolean
  - created_at, updated_at
  - computed: progress_heuristic (impact‑weighted completions)

- JournalEntry (optional)
  - id: string
  - task_id: string | null
  - problem_id: string | null
  - goal_id: string | null
  - text: string (short rationale, reflection, or decision)
  - created_at

Relationships
- A Task can link to multiple Problems and Goals.
- Problems and Goals do not require tasks but aggregate metrics from linked tasks.
- Labels are freeform strings; may overlap with Problem/Goal areas.

Computed metrics (examples)
- Problem.actions_taken_count: number of closed tasks linking to the problem.
- Problem.momentum: weighted count over a recent window (e.g., last 14 days).
- Goal.progress_heuristic: sum(task.impact for closed tasks with goal_id) normalized.

Sample JSON
```json
{
  "tasks": [
    {
      "id": "01J7YQ2M4Z4T9B28QJ3W0V2NYV",
      "content": "Schedule dentist appointment",
      "why": "Reduces stress and supports health",
      "labels": ["health", "admin"],
      "priority": 3,
      "due_date": "2025-09-05",
      "status": "open",
      "parent_id": null,
      "problem_ids": ["01J7YQ0W4RDXK1MZV18H4WX8JQ"],
      "goal_ids": ["01J7YQ0C9P6A3K2K3C2FF8Z0E3"],
      "impact": 3,
      "created_at": "2025-09-02T17:15:00Z",
      "updated_at": "2025-09-02T17:15:00Z"
    }
  ],
  "problems": [
    {
      "id": "01J7YQ0W4RDXK1MZV18H4WX8JQ",
      "title": "Lingering admin tasks cause stress",
      "description": "Too many small undone tasks pile up",
      "area": "stress",
      "label_hints": ["admin", "inbox"],
      "active": true,
      "created_at": "2025-09-01T12:00:00Z",
      "updated_at": "2025-09-02T17:00:00Z",
      "actions_taken_count": 12,
      "momentum": 5
    }
  ]
}
```

IDs and timestamps
- Use ULIDs or UUIDv4 for ids; monotonic ULIDs help ordering without DB queries.
- Maintain created_at/updated_at for audit; update only on changes.

Extensibility
- Add per‑task custom fields as needed; keep core schema stable.
- Support soft‑delete flags to avoid data loss.

