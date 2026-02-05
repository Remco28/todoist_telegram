# Where We Left Off

Status
- Chosen path: DIY motivated task system (Tasks + Problems + optional Goals + Why) designed for LLM control.
- Docs drafted: domain model, API/MCP design, storage/sync, LLM integration, flows, security, roadmap, LLM features.
- No coding yet — planning only.

Decisions So Far
- Motivation-centric: each task can have a short `why`; Problems aggregate actions and momentum.
- Token efficiency first: summaries, small default field sets, limit/paging, optional handles.
- Local-first: start on WSL; cross-device later via sync folder or $4 VPS if needed.

Open Questions (to confirm next session)
- Goals in MVP: include now or later? (We can start with Problems + Labels and add Goals next.)
- Default categories: financial, health, family, stress — add/remove?
- Motivation model: single `why` per task vs lightweight journal entries as well?
- Impact scale: keep 0–5 subjective impact for progress heuristics?
- MVP LLM features: pick top 3–5 (recommend: Problem Review, Action Suggestions, Smart Reschedule, Next Action Rewrite, Label Normalization).

Suggested First Actions When You Return
- Confirm MVP LLM features and defaults (categories, impact, summary field set).
- Choose storage default (recommend SQLite) and cross-device approach (sync folder vs VPS later).
- Then we’ll scaffold the schema and stub tools matching the docs (still minimal, token-lean outputs).

