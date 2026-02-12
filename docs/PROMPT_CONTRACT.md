# Prompt Contract

## Purpose
Keep model behavior consistent, auditable, and token-efficient across providers.

## Contract Layers (Every Call)
1. System policy: invariant rules and guardrails.
2. Operation prompt: one of `extract`, `query`, `plan`, `summarize`.
3. Retrieved context: compact, relevance-ranked facts.
4. User input: raw message or command.

## Operation Types
- `extract`: parse free-form text into structured update proposals.
- `query`: answer user questions from current stored state.
- `plan`: rank and explain next actions.
- `summarize`: compress recent activity into durable memory.
- `action_plan`: convert conversational input + grounding into executable actions.
- `action_critic`: review proposed actions for safety/correctness before execution.

## Output Requirements
- `extract` must return strict JSON with schema version.
- `extract` should include task action semantics where possible:
  - per-task `action`: `create|update|complete|archive|noop`
  - optional `target_task_id` when referencing existing tasks.
  - default preference: resolve against provided grounding candidates before creating near-duplicates.
- `query` returns concise text plus optional cited entity ids.
- `plan` returns ordered items and rationale fields.
- `summarize` returns compact facts and open questions.
- `action_plan` should return:
  - `intent` (`query|action`)
  - `scope` (`single|subset|all_open|all_matching`)
  - `actions[]` (typed operations with entity refs where possible)
  - `confidence` (0-1)
  - `needs_confirmation` (bool)
  - mutation actions should include `target_task_id` whenever referencing existing tasks.
- `action_critic` should return:
  - `approved` (bool)
  - `issues[]` (duplicates, conflicts, missing target refs, risky bulk updates)
  - optional `revised_actions[]`

## Validation and Retry
- Parse and validate outputs against schema.
- If invalid: retry with corrective instruction.
- If still invalid: fail safely and log for review.
- Executor does not infer meaning from raw user text; it only executes validated proposed actions.
- Executor enforces ID-first mutation policy: `update/complete/archive` without valid `target_task_id` are unresolved and must route to clarify mode.
- Fallback behavior is schema-recovery only; no heuristic broad writes.

## Versioning
- Each prompt template has `prompt_version`.
- Persist `provider` with each run.
- Persist `model` with each run.
- Persist `prompt_version` with each run.
- Persist token usage with each run.
- Persist latency with each run.
- Persist status with each run.

## Cost and Efficiency Controls
- Keep system policy short and stable.
- Prefer retrieval snippets over transcript replay.
- Provide compact extraction grounding (recent tasks/goals/problems) so model can update existing entities rather than inventing duplicates.
- Avoid LLM use for deterministic transforms.
- Track per-operation token and cost budgets.
- Prefer stable planner/critic prompts over growing heuristic code paths.
