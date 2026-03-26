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
      .toolbar, .kpis {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    @media (max-width: 640px) {
      .shell {
        padding: 18px 14px 42px;
      }
      .toolbar, .kpis {
        grid-template-columns: 1fr;
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
            <label>
              API token
              <input id="token-input" type="password" placeholder="test_token or real bearer token" />
            </label>
            <label>
              Work item status filter
              <select id="status-filter">
                <option value="">All statuses</option>
                <option value="open">Open</option>
                <option value="blocked">Blocked</option>
                <option value="done">Done</option>
                <option value="archived">Archived</option>
              </select>
            </label>
            <label>
              Work item kind filter
              <select id="kind-filter">
                <option value="">All kinds</option>
                <option value="project">Project</option>
                <option value="task">Task</option>
                <option value="subtask">Subtask</option>
              </select>
            </label>
            <button id="refresh-button" type="button">Refresh</button>
          </div>
          <div class="status" id="session-status"></div>
        </section>

        <section class="panel">
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

        <section class="panel">
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
            <button class="warn" id="dispatch-reminders-button" type="button">Dispatch due reminders</button>
          </div>

          <div class="section-head">
            <div>
              <h2>Work Items</h2>
              <p>Fast maintenance layer over the canonical local-first store.</p>
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

        <section class="panel">
          <div class="section-head">
            <div>
              <h2>Recent Changes</h2>
              <p>Read-only action history from the local-first audit trail.</p>
            </div>
          </div>
          <div class="items" id="history"></div>
        </section>

        <section class="panel">
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

  <script>
    const initialToken = __TOKEN_JSON__;
    const tokenInput = document.getElementById("token-input");
    const statusFilter = document.getElementById("status-filter");
    const kindFilter = document.getElementById("kind-filter");
    const sessionStatus = document.getElementById("session-status");
    const workItemsEl = document.getElementById("work-items");
    const remindersEl = document.getElementById("reminders");
    const historyEl = document.getElementById("history");
    const versionsEl = document.getElementById("versions");
    const kpiOpen = document.getElementById("kpi-open");
    const kpiUrgent = document.getElementById("kpi-urgent");
    const kpiReminders = document.getElementById("kpi-reminders");
    let currentWorkItems = [];
    let currentReminders = [];

    tokenInput.value = initialToken;
    versionsEl.innerHTML = '<div class="empty">Select a work item or reminder to inspect its version history.</div>';

    function bearerToken() {
      return tokenInput.value.trim();
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
        const detail = await response.text();
        throw new Error(detail || `HTTP ${response.status}`);
      }
      const contentType = response.headers.get("content-type") || "";
      return contentType.includes("application/json") ? response.json() : response.text();
    }

    function hierarchyDepth(item, byId) {
      let depth = 0;
      let current = item;
      const seen = new Set();
      while (current && current.parent_id && byId.has(current.parent_id) && !seen.has(current.parent_id) && depth < 6) {
        seen.add(current.parent_id);
        current = byId.get(current.parent_id);
        depth += 1;
      }
      return depth;
    }

    function sortWorkItemsForHierarchy(items) {
      const byId = new Map(items.map((item) => [item.id, item]));
      const childrenByParent = new Map();
      items.forEach((item) => {
        const key = item.parent_id && byId.has(item.parent_id) ? item.parent_id : "__root__";
        if (!childrenByParent.has(key)) childrenByParent.set(key, []);
        childrenByParent.get(key).push(item);
      });
      for (const rows of childrenByParent.values()) {
        rows.sort((left, right) => String(left.title || "").localeCompare(String(right.title || "")));
      }
      const ordered = [];
      const seen = new Set();
      function walk(item) {
        if (!item || seen.has(item.id)) return;
        seen.add(item.id);
        ordered.push(item);
        const children = childrenByParent.get(item.id) || [];
        children.forEach(walk);
      }
      (childrenByParent.get("__root__") || []).forEach(walk);
      items.forEach(walk);
      return ordered;
    }

    function renderWorkItems(items) {
      currentWorkItems = Array.isArray(items) ? items.slice() : [];
      if (!items.length) {
        workItemsEl.innerHTML = '<div class="empty">No work items matched the current filters.</div>';
        return;
      }
      const titleById = new Map(items.map((item) => [item.id, item.title]));
      const byId = new Map(items.map((item) => [item.id, item]));
      const orderedItems = sortWorkItemsForHierarchy(items);
      workItemsEl.innerHTML = orderedItems.map((item) => {
        const depth = hierarchyDepth(item, byId);
        const parentTitle = item.parent_id ? titleById.get(item.parent_id) : null;
        const meta = [
          item.kind,
          item.status,
          item.priority ? `p${item.priority}` : null,
          parentTitle ? `under ${parentTitle}` : null,
          item.due_at ? `due ${fmtDate(item.due_at)}` : null,
        ].filter(Boolean).map((value) => `<span class="pill">${escapeHtml(value)}</span>`).join("");
        const notes = item.notes ? `<p class="notes">${escapeHtml(item.notes)}</p>` : "";
        return `
          <article class="item" style="margin-left: ${Math.min(depth, 3) * 18}px">
            <h3 class="item-title">${escapeHtml(item.title)}</h3>
            <div class="meta">${meta}</div>
            ${notes}
            <div class="actions">
              <button class="secondary" type="button" data-item-edit="${item.id}">Edit</button>
              <button class="secondary" type="button" data-item-id="${item.id}" data-status="open">Open</button>
              <button class="secondary" type="button" data-item-id="${item.id}" data-status="blocked">Blocked</button>
              <button class="warn" type="button" data-item-id="${item.id}" data-status="done">Done</button>
              <button class="danger" type="button" data-item-id="${item.id}" data-status="archived">Archive</button>
              <button class="secondary" type="button" data-item-versions="${item.id}">Versions</button>
            </div>
          </article>
        `;
      }).join("");
    }

    function renderReminders(items) {
      currentReminders = Array.isArray(items) ? items.slice() : [];
      if (!items.length) {
        remindersEl.innerHTML = '<div class="empty">No reminders yet.</div>';
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
            <button class="secondary" type="button" data-reminder-versions="${item.id}">Versions</button>
          </div>
        </article>
      `).join("");
    }

    function renderHistory(items) {
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

    async function loadDashboard() {
      setStatus("Refreshing workbench...");
      const params = new URLSearchParams();
      if (statusFilter.value) params.set("status", statusFilter.value);
      if (kindFilter.value) params.set("kind", kindFilter.value);
      const [items, reminders, history] = await Promise.all([
        api(`/v1/work_items?${params.toString()}`),
        api("/v1/reminders?limit=20"),
        api("/v1/history/action_batches?limit=12"),
      ]);
      renderWorkItems(items);
      renderReminders(reminders);
      renderHistory(history);
      kpiOpen.textContent = items.filter((item) => item.status === "open").length;
      kpiUrgent.textContent = items.filter((item) => item.priority === 1 && item.status === "open").length;
      kpiReminders.textContent = reminders.filter((item) => item.status === "pending").length;
      setStatus(`Loaded ${items.length} work items, ${reminders.length} reminders, and ${history.length} recent changes.`);
    }

    async function loadToday() {
      setStatus("Loading today plan...");
      const plan = await api("/v1/plan/get_today");
      renderWorkItems((plan.today_plan || []).map((item) => ({
        id: item.task_id,
        title: item.title,
        kind: "task",
        status: "open",
        priority: null,
        parent_id: null,
        due_at: null,
        notes: item.reason || "",
      })));
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
      let item = currentWorkItems.find((row) => row.id === itemId);
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

      await api(`/v1/work_items/${itemId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `ui-work-item-edit-${itemId}-${Date.now()}`,
        },
        body: JSON.stringify({
          title: title.trim(),
          notes: notes.trim() || null,
          priority: normalizedPriority,
          due_at: isoFromLocal(due.trim()),
          parent_id: parentId.trim() || null,
        }),
      });
      await loadDashboard();
    }

    async function editReminder(reminderId) {
      let reminder = currentReminders.find((row) => row.id === reminderId);
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

      await api(`/v1/reminders/${reminderId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `ui-reminder-edit-${reminderId}-${Date.now()}`,
        },
        body: JSON.stringify({
          title: title.trim(),
          message: message.trim() || null,
          remind_at: isoFromLocal(remindAt.trim()),
          recurrence_rule: recurrence.trim() || null,
          kind: recurrence.trim() ? "recurring" : "one_off",
          work_item_id: workItemId.trim() || null,
        }),
      });
      await loadDashboard();
    }

    async function updateWorkItemStatus(itemId, nextStatus) {
      await api(`/v1/work_items/${itemId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `ui-work-item-update-${itemId}-${Date.now()}`,
        },
        body: JSON.stringify({ status: nextStatus }),
      });
      await loadDashboard();
    }

    async function updateReminderStatus(reminderId, nextStatus) {
      await api(`/v1/reminders/${reminderId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `ui-reminder-update-${reminderId}-${Date.now()}`,
        },
        body: JSON.stringify({ status: nextStatus }),
      });
      await loadDashboard();
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
      await loadDashboard();
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
      await loadDashboard();
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
      loadDashboard().catch((error) => setStatus(error.message, true));
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

    workItemsEl.addEventListener("click", (event) => {
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
      const versionsButton = event.target.closest("button[data-item-versions]");
      if (!versionsButton) return;
      loadWorkItemVersions(versionsButton.dataset.itemVersions).catch((error) => setStatus(error.message, true));
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

    if (bearerToken()) {
      loadDashboard().catch((error) => setStatus(error.message, true));
    }
  </script>
</body>
</html>
"""


def render_maintenance_ui(token: Optional[str]) -> str:
    return _MAINTENANCE_UI_TEMPLATE.replace("__TOKEN_JSON__", json.dumps(token or ""))
