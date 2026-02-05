# Todoist MCP Server — Debugging & Integration Summary

This doc captures **what was wrong**, **how it was fixed**, and **how to keep it working** when integrating a Flask-based MCP server with `gemini-cli` to control Todoist.

---

## Architecture

```
gemini-cli (MCP client)
      ⇅ JSON-RPC 2.0 over HTTP
Flask MCP server (this project)
      ⇅ HTTPS REST
Todoist API
```

---

## Key Fixes (In Order of Discovery)

1. **Path & Method Mismatch → 404**
   - **Issue**: Server only implemented `POST /mcp`. Some clients probe `/`, `/mcp/`, or do `GET` health checks first.
   - **Fix**: Accept **POST** at `"/"`, `"/mcp"`, `"/mcp/"` and **GET** health at the same paths. Add 404/405 handlers for visibility.

2. **Notifications Handling (JSON-RPC)**
   - **Issue**: `notifications/initialized` is a **notification** (no `id`). Returning a JSON body and/or 404 confuses the client.
   - **Fix**: For any request **without** `id`, return **HTTP 204 No Content** with an **empty body**. Log and ignore.

3. **HTTP Status for JSON-RPC Errors**
   - **Issue**: Returning transport errors (HTTP 4xx/5xx) for JSON-RPC failures caused the client to abort.
   - **Fix**: Always return **HTTP 200** for JSON-RPC responses (success **or** error). Put errors in the JSON body:
     ```json
     {"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not found"}}
     ```

4. **Capabilities & Instructions in `initialize`**
   - **Issue**: Server replied with `"capabilities": {}` and no `instructions`. Clients then assume no features or fail validation.
   - **Fix**: Include realistic capabilities and a non-null instructions string:
     ```json
     "capabilities": {
       "logging": {},
       "tools": { "listChanged": true },
       "resources": { "listChanged": true },
       "prompts": { "listChanged": true }
     },
     "instructions": "Todoist MCP: ..."
     ```

5. **Method Name Variants**
   - **Issue**: Different clients use different names. MCP-style namespaced vs. camelCase legacy.
   - **Fix**: Support both:
     - `initialize`, `tools/list`, `tools/call`
     - `listTools`, `callTool`

6. **`tools/list` Schema Shape**
   - **Issue**: Server returned `parameters`; MCP expects **`inputSchema`** with a JSON Schema.
   - **Fix**: Convert each tool to:
     ```json
     {
       "name": "create_task",
       "title": "Create Task",
       "description": "Create a new task or subtask.",
       "inputSchema": {
         "$schema": "https://json-schema.org/draft/2020-12/schema",
         "type": "object",
         "properties": { ... },
         "required": ["content"]
       }
     }
     ```

7. **Tool Result Payload Shape**
   - **Issue**: Returned `{"type":"json","data": ...}` inside `result.content`. Some clients ignore unknown content types.
   - **Fix**: Return **structured** JSON in `result.structuredContent` **and** a **text** fallback:
     ```json
     {
       "jsonrpc": "2.0",
       "id": 2,
       "result": {
         "content": [{ "type": "text", "text": "<stringified JSON>" }],
         "structuredContent": { "items": [ /* Todoist tasks */ ] },
         "isError": false
       }
     }
     ```
     - When the underlying result is a list (e.g., tasks), wrap it as an **object** (e.g., `{ "items": [...] }`).

8. **Robustness for Common Probes**
   - **Issue**: Some clients call `resources/list` and `prompts/list` even if you don’t advertise them.
   - **Fix**: Implement stubs returning empty lists:
     - `resources/list` → `{ "resources": [] }`
     - `prompts/list` → `{ "prompts": [] }`

9. **Content-Type Tolerance**
   - **Fix**: Accept `application/json`, `text/plain`, or empty `Content-Type` and still attempt to parse JSON. Return 415 for other types.

10. **Operational Logging & Safety**
    - **Fixes**:
      - Request/response logging to **stdout** and a rotating file `mcp_server.log`.
      - Mask secrets in logs (e.g., `3fb3...44cd`).
      - Add `timeout=15` to all Todoist HTTP calls.
      - Use consistent error translation from `requests` exceptions to JSON-RPC errors.

---

## Minimal Behavior Checklist (Server-Side)

- [x] **Routes**: `POST /`, `/mcp`, `/mcp/` + `GET` health on same paths.
- [x] **Initialize**: Echo client’s `protocolVersion` if present; return capabilities + `instructions`.
- [x] **Notifications**: `id == null` → **204** with **no body**.
- [x] **Tools**:
  - `tools/list` → tools array with `{name, title, description, inputSchema}`.
  - `tools/call` → use `{name, arguments}` (accept legacy `{toolName, parameters}` too).
  - Response includes `structuredContent` (object) + `content:[{type:"text"}]`.
