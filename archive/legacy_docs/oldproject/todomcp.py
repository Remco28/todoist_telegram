import os
import json
import logging
from typing import Any, Dict, Optional

import requests
from flask import Flask, request, jsonify

# ---------------------------
# Config
# ---------------------------

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

TODOIST_TOKEN = os.getenv("TODOIST_TOKEN")
if not TODOIST_TOKEN:
    raise RuntimeError("TODOIST_TOKEN env var is required")

TODOIST_BASE_URL = "https://api.todoist.com/rest/v2/"
TODOIST_HEADERS = {
    "Authorization": f"Bearer {TODOIST_TOKEN}",
    "Content-Type": "application/json",
}

JSON_SCHEMA_URL = "https://json-schema.org/draft/2020-12/schema"

# ---------------------------
# Flask app & logging
# ---------------------------

app = Flask(__name__)
log = logging.getLogger("mcp")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------
# Tool definitions (MCP: inputSchema)
# ---------------------------

TOOLS = [
    {
        "name": "get_active_tasks",
        "title": "Get Active Tasks",
        "description": "Retrieve all active tasks, optionally filtered.",
        "inputSchema": {
            "$schema": JSON_SCHEMA_URL,
            "type": "object",
            "title": "Get Active Tasks Parameters",
            "description": "Parameters for retrieving active tasks.",
            "properties": {
                "label": {"type": "string", "description": "Label to filter tasks by."},
                "filter": {"type": "string", "description": "Custom filter string for tasks."}
            },
            "required": []
        }
    },
    {
        "name": "create_task",
        "title": "Create Task",
        "description": "Create a new task or subtask.",
        "inputSchema": {
            "$schema": JSON_SCHEMA_URL,
            "type": "object",
            "title": "Create Task Parameters",
            "description": "Parameters for creating a new task.",
            "properties": {
                "content": {"type": "string", "description": "The content of the task."},
                "description": {"type": "string", "description": "A detailed description of the task."},
                "labels": {"type": "array", "items": {"type": "string"}, "description": "Labels to apply to the task."},
                "priority": {"type": "integer", "description": "Priority 1-4 (4 highest)."},
                "due_string": {"type": "string", "description": "Human-friendly due date (e.g., 'today', 'next Monday')."},
                "parent_id": {"type": "string", "description": "Parent task ID if creating a subtask."}
            },
            "required": ["content"]
        }
    },
    {
        "name": "get_task",
        "title": "Get Task",
        "description": "Retrieve a single task by ID.",
        "inputSchema": {
            "$schema": JSON_SCHEMA_URL,
            "type": "object",
            "title": "Get Task Parameters",
            "description": "Parameters for retrieving a single task.",
            "properties": {"id": {"type": "string", "description": "The ID of the task to retrieve."}},
            "required": ["id"]
        }
    },
    {
        "name": "update_task",
        "title": "Update Task",
        "description": "Update an existing task.",
        "inputSchema": {
            "$schema": JSON_SCHEMA_URL,
            "type": "object",
            "title": "Update Task Parameters",
            "description": "Parameters for updating an existing task.",
            "properties": {
                "id": {"type": "string", "description": "The ID of the task to update."},
                "content": {"type": "string", "description": "New content."},
                "description": {"type": "string", "description": "New detailed description."},
                "labels": {"type": "array", "items": {"type": "string"}, "description": "New labels."},
                "priority": {"type": "integer", "description": "New priority 1-4 (4 highest)."},
                "due_string": {"type": "string", "description": "Human-friendly due date."}
            },
            "required": ["id"]
        }
    },
    {
        "name": "close_task",
        "title": "Close Task",
        "description": "Complete a task.",
        "inputSchema": {
            "$schema": JSON_SCHEMA_URL,
            "type": "object",
            "title": "Close Task Parameters",
            "description": "Parameters for completing a task.",
            "properties": {"id": {"type": "string", "description": "The ID of the task to close."}},
            "required": ["id"]
        }
    },
    {
        "name": "reopen_task",
        "title": "Reopen Task",
        "description": "Reopen a completed task.",
        "inputSchema": {
            "$schema": JSON_SCHEMA_URL,
            "type": "object",
            "title": "Reopen Task Parameters",
            "description": "Parameters for reopening a task.",
            "properties": {"id": {"type": "string", "description": "The ID of the task to reopen."}},
            "required": ["id"]
        }
    },
    {
        "name": "delete_task",
        "title": "Delete Task",
        "description": "Delete a task.",
        "inputSchema": {
            "$schema": JSON_SCHEMA_URL,
            "type": "object",
            "title": "Delete Task Parameters",
            "description": "Parameters for deleting a task.",
            "properties": {"id": {"type": "string", "description": "The ID of the task to delete."}},
            "required": ["id"]
        }
    },
    {
        "name": "get_all_labels",
        "title": "Get All Labels",
        "description": "Retrieve all labels.",
        "inputSchema": {"$schema": JSON_SCHEMA_URL, "type": "object", "title": "Get All Labels Parameters", "description": "Parameters for retrieving all labels.", "properties": {}, "required": []}
    },
    {
        "name": "create_label",
        "title": "Create Label",
        "description": "Create a new label.",
        "inputSchema": {
            "$schema": JSON_SCHEMA_URL,
            "type": "object",
            "title": "Create Label Parameters",
            "description": "Parameters for creating a new label.",
            "properties": {
                "name": {"type": "string", "description": "The name of the label."},
                "order": {"type": "integer", "description": "Sort order in the UI."},
                "color": {"type": "string", "description": "Label color."},
                "favorite": {"type": "boolean", "description": "Whether the label is a favorite."}
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_label",
        "title": "Update Label",
        "description": "Update an existing label.",
        "inputSchema": {
            "$schema": JSON_SCHEMA_URL,
            "type": "object",
            "title": "Update Label Parameters",
            "description": "Parameters for updating an existing label.",
            "properties": {
                "id": {"type": "string", "description": "The ID of the label to update."},
                "name": {"type": "string", "description": "New name."},
                "order": {"type": "integer", "description": "New sort order."},
                "color": {"type": "string", "description": "New color."},
                "favorite": {"type": "boolean", "description": "Whether the label is a favorite."}
            },
            "required": ["id"]
        }
    },
    {
        "name": "delete_label",
        "title": "Delete Label",
        "description": "Delete a label.",
        "inputSchema": {
            "$schema": JSON_SCHEMA_URL,
            "type": "object",
            "title": "Delete Label Parameters",
            "description": "Parameters for deleting a label.",
            "properties": {"id": {"type": "string", "description": "The ID of the label to delete."}},
            "required": ["id"]
        }
    }
]

# ---------------------------
# Todoist forwarding
# ---------------------------

def _todoist_request(method: str, path: str, params: Optional[Dict[str, Any]] = None, json_data: Optional[Dict[str, Any]] = None):
    url = TODOIST_BASE_URL + path
    try:
        if method == "GET":
            resp = requests.get(url, headers=TODOIST_HEADERS, params=params, timeout=15)
        elif method == "POST":
            resp = requests.post(url, headers=TODOIST_HEADERS, json=json_data, timeout=15)
        elif method == "DELETE":
            resp = requests.delete(url, headers=TODOIST_HEADERS, timeout=15)
        else:
            raise ValueError(f"Unsupported method: {method}")
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return None
    except requests.exceptions.RequestException as e:
        # Map network/API errors into JSON-RPC error path
        raise ValueError(str(e)) from e

def execute_tool(tool_name: str, params: Dict[str, Any]):
    if tool_name == "get_active_tasks":
        return _todoist_request("GET", "tasks", params=params)
    if tool_name == "create_task":
        return _todoist_request("POST", "tasks", json_data=params)
    if tool_name == "get_task":
        return _todoist_request("GET", f"tasks/{params['id']}")
    if tool_name == "update_task":
        p = dict(params)
        task_id = p.pop("id")
        return _todoist_request("POST", f"tasks/{task_id}", json_data=p)
    if tool_name == "close_task":
        return _todoist_request("POST", f"tasks/{params['id']}/close")
    if tool_name == "reopen_task":
        return _todoist_request("POST", f"tasks/{params['id']}/reopen")
    if tool_name == "delete_task":
        return _todoist_request("DELETE", f"tasks/{params['id']}")
    if tool_name == "get_all_labels":
        return _todoist_request("GET", "labels")
    if tool_name == "create_label":
        return _todoist_request("POST", "labels", json_data=params)
    if tool_name == "update_label":
        p = dict(params)
        lid = p.pop("id")
        return _todoist_request("POST", f"labels/{lid}", json_data=p)
    if tool_name == "delete_label":
        return _todoist_request("DELETE", f"labels/{params['id']}")
    raise ValueError(f"Unknown tool: {tool_name}")

# ---------------------------
# JSON helpers
# ---------------------------

def _json_ok(id_val: Any, result_obj: Dict[str, Any]):
    return jsonify({"jsonrpc": "2.0", "id": id_val, "result": result_obj}), 200

def _json_error(code: int, message: str, id_val: Any):
    # Always HTTP 200 for JSON-RPC layer
    return jsonify({"jsonrpc": "2.0", "id": id_val, "error": {"code": code, "message": message}}), 200

def _pack_tool_result(result: Any):
    # structuredContent must be an object; wrap lists
    if result is None:
        structured = {"ok": True}
        text = "OK"
    elif isinstance(result, dict):
        structured = result
        text = json.dumps(result, ensure_ascii=False)
    else:
        structured = {"items": result}
        text = json.dumps(result, ensure_ascii=False)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": False
    }

# ---------------------------
# Handlers
# ---------------------------

@app.route("/", methods=["GET"])
@app.route("/mcp", methods=["GET"])
@app.route("/mcp/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "hint": "POST JSON-RPC 2.0 to /mcp (or /)",
    }), 200

