# Legacy Document Review

Purpose: decide what to keep, merge, archive, or discard from legacy docs now stored under `archive/legacy_docs/`.

## Decision Rules
- Keep: still accurate and directly useful for v1 delivery.
- Merge: useful content exists, but should move into canonical `docs/`.
- Archive: historical reference only; keep out of active docs path.
- Discard: obsolete/noise or unrelated.

## Recommended Disposition

### Keep (for now)
- `archive/legacy_docs/diy_todo/DOMAIN_MODEL.md`
  - Reason: core entity definitions still align with current direction.
- `archive/legacy_docs/diy_todo/API_MCP_DESIGN.md`
  - Reason: strong tool-shape guidance and token-efficiency ideas.
- `archive/legacy_docs/diy_todo/SECURITY_PRIVACY.md`
  - Reason: still relevant operational baseline for hosted deployment.
- `archive/legacy_docs/oldproject/Todoist_MCP_Summary.md`
  - Reason: useful if/when downstream Todoist sync MCP compatibility is revisited.

### Merge into canonical docs, then archive originals
- `archive/legacy_docs/diy_todo/LLM_FEATURES.md`
  - Merge target: `docs/ARCHITECTURE_V1.md` and `docs/EXECUTION_PLAN.md`.
- `archive/legacy_docs/diy_todo/LLM_INTEGRATION.md`
  - Merge target: `docs/PROMPT_CONTRACT.md` and `docs/MEMORY_AND_SESSION_POLICY.md`.
- `archive/legacy_docs/diy_todo/FLOWS.md`
  - Merge target: future `docs/TELEGRAM_FLOWS_V1.md`.
- `archive/legacy_docs/diy_todo/ROADMAP.md`
  - Merge target: `docs/PHASES.md`.
- `archive/legacy_docs/diy_todo/NEXT_STEPS.md`
  - Merge target: `docs/EXECUTION_PLAN.md`.
- `archive/legacy_docs/diy_todo/README.md`
  - Merge target: `docs/PROJECT_DIRECTION.md` and `docs/README.md`.

### Archive (historical, not active)
- `archive/legacy_docs/oldproject/todomcp.py`
- `archive/legacy_docs/oldproject/changelog.md`
- `archive/legacy_docs/oldproject/gemini.md`
- `archive/legacy_docs/oldproject/gemini old.md`
- `archive/legacy_docs/oldproject/settings.json`
- `archive/legacy_docs/oldproject/Environmental Variables.md`
  - Reason: old prototype and troubleshooting history; not source of truth for new architecture.

### Discard (or move outside project docs)
- `archive/legacy_docs/oldproject/reno_ideas.md`
  - Reason: unrelated renovation checklist not part of system architecture.
  - Status: removed during cleanup.
- `archive/legacy_docs/oldproject/sshpowershell.md`
  - Reason: unrelated shell setup instructions; not project-specific.
  - Status: removed during cleanup.

## Security Cleanup Notes
- `archive/legacy_docs/oldproject/todomcp_debug5.py` had a hardcoded token default and was removed during cleanup.
- `archive/legacy_docs/oldproject/mcp_server.log` contained operational traces and was removed during cleanup.

## Proposed Next Cleanup Steps
1. Merge high-value content from `archive/legacy_docs/diy_todo/` files into canonical `docs/`.
2. Delete unrelated files after one final review pass.
3. Keep only `docs/` as canonical project documentation.
