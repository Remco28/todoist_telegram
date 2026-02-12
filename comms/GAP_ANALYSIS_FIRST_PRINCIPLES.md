# Gap Analysis: First Principles vs. Implementation
**Date:** 2026-02-11
**Ref:** Architect's First Principles Review

## Objective
Align the current `todoist_mcp` codebase with the Architect's 8 core principles for correctness, predictability, simplicity, and cost.

## Status Summary
- **Aligned:** 5/8 principles are largely met by recent phases (11, 14).
- **Partial:** 2/8 principles are partially met but rely on "legacy" fallbacks.
- **Gap:** 1/8 principles (ID-First Updates) is currently violated by design.

## Detailed Analysis

### 1. Split Understanding from Execution
- **Principle:** Interpreter -> Executor -> Responder. No direct write from model output.
- **Status:** **Partial**.
- **Gap:** `backend/api/main.py` retains a `extract_structured_updates` fallback path if the Planner fails. This path relies on regex/keyword heuristics (`_derive_bulk_complete_actions`, etc.) which bypass the strict "Intepreter" logic.
- **Recommendation:** Deprecate the heuristic fallback. If the Planner fails, return a "I didn't understand" response instead of guessing.

### 2. ID-First Task Updates (Critical)
- **Principle:** Never "best guess" update by title. Require explicit ID match.
- **Status:** **Violated**.
- **Gap:** `_apply_capture` in `backend/api/main.py` explicitly falls back to `Task.title_norm == title_norm` if `target_task_id` is missing. This causes "silent bad writes" (updating the wrong task).
- **Recommendation:** Remove the `title_norm` fallback for `update`, `complete`, and `archive` actions. Only allow `create` to rely on title. If an update lacks an ID, treat it as ambiguous.

### 3. Confidence/Authority Ladder
- **Principle:** Auto -> Draft -> Clarify.
- **Status:** **Partial**.
- **Gap:** We have "Auto" and "Draft". We lack "Clarify". Low-confidence plans currently result in a Draft, which puts the burden on the user to debug the bot's bad guess.
- **Recommendation:** Introduce a `confidence < 0.5` threshold that triggers a "Clarification Mode" (simple text question) instead of a Draft.

### 4. Memory as Products
- **Principle:** Factual vs. Task vs. Summary. Scoped by relevance.
- **Status:** **Aligned**.
- **Note:** `backend/common/memory.py` separates these concerns well. "Relevance" is currently heuristic (links + recency) rather than semantic (embeddings), which is acceptable for v1 Simplicity.

### 5. Reconciler Contract
- **Principle:** Local = Truth. Reconciler detects drift. Replay-safe.
- **Status:** **Aligned**.
- **Evidence:** Phase 11 `backend/worker/main.py` (`handle_todoist_reconcile`) implements this exactly.

### 6. Explainability Trace
- **Principle:** Log intent, candidates, choice, and confidence.
- **Status:** **Aligned**.
- **Evidence:** `EventLog` captures `telegram_action_planned` and `telegram_autopilot_decision` with full metadata.

### 7. Reduce Fragility (Preflight)
- **Principle:** Verify credentials on startup.
- **Status:** **Gap**.
- **Gap:** `/health/ready` checks network connectivity (TCP) but not application-level auth (HTTP 401). Invalid keys cause runtime errors.
- **Recommendation:** Create `ops/preflight.py` or add a `check_credentials` mode to `backend/api/main.py` to validate `LLM_API_KEY` and `TELEGRAM_BOT_TOKEN` on startup.

### 8. Cost Control
- **Principle:** Bounded context, cheaper models for simple tasks.
- **Status:** **Aligned**.
- **Evidence:** `common/config.py` allows per-operation model selection. `common/memory.py` enforces strict token budgets.

## Priority Action Plan
1.  **Safety:** Disable `title_norm` matching for existing task updates (Fixes #2).
2.  **Stability:** Implement startup credential preflight check (Fixes #7).
3.  **Cleanliness:** Remove legacy regex fallbacks in `api/main.py` (Fixes #1).
