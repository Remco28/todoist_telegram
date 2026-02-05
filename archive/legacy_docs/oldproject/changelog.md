# Changelog

## 2025-07-25

### Gemini.md Updates for Agent Behavior and MCP Interaction

- **Removed Confirmation Prompts:** Modified `gemini.md` to remove instructions requiring the agent to confirm actions with the user, aligning with the new directive for direct execution.
- **Refined Tool Parameter Descriptions:** Updated `gemini.md` to remove `project_id` from the descriptions of `get_active_tasks` and `create_task` parameters, reinforcing the agent's focus on tasks and labels only.
- **Documented MCP Request Format:** Added a new section to `gemini.md` detailing the expected JSON structure for `call_tool` requests to the MCP server. This aims to improve the accuracy of agent-generated requests and reduce `400 Bad Request` errors.

### Troubleshooting MCP Server Connection

- **Initial State:** User reported that the MCP server was not accessible in the Gemini CLI. The server had been named `default` in `settings.json` as part of a previous troubleshooting attempt.

- **Step 1: Investigation:**
    - Reviewed `settings.json`: Confirmed the server was named `default` and configured to use `http://localhost:8000/mcp`.
    - Reviewed `todomcp.py`: Confirmed the Flask server was correctly set up to listen on port 8000 and handle requests at the `/mcp` endpoint.
    - User verified that the server was running and responding correctly to direct HTTP requests.

- **Step 2: Hypothesis & Correction:**
    - Hypothesized that using the reserved name "default" for the MCP server was causing a name conflict with the CLI's built-in `default_api`.
    - Modified `settings.json` to rename the server from `default` to `todoist_mcp`.

- **Step 3: Documentation Review:**
    - User provided a new `mcp_server_setup.md` file.
    - Reviewed the documentation and confirmed the `settings.json` configuration for an HTTP-based server was correct.

- **Step 4: Next Steps:**
    - Advised user to restart the Gemini CLI for the changes to `settings.json` to take effect.
    - Recommended using the `/mcp` command to check the connection status after the restart.

- **Step 5: Relocating `settings.json`:**
    - Identified that `settings.json` was not in the expected `.gemini` subdirectory within the project root.
    - Explained the purpose of the `.gemini` directory for project-specific configurations and CLI discoverability.
    - User manually created the `.gemini` directory and moved `settings.json` into it.
    - Advised user to restart the Gemini CLI again and re-run `/mcp`.

### MCP Server Tool Definition Refinement

- **Issue:** MCP server detected but no tools were being cached by the Gemini CLI, suggesting a schema validation issue.

- **Action 1: Removed Duplicate Code:**
    - Removed duplicate `TODOIST_BASE_URL` and `headers` definitions in `todomcp.py` to clean up the code and potentially force re-evaluation of tool definitions.

- **Action 2: Enhanced Tool Schemas:**
    - Added `title` and `description` fields to the `parameters` object and to each property within the parameters for all tools defined in `todomcp.py` (`get_active_tasks`, `create_task`, `get_task`, `update_task`, `close_task`, `reopen_task`, `delete_task`, `get_all_labels`, `create_label`, `update_label`, `delete_label`). This provides more verbose and explicit schema definitions, which can improve compatibility with the Gemini CLI's tool validation process.

- **Action 3: Removed Project/Section IDs from Tool Definitions:**
    - Removed `project_id` and `section_id` from the `get_active_tasks` tool definition and `project_id` from the `create_task` tool definition in `todomcp.py` to align with the agent's focus on tasks and labels only.

- **Action 4: Added `includeTools` to `settings.json`:**
    - Added the `includeTools` array to both `settings.json` files, explicitly listing all available tools to ensure the Gemini CLI correctly loads them from the MCP server.

- **Next Steps:** Advised user to restart the Gemini CLI and check the `/mcp` status to see if tools are now cached.