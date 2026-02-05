# LLM Features

Purpose
- Capture motivation and momentum by augmenting Tasks with Problems, Goals, and Why.
- Use LLMs to propose, clarify, and schedule tasks while keeping token usage low and actions auditable.

MVP Priority (recommend)
1) Problem Review: concise brief + insights for a selected Problem.
2) Action Suggestions: propose 3–7 concrete next tasks (content, why, labels, due, impact, links).
3) Smart Reschedule: bulk proposals for overdue→today, work→tomorrow with rationale.
4) Next Action Rewrite: improve vague tasks into clear, actionable phrasing.
5) Label Normalization: suggest canonical labels and merges.

Token Efficiency Principles
- Summary-first: default to summary fields and limit=20; expand specific items on demand.
- Field selection: opt-in to heavy fields via `fields` or `format=detailed`.
- Handles: list tools return `handle` identifiers; subsequent calls reference `handle + indices/ids`.
- Delta replies: bulk operations return compact summaries of changes rather than full objects.

Feature Details

Problem Review (Deep Dive)
- Outcome: short brief describing the Problem, recent actions, momentum trend, and blockers.
- Inputs: problem_id (or search), optionally timeframe for momentum (e.g., last 14 days).
- Outputs: { brief, insights: [short bullets], metrics: { actions_taken_count, momentum }, references: top linked tasks (summary) }.
- Tools: problems/review (read-only), tasks/list (linked tasks), optional expand item.

Action Suggestions
- Outcome: concrete next steps that connect to Problems/Goals with a motivating Why.
- Inputs: problem_id (or goal_id), context note (e.g., "this week small wins"), constraints (max_items=5).
- Outputs: suggestions: [{ content, why, labels[], due_date?, impact?, problem_ids[], goal_ids[] }].
- Tools: tasks/suggest_for_problem (read-only suggestion), tasks/create (apply selected suggestions).
- Guardrails: suggestions are separate from state changes; user/agent explicitly applies them.

Smart Reschedule
- Outcome: prioritized reschedule proposals (e.g., overload today? push low-impact to tomorrow; pull overdue to today).
- Inputs: filters (overdue=true, label="work"), scheduling constraints (target day), max items.
- Outputs: [{ id, proposed_due_date, rationale }].
- Tools: tasks/list (select candidates), tasks/suggest_reschedule (read-only), tasks/batch_update (apply).
- Guardrails: summarise planned changes; require confirmation for bulk.

Next Action Rewrite
- Outcome: turn vague phrasing into clear next actions with acceptance criteria hints.
- Inputs: task_id or text; optional style guidelines (verb-first, <= 70 chars).
- Outputs: { improved_content, optional_description, notes }.
- Tools: tasks/rewrite (suggest), tasks/update (apply).

Label Normalization
- Outcome: propose canonical labels and merges (e.g., Work/work/office → work).
- Inputs: current label set (summary) and usage counts.
- Outputs: mapping: { from_label: to_label, reason }[]; confidence levels optional.
- Tools: labels/normalize_suggestions (suggest), tasks/batch_update (apply mapped labels).

Additional Opportunities (Later)
- Decomposition: tasks/suggest_subtasks → 3–5 micro-steps.
- Duplicates: tasks/find_duplicates → clusters to merge.
- Energy/Context buckets: suggest labels like low_energy, deep_work, phone.
- Templates: SOP/checklist suggestions for recurring Problems (taxes, travel).
- Reflection: weekly nudge summarizing wins and sticking points; journal entries.

Safety & Explainability
- Separate suggest vs apply paths to avoid unintended changes.
- Keep a short rationale (why) on suggestions and changes.
- Confidence flags (low/medium/high) guide quick acceptance vs review.
- Change summaries: “Moved 6 overdue tasks to today (Problem: Stress backlog)”.

Minimal Default Field Set (summary mode)
- id, content, labels[], priority, due_date, status, problem_ids[], goal_ids[], summary, why?
- Avoid large descriptions by default; expand only when requested.

UX Patterns
- Progressive disclosure: show one screen of summaries, ask for confirmation, then act.
- Index-based selection: refer to items by small indices in current handle to minimize tokens.
- Quick exit ramps: always allow “show details for #3” without re-listing everything.