def _handle_jsonrpc(data: Dict[str, Any]):
    method = data.get("method")
    rpc_id = data.get("id", None)
    params = data.get("params", {}) or {}

    # Notifications (no id) -> 204 with empty body
    if rpc_id is None:
        # Accept common notifications
        return ("", 204)

    # initialize
    if method == "initialize":
        requested = params.get("protocolVersion")
        proto = requested or "2025-03-26"
        caps = {
            "logging": {},
            "tools": {"listChanged": True},
            "resources": {"listChanged": True},
            "prompts": {"listChanged": True},
        }
        result = {
            "protocolVersion": proto,
            "capabilities": caps,
            "serverInfo": {"name": "todoist_mcp", "version": "1.0.0"},
            "instructions": "Todoist MCP: use tools/list to discover tools, then tools/call with {name, arguments}.",
        }
        return _json_ok(rpc_id, result)

    # tools/list
    if method in ("tools/list", "listTools"):
        return _json_ok(rpc_id, {"tools": TOOLS})

    # tools/call
    if method in ("tools/call", "callTool"):
        try:
            tool_name = params.get("name") or params.get("toolName") or params.get("tool_name")
            tool_params = params.get("arguments") or params.get("parameters") or {}
            result = execute_tool(tool_name, tool_params)
            return _json_ok(rpc_id, _pack_tool_result(result))
        except ValueError as e:
            return _json_error(-32000, str(e), rpc_id)

    # Optional: resources & prompts (empty)
    if method == "resources/list":
        return _json_ok(rpc_id, {"resources": []})
    if method == "prompts/list":
        return _json_ok(rpc_id, {"prompts": []})

    # Unknown method
    return _json_error(-32601, f"Method not found: {method}", rpc_id)

