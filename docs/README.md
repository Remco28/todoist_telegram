# Documentation Index

## Build Workflow
- Active Architect task specs live in `comms/tasks/`.
- Completed task specs are archived in `comms/tasks/archive/`.
- Phase 1 task specifications and revisions are archived under `comms/tasks/archive/`.
- Phase 2 and Phase 3 task specifications and revisions are archived under `comms/tasks/archive/`.
- Phase 4 test specification is archived under `comms/tasks/archive/`.
- Phase 5 specification and revisions are archived under `comms/tasks/archive/`.
- Phase 6 hardening specification is archived under `comms/tasks/archive/`.
- Phase 7 specification and revision are archived under `comms/tasks/archive/`.
- Phase 8 through Phase 12 specifications are archived under `comms/tasks/archive/`.
- Phase 13 implementation specification is active in `comms/tasks/`.

## Canonical Direction (Current)
- `docs/PROJECT_DIRECTION.md`: mission, product direction, scope boundaries.
- `docs/ARCHITECTURE_V1.md`: technical architecture, engines, runtime model.
- `docs/PHASES.md`: phased roadmap with exit criteria.
- `docs/EXECUTION_PLAN.md`: actionable backlog, risks, and next-session plan.
- `docs/ADVISORY_2026_02_10.md`: independent advisory review used to align next-phase priorities.
- `docs/MEMORY_AND_SESSION_POLICY.md`: session semantics, retention, and memory assembly rules.
- `docs/PROMPT_CONTRACT.md`: backend-owned prompt architecture and output contracts.
- `docs/contracts/`: concrete v1 JSON Schemas for `extract`, `query`, and `plan`.
- `docs/LEGACY_DOC_REVIEW.md`: keep/merge/archive/discard recommendations for old docs.

## Release Readiness
- `ops/DEPLOY_CHECKLIST.md`: release gates, deploy sequence, rollback checklist.
- `ops/RESTORE_RUNBOOK.md`: restore steps and release-incident first-response flow.
- Staging smoke invocation:
  - `RUN_STAGING_SMOKE=1 STAGING_API_BASE_URL=<url> STAGING_AUTH_TOKEN=<token> DATABASE_URL=<db> REDIS_URL=<redis> cd backend && pytest -q tests/test_phase8_staging_smoke.py`

## Current Active Spec
- `comms/tasks/2026-02-11-phase-13-production-rollout-spec.md`

## Legacy Archive
- `archive/legacy_docs/diy_todo/`: earlier planning set kept for reference.
- `archive/legacy_docs/oldproject/`: prior Todoist MCP prototype artifacts.
