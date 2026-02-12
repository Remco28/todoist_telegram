# Phase 15 Advisory Remediation Plan (Architect Packet)

## Context
Two advisory reviews identified post-launch risks in performance, maintainability, and reliability. We accepted all items marked `Agree` or `Strongly Agree` and are converting them into execution-ready specs.

## Rationale
The simplest path is to fix system truths in this order:
1. Prevent avoidable runtime/ops risk first.
2. Reduce structural complexity in the highest-churn endpoint.
3. Then improve model-behavior architecture and schema debt.

This sequencing minimizes regression risk while improving quality where the app is currently weakest.

## Execution Order
1. `comms/tasks/2026-02-11-phase-15a-sync-time-and-ops-hardening-spec.md`
2. `comms/tasks/2026-02-11-phase-15b-telegram-webhook-modularization-spec.md`
3. `comms/tasks/2026-02-11-phase-15c-planner-authority-and-schema-polish-spec.md`

## Advisory-to-Spec Mapping
- Todoist sync efficiency -> 15A
- UTC timestamp consistency -> 15A
- Memory compaction safety for draft references -> 15A
- Backup retention safety guardrail -> 15A
- Telegram webhook God-function refactor -> 15B
- Telegram HTML escaping consistency audit -> 15B
- Planner vs heuristic overlap reduction -> 15C
- Pydantic v2 migration cleanup -> 15C
- Memory token estimator precision path + observability -> 15C

## Global Constraints (All 15x Specs)
- Do not change public API contracts unless explicitly listed.
- Keep migrations reversible and minimal.
- Preserve current Telegram UX behavior while refactoring internals.
- Add tests for every behavioral change.
- Keep provider-specific logic isolated to adapter boundary.

## Done Definition (Phase 15 Packet)
- All three specs implemented and pass architect review.
- Test suite remains green.
- No production behavior regressions in capture/query/plan/sync Telegram flows.
- Documentation updated where flow ownership changes.