- [x] **Errors**: JSON-RPC error envelope with HTTP **200**.
- [x] **Extras**: Empty `resources/list`, `prompts/list` to satisfy probing clients.
- [x] **Logging**: Request/response, token masking, timeouts.

---

## Testing Snippets

### PowerShell
```powershell
# Initialize
$init = '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"gemini-cli-mcp-client","version":"0.0.1"}}}'
Invoke-WebRequest http://127.0.0.1:8000/mcp -Method POST -ContentType "application/json" -Body $init

# Notification (should be 204, empty body)
$note = '{"jsonrpc":"2.0","method":"notifications/initialized"}'
Invoke-WebRequest http://127.0.0.1:8000/mcp -Method POST -ContentType "application/json" -Body $note

# List tools (MCP)
$tools = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
Invoke-WebRequest http://127.0.0.1:8000/mcp -Method POST -ContentType "application/json" -Body $tools

# Call get_active_tasks (MCP)
$call = '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_active_tasks","arguments":{}}}'
Invoke-WebRequest http://127.0.0.1:8000/mcp -Method POST -ContentType "application/json" -Body $call
```

### curl
```bash
curl -s http://127.0.0.1:8000/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"gemini-cli-mcp-client","version":"0.0.1"}}}' | jq

curl -s http://127.0.0.1:8000/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' -i

curl -s http://127.0.0.1:8000/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq

curl -s http://127.0.0.1:8000/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_active_tasks","arguments":{}}}' | jq
```

---

## Common Symptoms → Fix Map

| Symptom | Likely Cause | Fix |
|---|---|---|
| `404 NOT FOUND` right after start | Client POSTed to `/` or `/mcp/` | Add routes for `/`, `/mcp`, `/mcp/` |
| Client sends `notifications/initialized` then fails | Server returned JSON or 4xx | Return **204** with empty body for notifications |
| Client stops after `initialize` | Missing capabilities or `instructions` | Add realistic `capabilities` and `instructions` string |
| `tools/list` returns but client won’t call | Tools use `parameters` instead of `inputSchema` | Rename to `inputSchema` and include JSON Schema |
| Client says it “can’t retrieve tasks” despite 200 | `result.content` uses unsupported type (`json`) | Use `structuredContent` + `content:[{type:"text"}]` |
| Random 400/500s during calls | Propagated Todoist/network errors | Catch `requests` exceptions; map to JSON-RPC error body with HTTP 200 |
| Token printed in logs | Logging secrets directly | Mask tokens and rotate log files |

---

## Production Hardening (Recommended)

- Remove default token; **require** `TODOIST_TOKEN`.
- Add **rate limiting** or a simple auth gate if exposing beyond localhost.
- Validate tool parameters against `inputSchema` before calling Todoist.
- Normalize Todoist list results into a consistent object (e.g., `{items:[...]}`) across tools.
- Add **outputSchema** (optional) for stricter clients.
- Consider structured logging (JSON lines) and metrics counters for tool calls.
- Handle **Todoist 429** with basic backoff (respect `Retry-After`).

---

## Implementation Notes (Server)

- Accept JSON from `application/json`, `text/plain`, or empty `Content-Type` (some clients send plain text JSON).
- Always attempt `json.loads(body)` with proper exception handling; on failure, return JSON-RPC parse error (`-32700`) with HTTP 200.
- Prefer **POST** for JSON-RPC; `GET` only for health checks.
- Use request/response logging with body previews (cap at reasonable length, e.g., 2KB).

---

## Next Steps / Extensions

- Add Todoist **projects**/**sections** tools and `resources/list` items that describe them.
- Provide **prompt templates** for common actions (e.g., “Summarize today’s tasks by project”). 
- Add **batch** operations (close many tasks, relabel, reprioritize).
- Implement **outputSchema** and per-tool instructions for richer UIs.

---

## Files Mentioned

- `todomcp_debug5.py` — latest debug server (structuredContent + text fallback, inputSchema, stubs, logging).
- `mcp_server.log` — rotating request/response logs (path can be overridden with `MCP_LOG_PATH`).

---

## Quick Start

```powershell
$env:TODOIST_TOKEN = "<your real token>"
python .\todomcp_debug5.py
```

If something breaks, check **`mcp_server.log`** and the console. The log shows exactly which method/path the client called and what was returned.

---

This doc is designed so another engineer or AI can continue the work with minimal context.