def _handle_legacy(data: Dict[str, Any]):
    action = data.get("action")
    if action == "list_tools":
        return jsonify({"tools": TOOLS}), 200
    if action == "call_tool":
        try:
            result = execute_tool(data.get("tool_name"), data.get("parameters", {}) or {})
            return jsonify({"result": result}), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 200
    return jsonify({"error": "Invalid request"}), 200

def _handle_request():
    ct = (request.content_type or "").lower()
    raw = request.get_data(as_text=True)

    # Parse JSON for application/json, text/plain, or missing content-type
    if ("application/json" in ct) or ("text/plain" in ct) or (ct == ""):
        try:
            data = json.loads(raw) if raw else {}
        except Exception as e:
            # Parse error (-32700)
            return _json_error(-32700, f"Parse error: {e}", None)
    else:
        return jsonify({"error": "Unsupported Content-Type", "content_type": ct}), 415

    # JSON-RPC?
    if isinstance(data, dict) and data.get("jsonrpc") == "2.0":
        return _handle_jsonrpc(data)

    # Legacy
    return _handle_legacy(data)

@app.route("/", methods=["POST"])
@app.route("/mcp", methods=["POST"])
@app.route("/mcp/", methods=["POST"])
def mcp_entry():
    return _handle_request()

# ---------------------------
# Main
# ---------------------------

if __name__ == "__main__":
    log.info(f"Starting MCP server on http://{MCP_HOST}:{MCP_PORT}")
    app.run(host=MCP_HOST, port=MCP_PORT, debug=False, threaded=True)
