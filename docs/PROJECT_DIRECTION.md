# Project Direction

## Mission
Build a Telegram-native personal execution system that helps one user think out loud, stay organized, and act on the right things without depending on a third-party task product.

## Product Intent
This product is a Telegram-native executive assistant that lets a user think out loud, ask questions, and make lightweight changes conversationally, while the system turns that into reliable structured state, plans, reminders, and history behind the scenes.

## Product Direction
- Primary interface: Telegram.
- Secondary interface: lightweight web UI for review, editing, cleanup, and history inspection.
- Core system: backend API + database + worker/scheduler.
- Source of truth: local Postgres database.
- Queue/cache: Redis, only where it materially simplifies reminders, planning, or request handling.
- AI engine: provider-agnostic LLM adapter.
- External task platforms: not required. Todoist is being removed from the product direction.
- Interaction model: conversation first, commands second.
- Visible Telegram command surface should stay minimal.
- Durable writes should come from structured proposals plus backend validation, not from raw text execution.
- Subtasks are supported, but subtask generation is explicit by request, not automatic by default.
- Hierarchy is intentionally shallow and practical:
- `project -> task -> subtask`
- The user should be able to promote a task into a project without losing continuity.

## Current Reality Check (2026-03-25)
- The repository may still contain legacy v1 tables for one-shot export, but the live app does not expose or depend on legacy `tasks`, `goals`, or `problems` routes.
- The live runtime no longer depends on Todoist sync/reconcile.
- That implementation proved useful for validating conversational capture, confirmation, planning, and Telegram delivery.
- It is no longer the target architecture.
- The next major rework will simplify the system into a local-first assistant with:
- a unified work-item model,
- first-class history and undo,
- stronger grounding data for the model,
- reminders and planning owned locally,
- no Todoist dependency.

## Non-Negotiable Requirements
- The local database is the product and the source of truth.
- Telegram must feel conversational; slash commands are optional shortcuts, not the main mental model.
- The backend, not the model, owns validation, write execution, and auditability.
- Every durable change must be reversible or at least inspectable through action history.
- The system must support projects, tasks, and subtasks cleanly.
- Subtasks must only be generated when explicitly requested by the user or explicitly confirmed after a suggestion.
- The system must preserve recent visible context so follow-ups like "that one" or "move the register task" work naturally.
- The system must remain single-user and opinionated rather than trying to become a generic collaboration platform.
- The web UI must stay lightweight and maintenance-oriented.
- The system must run reliably on a VPS with backups, restore drills, and clear operational logs.

## Guiding Principles
- Local first: no external task platform should be required for the product to be useful.
- Telegram first: the best experience should happen in conversation, not in a dashboard.
- Structured state over transcript sprawl: the DB should store enough shape, aliases, and history that the model can reason against real entities.
- Backend-enforced safety: the model can interpret intent and propose structure, but the backend validates and writes.
- Reversible operations: prefer archives, versions, action batches, and undo over irreversible edits.
- Shallow useful hierarchy: support projects/tasks/subtasks, but avoid deep nested workflow trees.
- Explicit decomposition: task breakdown is a capability the user asks for, not background automation.
- Explainable grounding: target resolution should be understandable and inspectable.
- Keep the surface small: fewer commands, fewer integrations, fewer product modes.

## v2 Scope
- Replace the legacy `task / goal / problem` split with a unified `work_items` model.
- Support `project`, `task`, and `subtask` as item kinds.
- Add aliases, structured links, reminders, recent context, plan snapshots, action batches, and version history.
- Keep Telegram as the primary UX for capture, queries, changes, confirmations, reminders, and daily planning.
- Add a small web UI for editing fields, browsing history, inspecting plans, and undoing mistakes.
- Add local planner and reminder scheduling that do not depend on Todoist.
- Keep provider support pluggable and prompt contracts versioned.

## Out of Scope
- Multi-user collaboration and shared workspaces.
- Deep project-management features like swimlanes, kanban boards, and portfolio dashboards.
- Generic automation marketplace or large connector ecosystem.
- Full custom mobile app.
- Sync parity with Todoist or any other external task manager.

## Immediate Direction
1. Redesign the domain model around unified work items and durable change history.
2. Remove Todoist from the target architecture and deprecate it from user-facing documentation.
3. Preserve the existing strengths:
- Telegram confirmations
- conversational queries
- planning
- operational logging
4. Add the missing capabilities that matter more in a local-first system:
- reminders
- undo
- aliases
- project/task/subtask hierarchy
- lightweight web editing
