# Flows

Overdue → Today (bulk)
- Intent: Move overdue tasks to today.
- Steps:
  - tasks/list { overdue: true, limit: 20, format: "summary" }
  - Present compact list (index, content, due, labels).
  - Confirm selection (all or subset by index/id).
  - tasks/batch_update { ids: [...], updates: { due_date: today } }
  - Optionally add a short why if missing: “Reduce stress by clearing backlog.”

Label → Tomorrow (bulk)
- Intent: Reschedule by context.
- Steps:
  - tasks/list { label: "work", limit: 20 }
  - Confirm selection; then tasks/batch_update { updates: { due_date: tomorrow } }

Attach tasks to a Problem
- Intent: Group actions under a solvable problem to build momentum.
- Steps:
  - problems/list { search: "stress" } or create a new problem.
  - tasks/list { search: "admin|billing|inbox" } to find candidates.
  - problems/link_task for selected tasks.
  - Result: Problem.actions_taken_count will rise as tasks complete.

Capture reasoning (why)
- Intent: Strengthen motivation and context.
- Steps:
  - For a single task: tasks/update { id, why: "…" }
  - For many tasks: batch_update with a shared why or none (keep individual why’s distinct).

Reduce stress this week
- Intent: Identify and act on stress‑reducing tasks.
- Steps:
  - problems/list { area: "stress", active: true }
  - tasks/list { label: "admin", limit: 20 } and suggest problem links and due dates.
  - batch_update selected tasks to schedule small wins over the week.
  - JournalEntry optional: “Plan to reduce stress via quick admin wins.”

Review progress
- Intent: See momentum and progress by problem.
- Steps:
  - problems/list { format: "summary" } → include actions_taken_count and momentum.
  - Optionally expand a specific problem to detailed view and recent completions.

