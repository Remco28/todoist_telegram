# DIY Motivated Tasks — Planning

This project designs a lightweight, LLM‑friendly task system that tracks not just what to do, but why. It introduces Problems and Goals alongside Tasks so that actions ladder up to meaningful outcomes and motivation.

Guiding principles
- LLM‑first: tools are simple, composable, and token‑efficient.
- Motivation‑aware: every task can carry a Why and link to Problems and Goals.
- Minimal by default: summaries first, details on demand; small payloads.
- Portable: start local; optionally sync or run on a tiny VPS.
- Safe: keep data private; clear audit trails without leaking secrets.

Core concepts
- Task: what to do; may include a short why, labels, priority, due, and links.
- Problem: a friction or opportunity you are actively solving; tasks can attach.
- Goal: a longer‑term aim (financial, health, family, stress reduction); tasks can attach.
- Journal: optional short notes about reasoning or decisions; supports motivation.
- Metrics: actions taken per problem, impact‑weighted progress, recent momentum.

What this enables
- “Move all overdue tasks to today.”
- “Find work‑related tasks and move them to tomorrow.”
- “I want to reduce stress this week” → classify, schedule, and show progress.
- “This task advances my financial goals because …” → persist the why and link appropriately.

Scope for MVP
- CRUD for tasks, problems, labels; optional goals (read/write) or start read‑only.
- Bulk updates with safety checks (e.g., confirm selection).
- Filters: overdue, label, problem, goal, search; paging and field selection.
- Token efficiency: summary views by default; handles for large selections.

Documents in this folder
- DOMAIN_MODEL.md — entities, fields, relationships, and examples.
- API_MCP_DESIGN.md — tool list, schemas, responses, and token efficiency.
- STORAGE_SYNC.md — storage choices, cross‑device options, and ops.
- LLM_INTEGRATION.md — usage with Claude/other LLMs; prompts and guardrails.
- FLOWS.md — practical flows for everyday operations.
- SECURITY_PRIVACY.md — data safety, logging, and hosting considerations.
- ROADMAP.md — MVP milestones and future ideas.

Open questions
- Goal granularity: simple tags vs structured goals with timeframes?
- Problem scope: only active problems or archive/hide completed ones?
- Motivation model: a single why per task or a journal of evolving reasons?

