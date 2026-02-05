# AI Task Brain

AI-powered personal execution system for capturing free-form thoughts, organizing them into structured work, and generating actionable plans.

## Current Status
- Direction and architecture are defined in `docs/`.
- Contracts for first LLM operations are defined in `docs/contracts/`.
- Legacy materials are archived in `archive/legacy_docs/`.

## Canonical Docs
- `docs/PROJECT_DIRECTION.md`
- `docs/ARCHITECTURE_V1.md`
- `docs/PHASES.md`
- `docs/EXECUTION_PLAN.md`
- `docs/MEMORY_AND_SESSION_POLICY.md`
- `docs/PROMPT_CONTRACT.md`

## Repo Layout
- `docs/`: active project documentation and contracts.
- `archive/legacy_docs/`: historical reference only.
- `comms/`: role/process notes from earlier workflow setup.
- `.gemini/`: project-scoped Gemini MCP configuration.

## Next Build Step
Scaffold implementation folders:
- `api/`
- `worker/`
- `migrations/`

Then implement the first vertical slice: `capture/thought` with validated extract output and transactional writes.
