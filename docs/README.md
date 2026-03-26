# Documentation Index

## Current Direction
The repository is entering a local-first redesign.

Canonical planning docs:
- `docs/PROJECT_DIRECTION.md`: product mission, intent, and non-negotiable constraints.
- `docs/ARCHITECTURE_V1.md`: current architecture target for the local-first rebuild.
- `docs/PHASES.md`: rework phases and exit criteria.
- `docs/EXECUTION_PLAN.md`: current execution tracks, backlog, and immediate next session plan.

Supporting docs:
- `docs/MEMORY_AND_SESSION_POLICY.md`: memory/session rules for the redesign.
- `docs/PROMPT_CONTRACT.md`: prompt and model-output contract for the redesign.
- `docs/LEGACY_DOC_REVIEW.md`: what older planning documents are still worth keeping.
- `docs/contracts/`: legacy v1 JSON schemas. These remain useful for reference but are not the target end-state for the rework.

## Build Workflow
- Active architect task specs live in `comms/tasks/`.
- Completed specs are archived in `comms/tasks/archive/`.
- The new rework spec is the primary execution reference until implementation begins.

## Current Active Specs
- `comms/tasks/2026-03-25-local-first-telegram-rebuild-spec.md`

## Release and Operations
These runbooks still matter operationally during the transition:
- `ops/DEPLOY_CHECKLIST.md`
- `ops/RESTORE_RUNBOOK.md`
- `ops/PROD_ROLLOUT_CHECKLIST.md`
- `ops/SECRETS_ROTATION_RUNBOOK.md`
- `ops/OPERATIONS_BASELINE.md`

Note:
- Some ops docs still reference archival export steps while the final local-first cleanup is in progress.
- Product direction and architecture docs are the authoritative source for where the system is going next.

## Legacy Archive
- `archive/legacy_docs/diy_todo/`: older planning material.
- `archive/legacy_docs/oldproject/`: previous Todoist-centric prototype artifacts.
