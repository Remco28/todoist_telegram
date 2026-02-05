# Contracts v1

This folder contains provider-facing and backend-validation schemas for the first three LLM operations.

- `extract_response.schema.json`: LLM proposal for structured write updates.
- `query_response.schema.json`: LLM response shape for read-only conversational answers.
- `plan_response.schema.json`: LLM response shape for prioritized plan output.

Usage rules:
- LLM output must be parsed and validated against the matching schema.
- Invalid output is retried with corrective instruction.
- Backend writes are allowed only from validated `extract` output.
