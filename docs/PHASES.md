# Phased Plan

## Current Status (2026-03-25)
- The legacy v1 implementation exists and remains useful as a reference baseline.
- That baseline is now superseded by the local-first redesign.
- Rework Phase R0 is the current planning phase.

## Rework Principles
- Keep the working Telegram product shape that already proved valuable.
- Replace the underlying model and architecture where the old design is now holding the product back.
- Remove Todoist from the target system.
- Build the local database into the real product.

## Phase R0: Product Reset and Domain Design
### Goals
- Freeze the new local-first product direction.
- Define the unified `work_items` model and supporting tables.
- Define the Telegram-first and web-secondary product contract.
- Record the rework sequence before code changes start.

### Exit Criteria
- Direction, architecture, roadmap, and rework spec are published.
- Core entities and invariants are agreed.
- Todoist is explicitly deprecated in the product plan.

## Phase R1: Unified Work Item Schema
### Goals
- Introduce `work_items` with `project | task | subtask`.
- Add `work_item_aliases`, `work_item_links`, `areas`, `people`, and `reminders`.
- Add `action_batches` and `work_item_versions`.
- Define export-and-discard strategy for any legacy `tasks/goals/problems` rows worth keeping.

### Exit Criteria
- New schema and migrations exist.
- Legacy entities can be backfilled or mapped into the new schema.
- Action history and version tracking are first-class.

## Phase R2: Telegram Write Path Migration
### Goals
- Move Telegram conversational writes onto the new `work_items` model.
- Preserve model-first intent routing.
- Use bounded candidate resolution against aliases, hierarchy, people, areas, and recent context.
- Keep confirmation-first write behavior.

### Exit Criteria
- Telegram action proposals write only to the new local schema.
- Clarification and confirmation flows work against `work_items`.
- Old Todoist-oriented assumptions are removed from Telegram write handling.

## Phase R3: Planner, Today, Urgent, and Reminder Engine
### Goals
- Rebuild planning against `work_items`, reminders, and hierarchy.
- Replace legacy plan storage with `plan_snapshots`.
- Add local reminder scheduling and delivery.
- Add daily brief and weekly review primitives.

### Exit Criteria
- `/today` and `/urgent` are served from the new planner.
- Reminder jobs are local and Todoist-independent.
- Plan state is reproducible from local DB only.

## Phase R4: Web Interface
### Goals
- Add a lightweight web UI over the new domain model.
- Support manual editing, cleanup, browsing, and review.
- Support project/task/subtask navigation.
- Support reminder and history inspection.

### Exit Criteria
- Web UI can inspect and edit work items safely.
- Web UI supports maintenance tasks without becoming the primary UX.

## Phase R5: Undo, History, and Operator Safety
### Goals
- Expose recent action history.
- Add undo/revert for recent action batches.
- Improve backup, restore, and operator diagnostics around the new model.

### Exit Criteria
- Recent changes can be inspected and reversed safely.
- Restore and recovery procedures are documented against the new schema.
- Model mistakes are recoverable without manual DB surgery.

## Phase R6: Legacy Removal
### Goals
- Remove Todoist sync and reconcile.
- Remove legacy task/goal/problem-specific runtime paths once replaced.
- Remove obsolete commands and code that only existed to work around legacy constraints.

### Exit Criteria
- Todoist is fully removed from runtime behavior and primary docs.
- Legacy schema paths are no longer on the main execution path.
- The product is internally consistent around the new domain model.

## Phase R7: Product Polish and Daily-Use Refinement
### Goals
- Tighten Telegram conversation quality against real user transcripts.
- Improve reminder quality and planning trustworthiness.
- Refine subtask request UX and project promotion behavior.
- Reduce operator friction in the web UI and runbooks.

### Exit Criteria
- Daily use no longer depends on commands or legacy workarounds.
- Project/task/subtask flows feel natural.
- Reminders, planning, and undo are trustworthy enough for regular personal use.

## Non-Goals During Rework
- Reintroducing external task sync.
- Building a collaboration product.
- Expanding into a large dashboard-heavy web application.
- Adding broad connector ecosystems before the core local product is solid.
