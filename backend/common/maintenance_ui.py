import json
from typing import Optional


_MAINTENANCE_UI_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Local Assistant Workbench</title>
  <style>
    :root {
      --bg: #f3efe4;
      --panel: #fffaf0;
      --ink: #1f2a1f;
      --muted: #586256;
      --line: #d7cfbe;
      --accent: #1f6f50;
      --accent-soft: #dceee5;
      --warn: #8c5a19;
      --danger: #8f2f2f;
      --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      --serif: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(31,111,80,0.10), transparent 35%),
        linear-gradient(180deg, #f7f2e8 0%, var(--bg) 100%);
      color: var(--ink);
      font-family: var(--serif);
    }
    .shell {
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px 20px 64px;
    }
    .hero {
      display: grid;
      gap: 12px;
      margin-bottom: 22px;
    }
    .eyebrow {
      font: 700 12px/1.2 var(--mono);
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--accent);
    }
    h1 {
      margin: 0;
      font-size: clamp(2rem, 4vw, 3.4rem);
      line-height: 0.98;
      letter-spacing: -0.03em;
    }
    .subcopy {
      max-width: 780px;
      color: var(--muted);
      font-size: 1.02rem;
      line-height: 1.5;
    }
    .notice {
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.62);
      border-radius: 18px;
      padding: 14px 16px;
      color: var(--muted);
    }
    .layout {
      display: grid;
      gap: 18px;
      grid-template-columns: 320px minmax(0, 1fr);
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px;
      box-shadow: 0 20px 50px rgba(42, 39, 34, 0.06);
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: 1.05rem;
      letter-spacing: -0.01em;
    }
    .mode-toggle {
      display: inline-flex;
      gap: 8px;
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,0.7);
    }
    .mode-toggle button {
      padding: 8px 12px;
      background: transparent;
      color: var(--muted);
    }
    .mode-toggle button.active {
      background: var(--accent);
      color: #fff;
    }
    .stack {
      display: grid;
      gap: 12px;
    }
    label {
      display: grid;
      gap: 6px;
      font-size: 0.9rem;
      color: var(--muted);
    }
    input, select, textarea, button {
      font: inherit;
    }
    input, select, textarea {
      width: 100%;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
    }
    textarea {
      min-height: 88px;
      resize: vertical;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 10px 14px;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
      transition: transform 120ms ease, opacity 120ms ease;
    }
    button:hover { transform: translateY(-1px); }
    button.secondary {
      background: var(--accent-soft);
      color: var(--accent);
    }
    button.warn {
      background: #f5e6ce;
      color: var(--warn);
    }
    button.danger {
      background: #f6dddd;
      color: var(--danger);
    }
    .toolbar {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 14px;
    }
    .kpis {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin-bottom: 16px;
    }
    .kpi {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
      background: rgba(255,255,255,0.6);
    }
    .kpi .label {
      color: var(--muted);
      font-size: 0.82rem;
      margin-bottom: 4px;
    }
    .kpi .value {
      font-size: 1.5rem;
      font-weight: 700;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 10px;
    }
    .section-head p {
      margin: 0;
      color: var(--muted);
      font-size: 0.9rem;
    }
    .filter-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 14px;
      align-items: end;
    }
    .filter-actions {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
    }
    .filter-actions button {
      white-space: nowrap;
    }
    .items {
      display: grid;
      gap: 12px;
    }
    .item {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      background: rgba(255,255,255,0.7);
    }
    .item-title {
      font-size: 1.08rem;
      margin: 0 0 6px;
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
    }
    .pill {
      border-radius: 999px;
      padding: 4px 9px;
      font: 700 11px/1.1 var(--mono);
      letter-spacing: 0.04em;
      text-transform: uppercase;
      background: #f2eee3;
      color: var(--muted);
    }
    .notes {
      margin: 0 0 10px;
      color: var(--muted);
      white-space: pre-wrap;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .tree-section {
      display: grid;
      gap: 10px;
    }
    .tree-section + .tree-section {
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid rgba(215, 207, 190, 0.7);
    }
    .tree-section-title {
      margin: 0;
      font-size: 0.96rem;
      color: var(--muted);
      letter-spacing: 0.01em;
    }
    .tree-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
    }
    .tree-label {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }
    .tree-label .item-title {
      margin: 0;
    }
    .tree-toggle {
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--accent);
      font: 700 12px/1.2 var(--mono);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .tree-toggle:hover {
      transform: none;
      opacity: 0.82;
    }
    .tree-children {
      display: grid;
      gap: 10px;
      margin-top: 10px;
      padding-left: 16px;
      border-left: 1px solid rgba(215, 207, 190, 0.8);
    }
    .tree-children.collapsed {
      display: none;
    }
    .today-panel {
      display: grid;
      gap: 12px;
      margin-bottom: 16px;
    }
    .today-columns {
      display: grid;
      gap: 12px;
      grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.9fr);
    }
    .today-column {
      display: grid;
      gap: 10px;
    }
    .today-column h3 {
      margin: 0;
      font-size: 0.96rem;
      color: var(--muted);
    }
    .today-list {
      display: grid;
      gap: 10px;
    }
    .today-item .item-title {
      margin-bottom: 4px;
    }
    .today-item .actions {
      margin-top: 10px;
    }
    .today-item .notes {
      margin-bottom: 8px;
    }
    .today-panel.is-empty {
      display: none;
    }
    .toast-stack {
      position: fixed;
      right: 18px;
      bottom: 18px;
      z-index: 20;
      display: grid;
      gap: 10px;
      width: min(360px, calc(100vw - 24px));
    }
    .toast {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255, 250, 240, 0.98);
      box-shadow: 0 14px 30px rgba(42, 39, 34, 0.12);
      padding: 12px 14px;
      display: grid;
      gap: 8px;
    }
    .toast strong {
      display: block;
      margin: 0;
      font-size: 0.96rem;
    }
    .toast .toast-actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
    }
    .toast .toast-actions button {
      padding: 8px 12px;
    }
    .maintenance-summary {
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px dashed var(--line);
      background: rgba(255,255,255,0.55);
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.4;
    }
    .maintenance-only {
      display: block;
    }
    body[data-mode="user"] .maintenance-only {
      display: none !important;
    }
    body[data-mode="maintenance"] .user-only {
      display: none !important;
    }
    .status {
      min-height: 24px;
      color: var(--muted);
      margin-top: 10px;
      font-size: 0.9rem;
    }
    .empty {
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 16px;
      padding: 18px;
      text-align: center;
    }
    code {
      font-family: var(--mono);
      background: rgba(255,255,255,0.8);
      padding: 2px 4px;
      border-radius: 6px;
    }
    @media (max-width: 960px) {
      .layout {
        grid-template-columns: 1fr;
      }
      .toolbar, .kpis, .filter-grid, .today-columns {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    @media (max-width: 640px) {
      .shell {
        padding: 18px 14px 42px;
      }
      .toolbar, .kpis, .filter-grid, .today-columns {
        grid-template-columns: 1fr;
      }
      .filter-actions {
        justify-content: stretch;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="eyebrow">Maintenance Surface</div>
      <h1>Local Assistant Workbench</h1>
      <div class="subcopy">
        Lightweight review and cleanup interface for the local-first assistant. Telegram stays primary; this page is for direct edits,
        inspecting reminders, and recovering from odd model behavior without touching raw database state.
      </div>
      <div class="notice">
        Open this page with <code>?token=&lt;your_api_token&gt;</code>. The token stays in your browser and is only used to call the existing API.
      </div>
    </section>

    <div class="layout">
      <aside class="stack">
        <section class="panel">
          <h2>Session</h2>
          <div class="stack">
            <div>
              <div class="mode-toggle" role="tablist" aria-label="Workbench mode">
                <button class="secondary" id="mode-user-button" type="button" data-mode-toggle="user">User</button>
                <button class="secondary" id="mode-maintenance-button" type="button" data-mode-toggle="maintenance">Maintenance</button>
              </div>
            </div>
            <label>
              API token
              <input id="token-input" type="password" placeholder="test_token or real bearer token" />
            </label>
            <label>
              <span class="maintenance-only">Today plan chat id</span>
              <input class="maintenance-only" id="chat-id-input" type="text" placeholder="Optional; blank uses your latest Telegram session" />
            </label>
            <div class="maintenance-summary user-only">
              User mode keeps direct task management visible and hides maintenance controls like version history, manual creation, raw dispatch, and advanced Telegram context overrides.
            </div>
            <button id="refresh-button" type="button">Refresh</button>
          </div>
          <div class="status" id="session-status"></div>
        </section>

        <section class="panel maintenance-only">
          <h2>Create Work Item</h2>
          <div class="stack">
            <label>
              Title
              <input id="new-title" type="text" placeholder="Review payroll paperwork" />
            </label>
            <label>
              Kind
              <select id="new-kind">
                <option value="task">Task</option>
                <option value="subtask">Subtask</option>
                <option value="project">Project</option>
              </select>
            </label>
            <label>
              Parent work item id
              <input id="new-parent-id" type="text" placeholder="Optional parent for task/subtask" />
            </label>
            <label>
              Priority
              <select id="new-priority">
                <option value="">None</option>
                <option value="1">1</option>
                <option value="2">2</option>
                <option value="3">3</option>
                <option value="4">4</option>
              </select>
            </label>
            <label>
              Due at
              <input id="new-due-at" type="datetime-local" />
            </label>
            <label>
              Notes
              <textarea id="new-notes" placeholder="Optional detail or context"></textarea>
            </label>
            <button id="create-work-item-button" type="button">Create work item</button>
          </div>
        </section>

        <section class="panel maintenance-only">
          <h2>Create Reminder</h2>
          <div class="stack">
            <label>
              Title
              <input id="new-reminder-title" type="text" placeholder="Ping Patrick about 401k email" />
            </label>
            <label>
              Remind at
              <input id="new-reminder-at" type="datetime-local" />
            </label>
            <label>
              Recurrence
              <select id="new-reminder-recurrence">
                <option value="">One-off</option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="weekdays">Weekdays</option>
                <option value="monthly">Monthly</option>
              </select>
            </label>
            <label>
              Message
              <textarea id="new-reminder-message" placeholder="Optional reminder body"></textarea>
            </label>
            <label>
              Linked work item id
              <input id="new-reminder-work-item-id" type="text" placeholder="Optional work item to attach this reminder to" />
            </label>
            <button id="create-reminder-button" type="button">Create reminder</button>
          </div>
        </section>
      </aside>

      <main class="stack">
        <section class="panel">
          <div class="kpis">
            <div class="kpi">
              <div class="label">Open work items</div>
              <div class="value" id="kpi-open">-</div>
            </div>
            <div class="kpi">
              <div class="label">Urgent items</div>
              <div class="value" id="kpi-urgent">-</div>
            </div>
            <div class="kpi">
              <div class="label">Pending reminders</div>
              <div class="value" id="kpi-reminders">-</div>
            </div>
          </div>

          <div class="toolbar">
            <button class="secondary" id="load-today-button" type="button">Load today plan</button>
            <button class="secondary" id="load-urgent-button" type="button">Load urgent items</button>
            <button class="secondary" id="load-open-button" type="button">Open work items</button>
            <button class="warn maintenance-only" id="dispatch-reminders-button" type="button">Dispatch due reminders</button>
          </div>

          <div class="today-panel is-empty" id="today-panel">
            <div class="section-head">
              <div>
                <h2>Today</h2>
                <p>Separate from the main list so you can load the live plan without overwriting your broader view.</p>
              </div>
              <button class="secondary" id="clear-today-button" type="button">Clear today panel</button>
            </div>
            <div class="today-columns">
              <section class="today-column">
                <h3>Today plan</h3>
                <div class="today-list" id="today-plan-items"></div>
              </section>
              <section class="today-column">
                <h3>Due reminders</h3>
                <div class="today-list" id="today-plan-reminders"></div>
              </section>
            </div>
          </div>

          <div class="section-head">
            <div>
              <h2>Work Items</h2>
              <p>Fast maintenance layer over the canonical local-first store.</p>
            </div>
          </div>
          <div class="filter-grid">
            <label>
              Search
              <input id="search-filter" type="search" placeholder="Search title or notes" />
            </label>
            <label>
              Status
              <select id="status-filter">
                <option value="">All statuses</option>
                <option value="open">Open</option>
                <option value="blocked">Blocked</option>
                <option value="done">Done</option>
                <option value="archived">Archived</option>
              </select>
            </label>
            <label>
              Kind
              <select id="kind-filter">
                <option value="">All kinds</option>
                <option value="project">Project</option>
                <option value="task">Task</option>
                <option value="subtask">Subtask</option>
              </select>
            </label>
            <label>
              Due window
              <select id="due-filter">
                <option value="">Any date</option>
                <option value="overdue">Overdue</option>
                <option value="today">Due today</option>
                <option value="next7">Next 7 days</option>
                <option value="next14">Next 14 days</option>
                <option value="scheduled">Has a due date</option>
                <option value="unscheduled">No due date</option>
              </select>
            </label>
            <div class="filter-actions">
              <button class="secondary" id="reset-filters-button" type="button">Reset filters</button>
            </div>
          </div>
          <div class="items" id="work-items"></div>
        </section>

        <section class="panel">
          <div class="section-head">
            <div>
              <h2>Reminders</h2>
              <p>Pending and recent reminders tied to the assistant’s own scheduler.</p>
            </div>
          </div>
          <div class="items" id="reminders"></div>
        </section>

        <section class="panel maintenance-only">
          <div class="section-head">
            <div>
              <h2>Recent Changes</h2>
              <p>Read-only action history from the local-first audit trail.</p>
            </div>
          </div>
          <div class="items" id="history"></div>
        </section>

        <section class="panel maintenance-only">
          <div class="section-head">
            <div>
              <h2>Version Details</h2>
              <p>Inspect recent snapshots for a selected work item or reminder.</p>
            </div>
          </div>
          <div class="items" id="versions"></div>
        </section>
      </main>
    </div>
  </div>
  <div class="toast-stack" id="toast-stack" aria-live="polite" aria-atomic="true"></div>

  <script>
    const initialToken = __TOKEN_JSON__;
    const tokenInput = document.getElementById("token-input");
    const chatIdInput = document.getElementById("chat-id-input");
    const searchFilter = document.getElementById("search-filter");
    const statusFilter = document.getElementById("status-filter");
    const kindFilter = document.getElementById("kind-filter");
    const dueFilter = document.getElementById("due-filter");
    const sessionStatus = document.getElementById("session-status");
    const workItemsEl = document.getElementById("work-items");
    const remindersEl = document.getElementById("reminders");
    const historyEl = document.getElementById("history");
    const versionsEl = document.getElementById("versions");
    const todayPanel = document.getElementById("today-panel");
    const todayPlanItemsEl = document.getElementById("today-plan-items");
    const todayPlanRemindersEl = document.getElementById("today-plan-reminders");
    const toastStack = document.getElementById("toast-stack");
    const kpiOpen = document.getElementById("kpi-open");
    const kpiUrgent = document.getElementById("kpi-urgent");
    const kpiReminders = document.getElementById("kpi-reminders");
    const modeButtons = Array.from(document.querySelectorAll("button[data-mode-toggle]"));
    let currentWorkItems = [];
    let currentReminders = [];
    let currentHistory = [];
    let currentTodayPlan = [];
    let currentTodayReminders = [];
    const collapsedWorkItemIds = new Set();
    const storedCollapsedIds = window.localStorage.getItem("workbench-collapsed-work-items");
    if (storedCollapsedIds) {
      try {
        JSON.parse(storedCollapsedIds).forEach((id) => {
          if (typeof id === "string" && id) collapsedWorkItemIds.add(id);
        });
      } catch (_) {}
    }
    let currentMode = window.localStorage.getItem("workbench-mode") || "user";

    tokenInput.value = initialToken;
    chatIdInput.value = window.localStorage.getItem("workbench-chat-id") || "";
    versionsEl.innerHTML = '<div class="empty">Select a work item or reminder to inspect its version history.</div>';
    document.body.dataset.mode = currentMode;

    function bearerToken() {
      return tokenInput.value.trim();
    }

    function workbenchChatId() {
      return chatIdInput.value.trim();
    }

    function persistCollapsedState() {
      window.localStorage.setItem("workbench-collapsed-work-items", JSON.stringify(Array.from(collapsedWorkItemIds)));
    }

    function setMode(mode) {
      currentMode = mode === "maintenance" ? "maintenance" : "user";
      document.body.dataset.mode = currentMode;
      window.localStorage.setItem("workbench-mode", currentMode);
      modeButtons.forEach((button) => {
        button.classList.toggle("active", button.dataset.modeToggle === currentMode);
      });
      renderWorkItems(currentWorkItems);
      renderReminders(currentReminders);
      renderHistory(currentHistory);
    }

    function authHeaders(extra = {}) {
      const token = bearerToken();
      if (!token) {
        throw new Error("Add ?token=<api_token> or paste one into the token field.");
      }
      return {
        ...extra,
        "Authorization": `Bearer ${token}`,
      };
    }

    function isoFromLocal(input) {
      if (!input) return null;
      const date = new Date(input);
      return Number.isNaN(date.getTime()) ? null : date.toISOString();
    }

    function fmtDate(value) {
      if (!value) return null;
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
    }

    function parseDate(value) {
      if (!value) return null;
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? null : date;
    }

    function startOfToday() {
      const now = new Date();
      return new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
    }

    function endOfToday() {
      const start = startOfToday();
      return new Date(start.getFullYear(), start.getMonth(), start.getDate(), 23, 59, 59, 999);
    }

    function addLocalDays(baseDate, days, hour = 12) {
      return new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate() + days, hour, 0, 0, 0);
    }

    function dueValue(item) {
      return item?.due_at || item?.scheduled_for || null;
    }

    function dueMatchesFilter(item) {
      const filter = dueFilter.value;
      if (!filter) return true;
      const due = parseDate(dueValue(item));
      if (filter === "unscheduled") return !due;
      if (filter === "scheduled") return Boolean(due);
      if (!due) return false;
      const start = startOfToday();
      const end = endOfToday();
      if (filter === "overdue") return due < start;
      if (filter === "today") return due >= start && due <= end;
      if (filter === "next7") return due >= start && due <= addLocalDays(start, 7, 23);
      if (filter === "next14") return due >= start && due <= addLocalDays(start, 14, 23);
      return true;
    }

    function filteredWorkItems(items) {
      const query = searchFilter.value.trim().toLowerCase();
      return items.filter((item) => {
        if (statusFilter.value && item.status !== statusFilter.value) return false;
        if (kindFilter.value && item.kind !== kindFilter.value) return false;
        if (!dueMatchesFilter(item)) return false;
        if (!query) return true;
        return [item.title, item.notes].filter(Boolean).some((value) => String(value).toLowerCase().includes(query));
      });
    }

    function applyWorkItemPatchLocally(item, patch) {
      const next = { ...item, ...patch };
      if (Object.prototype.hasOwnProperty.call(patch, "due_at")) next.due_at = patch.due_at;
      if (Object.prototype.hasOwnProperty.call(patch, "priority")) next.priority = patch.priority;
      if (Object.prototype.hasOwnProperty.call(patch, "parent_id")) next.parent_id = patch.parent_id;
      return next;
    }

    function applyReminderPatchLocally(item, patch) {
      return { ...item, ...patch };
    }

    function updateWorkItemCollections(itemId, patch) {
      currentWorkItems = currentWorkItems.map((item) => item.id === itemId ? applyWorkItemPatchLocally(item, patch) : item);
      currentTodayPlan = currentTodayPlan.map((item) => item.id === itemId ? applyWorkItemPatchLocally(item, patch) : item);
    }

    function updateReminderCollections(reminderId, patch) {
      currentReminders = currentReminders.map((item) => item.id === reminderId ? applyReminderPatchLocally(item, patch) : item);
      currentTodayReminders = currentTodayReminders.map((item) => item.id === reminderId ? applyReminderPatchLocally(item, patch) : item);
    }

    function showToast(message, options = {}) {
      const toast = document.createElement("div");
      toast.className = "toast";
      const messageHtml = `<strong>${escapeHtml(options.title || "Saved")}</strong><div>${escapeHtml(message)}</div>`;
      toast.innerHTML = `${messageHtml}<div class="toast-actions"></div>`;
      const actionsEl = toast.querySelector(".toast-actions");
      const dismissButton = document.createElement("button");
      dismissButton.className = "secondary";
      dismissButton.type = "button";
      dismissButton.textContent = "Dismiss";
      dismissButton.addEventListener("click", () => toast.remove());
      actionsEl.appendChild(dismissButton);
      if (typeof options.onUndo === "function") {
        const undoButton = document.createElement("button");
        undoButton.type = "button";
        undoButton.textContent = options.undoLabel || "Undo";
        undoButton.addEventListener("click", async () => {
          undoButton.disabled = true;
          try {
            await options.onUndo();
            toast.remove();
          } catch (error) {
            setStatus(error.message, true);
            undoButton.disabled = false;
          }
        });
        actionsEl.prepend(undoButton);
      }
      toastStack.prepend(toast);
      window.setTimeout(() => {
        if (toast.isConnected) toast.remove();
      }, options.timeoutMs || 7000);
    }

    function escapeHtml(value) {
      return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function setStatus(message, isError = false) {
      sessionStatus.textContent = message || "";
      sessionStatus.style.color = isError ? "var(--danger)" : "var(--muted)";
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        headers: authHeaders(options.headers || {}),
      });
      if (!response.ok) {
        const contentType = response.headers.get("content-type") || "";
        let detail = "";
        if (contentType.includes("application/json")) {
          try {
            const body = await response.json();
            if (Array.isArray(body.detail)) {
              detail = body.detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
            } else if (typeof body.detail === "string") {
              detail = body.detail;
            } else {
              detail = JSON.stringify(body);
            }
          } catch (_) {
            detail = "";
          }
        }
        if (!detail) {
          detail = await response.text();
        }
        throw new Error(detail || `HTTP ${response.status}`);
      }
      const contentType = response.headers.get("content-type") || "";
      return contentType.includes("application/json") ? response.json() : response.text();
    }

    function sortWorkItemsForHierarchy(items) {
      return items.slice().sort((left, right) => String(left.title || "").localeCompare(String(right.title || "")));
    }

    function updateKpis(items = currentWorkItems, reminders = currentReminders) {
      kpiOpen.textContent = items.filter((item) => item.status === "open").length;
      kpiUrgent.textContent = items.filter((item) => item.priority === 1 && item.status === "open").length;
      kpiReminders.textContent = reminders.filter((item) => item.status === "pending").length;
    }

    function renderWorkItems(items = currentWorkItems) {
      if (Array.isArray(items)) {
        currentWorkItems = items.slice();
      }
      const visibleItems = filteredWorkItems(currentWorkItems);
      if (!visibleItems.length) {
        workItemsEl.innerHTML = '<div class="empty">No work items matched the current filters.</div>';
        updateKpis(currentWorkItems, currentReminders);
        return;
      }
      const byId = new Map(visibleItems.map((item) => [item.id, item]));
      const childrenByParent = new Map();
      visibleItems.forEach((item) => {
        const key = item.parent_id && byId.has(item.parent_id) ? item.parent_id : "__root__";
        if (!childrenByParent.has(key)) childrenByParent.set(key, []);
        childrenByParent.get(key).push(item);
      });
      for (const rows of childrenByParent.values()) {
        rows.splice(0, rows.length, ...sortWorkItemsForHierarchy(rows));
      }
      const rootItems = childrenByParent.get("__root__") || [];
      const sections = [
        { title: "Projects", rows: rootItems.filter((item) => item.kind === "project") },
        { title: "Tasks", rows: rootItems.filter((item) => item.kind === "task") },
        { title: "Subtasks", rows: rootItems.filter((item) => item.kind === "subtask") },
      ].filter((section) => section.rows.length > 0);

      function renderWorkItemNode(item) {
        const children = childrenByParent.get(item.id) || [];
        const parentTitle = item.parent_id ? byId.get(item.parent_id)?.title : null;
        const meta = [
          currentMode === "maintenance" ? item.kind : null,
          item.status !== "open" ? item.status : null,
          item.priority ? `p${item.priority}` : null,
          currentMode === "maintenance" && parentTitle ? `under ${parentTitle}` : null,
          dueValue(item) ? `due ${fmtDate(dueValue(item))}` : null,
        ].filter(Boolean).map((value) => `<span class="pill">${escapeHtml(value)}</span>`).join("");
        const notes = item.notes ? `<p class="notes">${escapeHtml(item.notes)}</p>` : "";
        const showChildren = children.length > 0 && !collapsedWorkItemIds.has(item.id);
        const toggle = children.length
          ? `<button class="tree-toggle" type="button" data-item-toggle="${item.id}">${showChildren ? "▾" : "▸"} ${showChildren ? "Hide" : "Show"} children (${children.length})</button>`
          : "";
        const versionsButton = currentMode === "maintenance"
          ? `<button class="secondary" type="button" data-item-versions="${item.id}">Versions</button>`
          : "";
        const statusButton = item.status === "done"
          ? `<button class="secondary" type="button" data-item-id="${item.id}" data-status="open">Reopen</button>`
          : `<button class="warn" type="button" data-item-id="${item.id}" data-status="done">Done</button>`;
        const priorityButton = item.priority === 1
          ? `<button class="secondary" type="button" data-item-quick="${item.id}" data-quick-action="normal-priority">Normal priority</button>`
          : `<button class="secondary" type="button" data-item-quick="${item.id}" data-quick-action="high-priority">High priority</button>`;
        return `
          <article class="item">
            <div class="tree-head">
              <div class="tree-label">
                <h3 class="item-title">${escapeHtml(item.title)}</h3>
              </div>
              ${toggle}
            </div>
            <div class="meta">${meta}</div>
            ${notes}
            <div class="actions">
              <button class="secondary" type="button" data-item-edit="${item.id}">Edit</button>
              ${statusButton}
              <button class="secondary" type="button" data-item-quick="${item.id}" data-quick-action="today">Today</button>
              <button class="secondary" type="button" data-item-quick="${item.id}" data-quick-action="tomorrow">Tomorrow</button>
              <button class="secondary" type="button" data-item-quick="${item.id}" data-quick-action="next-week">+1 week</button>
              ${priorityButton}
              <button class="secondary maintenance-only" type="button" data-item-id="${item.id}" data-status="blocked">Blocked</button>
              <button class="danger maintenance-only" type="button" data-item-id="${item.id}" data-status="archived">Archive</button>
              ${versionsButton}
            </div>
            ${children.length ? `<div class="tree-children ${showChildren ? "" : "collapsed"}">${children.map(renderWorkItemNode).join("")}</div>` : ""}
          </article>
        `;
      }

      workItemsEl.innerHTML = sections.map((section) => `
        <section class="tree-section">
          <h3 class="tree-section-title">${escapeHtml(section.title)}</h3>
          ${section.rows.map(renderWorkItemNode).join("")}
        </section>
      `).join("");
      updateKpis(currentWorkItems, currentReminders);
    }

    function renderTodayPanel() {
      if (!currentTodayPlan.length && !currentTodayReminders.length) {
        todayPanel.classList.add("is-empty");
        todayPlanItemsEl.innerHTML = '<div class="empty">Load the live plan when you want a Telegram-grounded view of today.</div>';
        todayPlanRemindersEl.innerHTML = '<div class="empty">No due reminders loaded into the today panel.</div>';
        return;
      }
      todayPanel.classList.remove("is-empty");
      if (!currentTodayPlan.length) {
        todayPlanItemsEl.innerHTML = '<div class="empty">No work items in the loaded today plan.</div>';
      } else {
        todayPlanItemsEl.innerHTML = currentTodayPlan.map((item) => `
          <article class="item today-item">
            <h3 class="item-title">${escapeHtml(item.title)}</h3>
            <div class="meta">
              ${item.kind ? `<span class="pill">${escapeHtml(item.kind)}</span>` : ""}
              ${item.parent_title ? `<span class="pill">under ${escapeHtml(item.parent_title)}</span>` : ""}
              ${dueValue(item) ? `<span class="pill">due ${escapeHtml(fmtDate(dueValue(item)) || dueValue(item))}</span>` : ""}
            </div>
            ${item.notes ? `<p class="notes">${escapeHtml(item.notes)}</p>` : ""}
            <div class="actions">
              <button class="warn" type="button" data-item-id="${item.id}" data-status="done">Done</button>
              <button class="secondary" type="button" data-item-edit="${item.id}">Edit</button>
              <button class="secondary" type="button" data-item-quick="${item.id}" data-quick-action="today">Today</button>
              <button class="secondary" type="button" data-item-quick="${item.id}" data-quick-action="tomorrow">Tomorrow</button>
              <button class="secondary" type="button" data-item-quick="${item.id}" data-quick-action="next-week">+1 week</button>
            </div>
          </article>
        `).join("");
      }
      if (!currentTodayReminders.length) {
        todayPlanRemindersEl.innerHTML = '<div class="empty">No due reminders in the loaded today panel.</div>';
      } else {
        todayPlanRemindersEl.innerHTML = currentTodayReminders.map((item) => `
          <article class="item today-item">
            <h3 class="item-title">${escapeHtml(item.title)}</h3>
            <div class="meta">
              <span class="pill">${escapeHtml(item.status || "pending")}</span>
              <span class="pill">${escapeHtml(fmtDate(item.remind_at) || item.remind_at)}</span>
            </div>
            ${item.message ? `<p class="notes">${escapeHtml(item.message)}</p>` : ""}
            <div class="actions">
              <button class="warn" type="button" data-reminder-id="${item.id}" data-reminder-status="completed">Completed</button>
              <button class="secondary" type="button" data-reminder-snooze="${item.id}" data-snooze-preset="1h">+1h</button>
              <button class="secondary" type="button" data-reminder-snooze="${item.id}" data-snooze-preset="tomorrow_morning">Tomorrow AM</button>
            </div>
          </article>
        `).join("");
      }
    }

    function renderReminders(items) {
      currentReminders = Array.isArray(items) ? items.slice() : [];
      if (!items.length) {
        remindersEl.innerHTML = '<div class="empty">No reminders yet.</div>';
        updateKpis(currentWorkItems, currentReminders);
        return;
      }
      const workItemTitleById = new Map(currentWorkItems.map((item) => [item.id, item.title]));
      remindersEl.innerHTML = items.map((item) => `
        <article class="item">
          <h3 class="item-title">${escapeHtml(item.title)}</h3>
          <div class="meta">
            <span class="pill">${escapeHtml(item.status)}</span>
            <span class="pill">${escapeHtml(item.kind)}</span>
            <span class="pill">${escapeHtml(fmtDate(item.remind_at) || item.remind_at)}</span>
            ${item.recurrence_rule ? `<span class="pill">${escapeHtml(item.recurrence_rule)}</span>` : ""}
            ${item.work_item_id ? `<span class="pill">for ${escapeHtml(item.work_item_title || workItemTitleById.get(item.work_item_id) || item.work_item_id)}</span>` : ""}
          </div>
          ${item.message ? `<p class="notes">${escapeHtml(item.message)}</p>` : ""}
          <div class="actions">
            <button class="secondary" type="button" data-reminder-edit="${item.id}">Edit</button>
            <button class="secondary" type="button" data-reminder-id="${item.id}" data-reminder-status="pending">Pending</button>
            <button class="warn" type="button" data-reminder-id="${item.id}" data-reminder-status="completed">Completed</button>
            <button class="danger" type="button" data-reminder-id="${item.id}" data-reminder-status="dismissed">Dismiss</button>
            <button class="secondary" type="button" data-reminder-snooze="${item.id}" data-snooze-preset="1h">+1h</button>
            <button class="secondary" type="button" data-reminder-snooze="${item.id}" data-snooze-preset="tomorrow_morning">Tomorrow AM</button>
            <button class="secondary" type="button" data-reminder-snooze="${item.id}" data-snooze-preset="next_week">+1 week</button>
            ${currentMode === "maintenance" ? `<button class="secondary" type="button" data-reminder-versions="${item.id}">Versions</button>` : ""}
          </div>
        </article>
      `).join("");
      updateKpis(currentWorkItems, currentReminders);
    }

    function renderHistory(items) {
      currentHistory = Array.isArray(items) ? items.slice() : [];
      if (!items.length) {
        historyEl.innerHTML = '<div class="empty">No action history yet.</div>';
        return;
      }
      const now = Date.now();
      historyEl.innerHTML = items.map((item) => `
        <article class="item">
          <h3 class="item-title">${escapeHtml(item.after_summary || item.source_message || "Change batch")}</h3>
          <div class="meta">
            <span class="pill">${escapeHtml(item.status)}</span>
            <span class="pill">${escapeHtml(fmtDate(item.created_at) || item.created_at)}</span>
            <span class="pill">${escapeHtml(String((item.applied_item_ids || []).length))} items</span>
          </div>
          ${item.source_message ? `<p class="notes">${escapeHtml(item.source_message)}</p>` : ""}
          <div class="actions">
            ${(item.status === "applied" && !item.reverted_at && (!item.undo_window_expires_at || new Date(item.undo_window_expires_at).getTime() >= now))
              ? `<button class="secondary" type="button" data-batch-id="${item.id}">Undo</button>`
              : ""}
          </div>
        </article>
      `).join("");
    }

    function renderVersions(items, label) {
      if (!items.length) {
        versionsEl.innerHTML = `<div class="empty">No version history for ${escapeHtml(label)} yet.</div>`;
        return;
      }
      versionsEl.innerHTML = items.map((item) => `
        <article class="item">
          <h3 class="item-title">${escapeHtml(item.operation || "update")}</h3>
          <div class="meta">
            <span class="pill">${escapeHtml(fmtDate(item.created_at) || item.created_at)}</span>
            ${item.action_batch_id ? `<span class="pill">${escapeHtml(item.action_batch_id)}</span>` : ""}
          </div>
          <p class="notes">Before: ${escapeHtml(JSON.stringify(item.before_json || {}))}</p>
          <p class="notes">After: ${escapeHtml(JSON.stringify(item.after_json || {}))}</p>
        </article>
      `).join("");
    }

    async function loadDashboard(options = {}) {
      if (!options.quiet) {
        setStatus("Refreshing workbench...");
      }
      const params = new URLSearchParams({ limit: "200" });
      const [itemsResult, remindersResult, historyResult] = await Promise.allSettled([
        api(`/v1/work_items?${params.toString()}`),
        api("/v1/reminders?limit=50"),
        api("/v1/history/action_batches?limit=12"),
      ]);
      const failures = [];
      if (itemsResult.status === "fulfilled") {
        renderWorkItems(itemsResult.value);
      } else {
        failures.push(`work items: ${itemsResult.reason.message}`);
      }
      if (remindersResult.status === "fulfilled") {
        renderReminders(remindersResult.value);
      } else {
        failures.push(`reminders: ${remindersResult.reason.message}`);
      }
      if (historyResult.status === "fulfilled") {
        renderHistory(historyResult.value);
      } else {
        failures.push(`history: ${historyResult.reason.message}`);
      }
      updateKpis(currentWorkItems, currentReminders);
      if (failures.length) {
        setStatus(`Workbench refreshed with partial errors: ${failures.join(" | ")}`, true);
        return;
      }
      if (!options.quiet) {
        setStatus(`Loaded ${currentWorkItems.length} work items, ${currentReminders.length} reminders, and ${currentHistory.length} recent changes.`);
      }
    }

    async function loadToday() {
      setStatus("Loading today plan...");
      const params = new URLSearchParams();
      if (workbenchChatId()) params.set("chat_id", workbenchChatId());
      const suffix = params.toString() ? `?${params.toString()}` : "";
      const plan = await api(`/v1/plan/get_today${suffix}`);
      currentTodayPlan = (plan.today_plan || []).map((item) => ({
        id: item.task_id,
        title: item.title,
        kind: item.kind || "task",
        status: "open",
        priority: null,
        parent_id: item.parent_id || null,
        due_at: null,
        scheduled_for: null,
        parent_title: item.parent_title || null,
        notes: item.parent_title ? `Under ${item.parent_title}` : "",
      }));
      currentTodayReminders = (plan.due_reminders || []).map((item) => ({
        id: item.reminder_id,
        title: item.title,
        status: "pending",
        kind: "one_off",
        remind_at: item.remind_at,
        message: item.message || "",
        work_item_id: item.work_item_id || null,
      }));
      renderTodayPanel();
      setStatus(`Loaded today plan with ${(plan.today_plan || []).length} items.`);
    }

    async function loadUrgent() {
      setStatus("Loading urgent items...");
      const items = await api("/v1/work_items?status=open&limit=200");
      const urgent = items.filter((item) => item.priority === 1).sort((a, b) => a.title.localeCompare(b.title));
      renderWorkItems(urgent);
      setStatus(`Loaded ${urgent.length} urgent items.`);
    }

    async function createWorkItem() {
      const payload = {
        title: document.getElementById("new-title").value.trim(),
        kind: document.getElementById("new-kind").value,
        parent_id: document.getElementById("new-parent-id").value.trim() || null,
        notes: document.getElementById("new-notes").value.trim() || null,
        status: "open",
        priority: document.getElementById("new-priority").value ? Number(document.getElementById("new-priority").value) : null,
        due_at: isoFromLocal(document.getElementById("new-due-at").value),
      };
      if (!payload.title) {
        throw new Error("Title is required.");
      }
      await api("/v1/work_items", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `ui-work-item-${Date.now()}`,
        },
        body: JSON.stringify(payload),
      });
      document.getElementById("new-title").value = "";
      document.getElementById("new-parent-id").value = "";
      document.getElementById("new-notes").value = "";
      document.getElementById("new-due-at").value = "";
      document.getElementById("new-priority").value = "";
      await loadDashboard();
    }

    async function createReminder() {
      const payload = {
        title: document.getElementById("new-reminder-title").value.trim(),
        remind_at: isoFromLocal(document.getElementById("new-reminder-at").value),
        message: document.getElementById("new-reminder-message").value.trim() || null,
        status: "pending",
        kind: "one_off",
        recurrence_rule: document.getElementById("new-reminder-recurrence").value || null,
        work_item_id: document.getElementById("new-reminder-work-item-id").value.trim() || null,
      };
      if (payload.recurrence_rule) {
        payload.kind = "recurring";
      }
      if (!payload.title || !payload.remind_at) {
        throw new Error("Reminder title and remind time are required.");
      }
      await api("/v1/reminders", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `ui-reminder-${Date.now()}`,
        },
        body: JSON.stringify(payload),
      });
      document.getElementById("new-reminder-title").value = "";
      document.getElementById("new-reminder-at").value = "";
      document.getElementById("new-reminder-message").value = "";
      document.getElementById("new-reminder-recurrence").value = "";
      document.getElementById("new-reminder-work-item-id").value = "";
      await loadDashboard();
    }

    async function editWorkItem(itemId) {
      let item = currentWorkItems.find((row) => row.id === itemId) || currentTodayPlan.find((row) => row.id === itemId);
      if (!item || item.notes === undefined) {
        const items = await api("/v1/work_items?limit=200");
        item = items.find((row) => row.id === itemId);
      }
      if (!item) {
        throw new Error("Work item not found.");
      }

      const title = window.prompt("Title", item.title || "");
      if (title === null) return;
      const notes = window.prompt("Notes (blank clears)", item.notes || "");
      if (notes === null) return;
      const priority = window.prompt("Priority 1-4 (blank clears)", item.priority ? String(item.priority) : "");
      if (priority === null) return;
      const due = window.prompt(
        "Due date/time in local browser format or blank to clear",
        item.due_at ? new Date(item.due_at).toISOString().slice(0, 16) : ""
      );
      if (due === null) return;
      const parentId = window.prompt("Parent work item id (blank clears)", item.parent_id || "");
      if (parentId === null) return;

      const normalizedPriority = priority.trim() ? Number(priority.trim()) : null;
      if (priority.trim() && (!Number.isInteger(normalizedPriority) || normalizedPriority < 1 || normalizedPriority > 4)) {
        throw new Error("Priority must be 1-4 or blank.");
      }

      const patch = {
        title: title.trim(),
        notes: notes.trim() || null,
        priority: normalizedPriority,
        due_at: isoFromLocal(due.trim()),
        parent_id: parentId.trim() || null,
      };
      await patchWorkItem(itemId, patch, {
        successMessage: `Saved changes to ${patch.title || item.title}.`,
        undoPatch: {
          title: item.title,
          notes: item.notes || null,
          priority: item.priority || null,
          due_at: item.due_at || null,
          parent_id: item.parent_id || null,
        },
        undoMessage: `Reverted changes to ${item.title}.`,
      });
    }

    async function editReminder(reminderId) {
      let reminder = currentReminders.find((row) => row.id === reminderId) || currentTodayReminders.find((row) => row.id === reminderId);
      if (!reminder) {
        const reminders = await api("/v1/reminders?limit=200");
        reminder = reminders.find((row) => row.id === reminderId);
      }
      if (!reminder) {
        throw new Error("Reminder not found.");
      }

      const title = window.prompt("Reminder title", reminder.title || "");
      if (title === null) return;
      const message = window.prompt("Reminder message (blank clears)", reminder.message || "");
      if (message === null) return;
      const remindAt = window.prompt(
        "Reminder time in local browser format",
        reminder.remind_at ? new Date(reminder.remind_at).toISOString().slice(0, 16) : ""
      );
      if (remindAt === null) return;
      const recurrence = window.prompt(
        "Recurrence: blank, daily, weekly, weekdays, or monthly",
        reminder.recurrence_rule || ""
      );
      if (recurrence === null) return;
      const workItemId = window.prompt("Linked work item id (blank clears)", reminder.work_item_id || "");
      if (workItemId === null) return;

      const patch = {
        title: title.trim(),
        message: message.trim() || null,
        remind_at: isoFromLocal(remindAt.trim()),
        recurrence_rule: recurrence.trim() || null,
        kind: recurrence.trim() ? "recurring" : "one_off",
        work_item_id: workItemId.trim() || null,
      };
      await patchReminder(reminderId, patch, {
        successMessage: `Saved changes to reminder ${patch.title || reminder.title}.`,
        undoPatch: {
          title: reminder.title,
          message: reminder.message || null,
          remind_at: reminder.remind_at || null,
          recurrence_rule: reminder.recurrence_rule || null,
          kind: reminder.kind || "one_off",
          work_item_id: reminder.work_item_id || null,
        },
        undoMessage: `Reverted changes to reminder ${reminder.title}.`,
      });
    }

    async function patchWorkItem(itemId, patch, options = {}) {
      const existing = currentWorkItems.find((item) => item.id === itemId) || currentTodayPlan.find((item) => item.id === itemId);
      if (!existing) {
        throw new Error("Work item not found.");
      }
      const previousItems = currentWorkItems.slice();
      const previousToday = currentTodayPlan.slice();
      updateWorkItemCollections(itemId, patch);
      renderWorkItems();
      renderTodayPanel();
      setStatus(options.pendingMessage || `Updating ${existing.title || itemId}...`);
      try {
        const updated = await api(`/v1/work_items/${itemId}`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": `ui-work-item-update-${itemId}-${Date.now()}`,
          },
          body: JSON.stringify(patch),
        });
        updateWorkItemCollections(itemId, updated);
        renderWorkItems();
        renderTodayPanel();
        await loadDashboard({ quiet: true });
        if (options.successMessage) {
          setStatus(options.successMessage);
        }
        if (options.allowUndo !== false && options.undoPatch) {
          showToast(options.successMessage || `Updated ${updated.title || existing.title}.`, {
            onUndo: () => patchWorkItem(itemId, options.undoPatch, {
              successMessage: options.undoMessage || `Reverted ${updated.title || existing.title}.`,
              allowUndo: false,
            }),
          });
        }
      } catch (error) {
        currentWorkItems = previousItems;
        currentTodayPlan = previousToday;
        renderWorkItems();
        renderTodayPanel();
        throw error;
      }
    }

    async function updateWorkItemStatus(itemId, nextStatus) {
      const item = currentWorkItems.find((row) => row.id === itemId) || currentTodayPlan.find((row) => row.id === itemId);
      if (!item || item.status === nextStatus) return;
      await patchWorkItem(itemId, { status: nextStatus }, {
        successMessage: `${nextStatus === "done" ? "Marked" : nextStatus === "open" ? "Reopened" : "Updated"} ${item.title}.`,
        undoPatch: { status: item.status },
        undoMessage: `Reverted ${item.title} to ${item.status}.`,
      });
    }

    async function patchReminder(reminderId, patch, options = {}) {
      const existing = currentReminders.find((item) => item.id === reminderId) || currentTodayReminders.find((item) => item.id === reminderId);
      if (!existing) {
        throw new Error("Reminder not found.");
      }
      const previousReminders = currentReminders.slice();
      const previousTodayReminders = currentTodayReminders.slice();
      updateReminderCollections(reminderId, patch);
      renderReminders(currentReminders);
      renderTodayPanel();
      setStatus(options.pendingMessage || `Updating ${existing.title || reminderId}...`);
      try {
        const updated = await api(`/v1/reminders/${reminderId}`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": `ui-reminder-update-${reminderId}-${Date.now()}`,
          },
          body: JSON.stringify(patch),
        });
        updateReminderCollections(reminderId, updated);
        renderReminders(currentReminders);
        renderTodayPanel();
        await loadDashboard({ quiet: true });
        if (options.successMessage) {
          setStatus(options.successMessage);
        }
        if (options.allowUndo !== false && options.undoPatch) {
          showToast(options.successMessage || `Updated reminder ${updated.title || existing.title}.`, {
            onUndo: () => patchReminder(reminderId, options.undoPatch, {
              successMessage: options.undoMessage || `Reverted reminder ${updated.title || existing.title}.`,
              allowUndo: false,
            }),
          });
        }
      } catch (error) {
        currentReminders = previousReminders;
        currentTodayReminders = previousTodayReminders;
        renderReminders(currentReminders);
        renderTodayPanel();
        throw error;
      }
    }

    async function updateReminderStatus(reminderId, nextStatus) {
      const reminder = currentReminders.find((row) => row.id === reminderId) || currentTodayReminders.find((row) => row.id === reminderId);
      if (!reminder || reminder.status === nextStatus) return;
      await patchReminder(reminderId, { status: nextStatus }, {
        successMessage: `${nextStatus === "completed" ? "Completed" : "Updated"} reminder ${reminder.title}.`,
        undoPatch: { status: reminder.status },
        undoMessage: `Reverted reminder ${reminder.title}.`,
      });
    }

    async function applyQuickAction(itemId, action) {
      const item = currentWorkItems.find((row) => row.id === itemId) || currentTodayPlan.find((row) => row.id === itemId);
      if (!item) {
        throw new Error("Work item not found.");
      }
      const today = addLocalDays(startOfToday(), 0);
      const tomorrow = addLocalDays(startOfToday(), 1);
      const nextWeek = addLocalDays(startOfToday(), 7);
      const actions = {
        "today": {
          patch: { due_at: today.toISOString() },
          message: `Scheduled ${item.title} for today.`,
        },
        "tomorrow": {
          patch: { due_at: tomorrow.toISOString() },
          message: `Scheduled ${item.title} for tomorrow.`,
        },
        "next-week": {
          patch: { due_at: nextWeek.toISOString() },
          message: `Scheduled ${item.title} for next week.`,
        },
        "high-priority": {
          patch: { priority: 1 },
          message: `Marked ${item.title} high priority.`,
        },
        "normal-priority": {
          patch: { priority: null },
          message: `Cleared priority for ${item.title}.`,
        },
      };
      const selected = actions[action];
      if (!selected) {
        throw new Error("Unsupported quick action.");
      }
      await patchWorkItem(itemId, selected.patch, {
        successMessage: selected.message,
        undoPatch: {
          due_at: Object.prototype.hasOwnProperty.call(selected.patch, "due_at") ? dueValue(item) : undefined,
          priority: Object.prototype.hasOwnProperty.call(selected.patch, "priority") ? (item.priority || null) : undefined,
        },
        undoMessage: `Reverted quick action on ${item.title}.`,
      });
    }

    async function snoozeReminder(reminderId, preset) {
      await api(`/v1/reminders/${reminderId}/snooze`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `ui-reminder-snooze-${reminderId}-${preset}-${Date.now()}`,
        },
        body: JSON.stringify({ preset }),
      });
      await loadDashboard({ quiet: true });
      showToast(`Snoozed reminder using ${preset.replaceAll("_", " ")}.`, { title: "Reminder updated" });
    }

    async function undoBatch(batchId) {
      await api(`/v1/history/action_batches/${batchId}/undo`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `ui-undo-${batchId}-${Date.now()}`,
        },
        body: JSON.stringify({}),
      });
      await loadDashboard({ quiet: true });
      showToast("Reverted the selected action batch.", { title: "Undo complete" });
    }

    async function loadWorkItemVersions(itemId) {
      setStatus(`Loading work item history for ${itemId}...`);
      const versions = await api(`/v1/work_items/${itemId}/versions?limit=20`);
      renderVersions(versions, `work item ${itemId}`);
      setStatus(`Loaded ${versions.length} versions for ${itemId}.`);
    }

    async function loadReminderVersions(reminderId) {
      setStatus(`Loading reminder history for ${reminderId}...`);
      const versions = await api(`/v1/reminders/${reminderId}/versions?limit=20`);
      renderVersions(versions, `reminder ${reminderId}`);
      setStatus(`Loaded ${versions.length} versions for ${reminderId}.`);
    }

    document.getElementById("refresh-button").addEventListener("click", () => loadDashboard().catch((error) => setStatus(error.message, true)));
    document.getElementById("load-today-button").addEventListener("click", () => loadToday().catch((error) => setStatus(error.message, true)));
    document.getElementById("load-urgent-button").addEventListener("click", () => loadUrgent().catch((error) => setStatus(error.message, true)));
    document.getElementById("load-open-button").addEventListener("click", () => {
      statusFilter.value = "open";
      renderWorkItems();
      setStatus("Showing open work items.");
    });
    document.getElementById("dispatch-reminders-button").addEventListener("click", async () => {
      try {
        setStatus("Dispatching due reminders...");
        await api("/v1/reminders/dispatch_due", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": `ui-reminder-dispatch-${Date.now()}`,
          },
          body: JSON.stringify({}),
        });
        setStatus("Reminder dispatch enqueued.");
      } catch (error) {
        setStatus(error.message, true);
      }
    });
    document.getElementById("create-work-item-button").addEventListener("click", () => createWorkItem().catch((error) => setStatus(error.message, true)));
    document.getElementById("create-reminder-button").addEventListener("click", () => createReminder().catch((error) => setStatus(error.message, true)));
    chatIdInput.addEventListener("change", () => {
      window.localStorage.setItem("workbench-chat-id", workbenchChatId());
    });
    document.getElementById("reset-filters-button").addEventListener("click", () => {
      searchFilter.value = "";
      statusFilter.value = "";
      kindFilter.value = "";
      dueFilter.value = "";
      renderWorkItems();
      setStatus("Reset work item filters.");
    });
    document.getElementById("clear-today-button").addEventListener("click", () => {
      currentTodayPlan = [];
      currentTodayReminders = [];
      renderTodayPanel();
      setStatus("Cleared the today panel.");
    });
    modeButtons.forEach((button) => {
      button.addEventListener("click", () => setMode(button.dataset.modeToggle));
    });
    [searchFilter, statusFilter, kindFilter, dueFilter].forEach((input) => {
      input.addEventListener(input.tagName === "INPUT" ? "input" : "change", () => renderWorkItems());
    });

    workItemsEl.addEventListener("click", (event) => {
      const toggleButton = event.target.closest("button[data-item-toggle]");
      if (toggleButton) {
        const itemId = toggleButton.dataset.itemToggle;
        if (collapsedWorkItemIds.has(itemId)) {
          collapsedWorkItemIds.delete(itemId);
        } else {
          collapsedWorkItemIds.add(itemId);
        }
        persistCollapsedState();
        renderWorkItems(currentWorkItems);
        return;
      }
      const editButton = event.target.closest("button[data-item-edit]");
      if (editButton) {
        editWorkItem(editButton.dataset.itemEdit).catch((error) => setStatus(error.message, true));
        return;
      }
      const button = event.target.closest("button[data-item-id]");
      if (button) {
        updateWorkItemStatus(button.dataset.itemId, button.dataset.status).catch((error) => setStatus(error.message, true));
        return;
      }
      const quickButton = event.target.closest("button[data-item-quick]");
      if (quickButton) {
        applyQuickAction(quickButton.dataset.itemQuick, quickButton.dataset.quickAction).catch((error) => setStatus(error.message, true));
        return;
      }
      const versionsButton = event.target.closest("button[data-item-versions]");
      if (!versionsButton) return;
      loadWorkItemVersions(versionsButton.dataset.itemVersions).catch((error) => setStatus(error.message, true));
    });

    todayPanel.addEventListener("click", (event) => {
      const itemStatusButton = event.target.closest("button[data-item-id]");
      if (itemStatusButton) {
        updateWorkItemStatus(itemStatusButton.dataset.itemId, itemStatusButton.dataset.status).catch((error) => setStatus(error.message, true));
        return;
      }
      const itemEditButton = event.target.closest("button[data-item-edit]");
      if (itemEditButton) {
        editWorkItem(itemEditButton.dataset.itemEdit).catch((error) => setStatus(error.message, true));
        return;
      }
      const quickButton = event.target.closest("button[data-item-quick]");
      if (quickButton) {
        applyQuickAction(quickButton.dataset.itemQuick, quickButton.dataset.quickAction).catch((error) => setStatus(error.message, true));
        return;
      }
      const reminderStatusButton = event.target.closest("button[data-reminder-id]");
      if (reminderStatusButton) {
        updateReminderStatus(reminderStatusButton.dataset.reminderId, reminderStatusButton.dataset.reminderStatus).catch((error) => setStatus(error.message, true));
        return;
      }
      const reminderSnoozeButton = event.target.closest("button[data-reminder-snooze]");
      if (reminderSnoozeButton) {
        snoozeReminder(reminderSnoozeButton.dataset.reminderSnooze, reminderSnoozeButton.dataset.snoozePreset).catch((error) => setStatus(error.message, true));
      }
    });

    remindersEl.addEventListener("click", (event) => {
      const editButton = event.target.closest("button[data-reminder-edit]");
      if (editButton) {
        editReminder(editButton.dataset.reminderEdit).catch((error) => setStatus(error.message, true));
        return;
      }
      const button = event.target.closest("button[data-reminder-id]");
      if (button) {
        updateReminderStatus(button.dataset.reminderId, button.dataset.reminderStatus).catch((error) => setStatus(error.message, true));
        return;
      }
      const snoozeButton = event.target.closest("button[data-reminder-snooze]");
      if (snoozeButton) {
        snoozeReminder(snoozeButton.dataset.reminderSnooze, snoozeButton.dataset.snoozePreset).catch((error) => setStatus(error.message, true));
        return;
      }
      const versionsButton = event.target.closest("button[data-reminder-versions]");
      if (!versionsButton) return;
      loadReminderVersions(versionsButton.dataset.reminderVersions).catch((error) => setStatus(error.message, true));
    });

    historyEl.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-batch-id]");
      if (!button) return;
      undoBatch(button.dataset.batchId).catch((error) => setStatus(error.message, true));
    });

    setMode(currentMode);
    renderTodayPanel();
    if (bearerToken()) {
      loadDashboard().catch((error) => setStatus(error.message, true));
    }
  </script>
</body>
</html>
"""


def render_maintenance_ui(token: Optional[str]) -> str:
    return _MAINTENANCE_UI_TEMPLATE.replace("__TOKEN_JSON__", json.dumps(token or ""))
