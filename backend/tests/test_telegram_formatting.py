"""Phase 4 Telegram formatting tests (spec case 10)."""
from datetime import date, datetime, timezone
from unittest.mock import patch

from common.telegram import (
    build_applied_reply_markup, escape_html, format_action_batch_details, format_today_plan, format_focus_mode, format_urgent_tasks, format_open_tasks, format_due_today, format_due_next_week, format_query_answer, format_capture_ack,
    split_telegram_text, strip_internal_ids, render_markdownish_text
)


class TestFormattersEscapeHtmlContent:
    """User-supplied content is escaped; structural Telegram HTML tags preserved."""

    def test_format_today_plan_escapes_titles_and_reasons(self):
        payload = {
            "today_plan": [
                {
                    "task_id": "tsk_<1>",
                    "rank": 1,
                    "title": "Fix <br> bug & test",
                    "reason": "Due <soon>",
                },
            ],
            "blocked_items": [
                {
                    "task_id": "tsk_2",
                    "title": "Deploy & monitor",
                    "blocked_by": ["<dependency>"],
                },
            ],
        }
        result = format_today_plan(payload)

        # User content escaped
        assert "&lt;br&gt;" in result
        assert "&amp; test" in result
        assert "&lt;soon&gt;" in result
        assert "&lt;dependency&gt;" in result

        # No raw HTML leaked from user content
        assert "<br>" not in result
        assert "<soon>" not in result
        assert "<dependency>" not in result

        # Structural Telegram tags preserved
        assert "<b>" in result
        assert "<i>" in result

    def test_format_focus_mode_escapes_titles(self):
        payload = {
            "today_plan": [
                {"task_id": "tsk_<1>", "title": "Task <with> special & chars"},
            ],
        }
        result = format_focus_mode(payload)

        assert "&lt;with&gt;" in result
        assert "&amp;" in result
        assert "<with>" not in result

    def test_format_today_plan_includes_human_freshness_line(self):
        payload = {"generated_at": "2026-03-18T18:40:00Z", "today_plan": []}
        with patch("common.telegram._utc_now", return_value=datetime(2026, 3, 18, 18, 40, 30, tzinfo=timezone.utc)):
            result = format_today_plan(payload)
        assert "Updated just now" in result
        assert "Mar 18" in result

    def test_format_today_plan_includes_due_reminders_section(self):
        payload = {
            "generated_at": "2026-03-18T18:40:00Z",
            "today_plan": [{"task_id": "tsk_1", "title": "Register for the 401k plan", "kind": "task"}],
            "due_reminders": [
                {
                    "reminder_id": "rem_1",
                    "title": "Follow up with Patrick",
                    "remind_at": "2026-03-18T19:15:00Z",
                    "message": "Check if the payroll email arrived.",
                }
            ],
        }
        result = format_today_plan(payload)
        assert "Due Reminders" in result
        assert "Follow up with Patrick" in result
        assert "Details: Check if the payroll email arrived." in result
        assert "local" not in result

    def test_format_focus_mode_marks_stale_cached_plan(self):
        payload = {
            "generated_at": "2026-03-18T18:40:00Z",
            "_served_from_cache": True,
            "today_plan": [{"task_id": "tsk_1", "title": "Task A"}],
        }
        with patch("common.telegram._utc_now", return_value=datetime(2026, 3, 18, 18, 50, 0, tzinfo=timezone.utc)):
            result = format_focus_mode(payload)
        assert "Updated 10 mins ago from cached plan" in result

    def test_format_focus_mode_empty_state_is_not_command_dependent(self):
        assert format_focus_mode({"today_plan": []}) == "Nothing to focus on right now."

    def test_format_urgent_tasks_lists_due_dates(self):
        with patch("common.telegram._utc_now", return_value=datetime(2026, 3, 26, 12, 0, 0, tzinfo=timezone.utc)):
            rendered = format_urgent_tasks(
                [
                    {"id": "tsk_1", "title": "Register for the 401k plan", "kind": "task", "due_date": "2026-03-25"},
                    {"id": "tsk_2", "title": "Submit payroll correction", "due_date": None},
                ]
            )
        assert "Urgent Items" in rendered
        assert "Register for the 401k plan" in rendered
        assert "Due 3/25/2026 (1 day overdue)" in rendered
        assert "Submit payroll correction" in rendered

    def test_format_open_tasks_groups_projects_and_nested_children(self):
        with patch("common.telegram._utc_now", return_value=datetime(2026, 3, 26, 12, 0, 0, tzinfo=timezone.utc)):
            rendered = format_open_tasks(
                [
                    {"id": "wki_1", "title": "Get glasses at Warby Parker", "kind": "project", "status": "open", "due_date": None, "parent_id": None},
                    {"id": "tsk_1", "title": "Schedule appointment at Warby Parker store", "kind": "task", "status": "open", "due_date": None, "parent_id": "wki_1"},
                    {"id": "tsk_2", "title": "Measure pupillary distance (PD)", "kind": "subtask", "status": "blocked", "due_date": "2026-03-25", "parent_id": "tsk_1"},
                    {"id": "tsk_3", "title": "Wash my car", "kind": "task", "status": "open", "due_date": "2026-03-26", "parent_id": None},
                ]
            )
        assert "Open Tasks" in rendered
        assert "<b>Projects</b>" in rendered
        assert "▣ Get glasses at Warby Parker" in rendered
        assert "- Schedule appointment at Warby Parker store" in rendered
        assert "- Measure pupillary distance (PD)" in rendered
        assert "<b>Tasks</b>" in rendered
        assert "Wash my car" in rendered
        assert "Due 3/25/2026 (1 day overdue)" in rendered
        assert "Due 3/26/2026 (today)" in rendered
        assert "blocked" in rendered

    def test_format_due_today_lists_tasks_and_reminders(self):
        rendered = format_due_today(
            [
                {"id": "wki_1", "title": "Finish registering the 401k account", "kind": "project", "status": "open"},
                {"id": "tsk_2", "title": "Review Neil's list", "kind": "subtask", "status": "blocked"},
            ],
            [
                {
                    "id": "rem_1",
                    "title": "Check on Patrick",
                    "remind_at": "2026-03-26T13:00:00Z",
                    "message": "Send the follow-up text.",
                }
            ],
        )
        assert "Due Today" in rendered
        assert "▣ Finish registering the 401k account" in rendered
        assert "- Review Neil's list" in rendered
        assert "blocked" in rendered
        assert "Due Reminders" in rendered
        assert "Check on Patrick" in rendered
        assert "Details: Send the follow-up text." in rendered

    def test_format_due_today_suppresses_duplicate_reminder_body(self):
        rendered = format_due_today(
            [],
            [
                {
                    "id": "rem_1",
                    "title": "Tell Callum about the Telegram Todo app",
                    "remind_at": "2026-03-26T23:00:00Z",
                    "message": "Tell Callum about the Telegram Todo app",
                }
            ],
        )
        assert "Tell Callum about the Telegram Todo app" in rendered
        assert "Details:" not in rendered

    def test_format_due_today_empty_state(self):
        rendered = format_due_today([], [])
        assert "Nothing is due today." in rendered

    def test_format_due_next_week_lists_tasks_and_reminders(self):
        with patch("common.telegram._local_today", return_value=date(2026, 3, 26)):
            rendered = format_due_next_week(
                [
                    {"id": "wki_1", "title": "Sign up for a Vanguard investment account", "kind": "project", "status": "open", "due_date": "2026-03-31"},
                    {"id": "tsk_2", "title": "Deposit money into Roth IRA account", "kind": "task", "status": "open", "due_date": "2026-03-31"},
                ],
                [
                    {
                        "id": "rem_1",
                        "title": "Check New York filing deadline",
                        "remind_at": "2026-04-01T13:00:00Z",
                        "message": "Confirm whether the state filing is due Wednesday.",
                    }
                ],
                week_label="Week of 3/30/2026",
            )
        assert "Due Next Week" in rendered
        assert "Week of 3/30/2026" in rendered
        assert "▣ Sign up for a Vanguard investment account" in rendered
        assert "Deposit money into Roth IRA account" in rendered
        assert "Due 3/31/2026 (in 5 days)" in rendered
        assert "Due Reminders" in rendered
        assert "Check New York filing deadline" in rendered
        assert "Details: Confirm whether the state filing is due Wednesday." in rendered
        assert "&nbsp;" not in rendered

    def test_format_due_next_week_empty_state(self):
        rendered = format_due_next_week([], [], week_label="Week of 3/30/2026")
        assert "Nothing is due next week." in rendered

    def test_format_today_plan_normalizes_wrapper_task_title(self):
        payload = {
            "today_plan": [
                {"task_id": "tsk_1", "title": "Move 'Complete Worker\\'s Compensation form for employee' to today", "kind": "task"},
            ],
        }
        result = format_today_plan(payload)
        assert "Complete Worker" in result
        assert "Move &#x27;" not in result
        assert "to today" not in result

    def test_format_today_plan_marks_projects(self):
        payload = {
            "today_plan": [
                {"task_id": "wki_1", "title": "Get glasses at Warby Parker", "kind": "project"},
            ],
        }
        result = format_today_plan(payload)
        assert "▣ Get glasses at Warby Parker" in result

    def test_due_date_text_uses_us_format_and_relative_window(self):
        with patch("common.telegram._utc_now", return_value=datetime(2026, 3, 26, 12, 0, 0, tzinfo=timezone.utc)):
            rendered = format_urgent_tasks(
                [
                    {"id": "tsk_today", "title": "Today item", "kind": "task", "due_date": "2026-03-26"},
                    {"id": "tsk_tomorrow", "title": "Tomorrow item", "kind": "task", "due_date": "2026-03-27"},
                    {"id": "tsk_window", "title": "Window item", "kind": "task", "due_date": "2026-04-07"},
                    {"id": "tsk_far", "title": "Far item", "kind": "task", "due_date": "2026-04-20"},
                ]
            )
        assert "Due 3/26/2026 (today)" in rendered
        assert "Due 3/27/2026 (tomorrow)" in rendered
        assert "Due 4/7/2026 (in 12 days)" in rendered
        assert "Due 4/20/2026" in rendered
        assert "Due 4/20/2026 (" not in rendered

    def test_escape_html_covers_required_chars(self):
        assert escape_html("<") == "&lt;"
        assert escape_html(">") == "&gt;"
        assert escape_html("&") == "&amp;"
        assert escape_html("safe text") == "safe text"

    def test_format_capture_ack_prefers_itemized_summary(self):
        result = format_capture_ack(
            {
                "tasks_created": 1,
                "tasks_updated": 2,
                "items": [
                    {"group": "completed", "label": "Remind Amy about the backpack"},
                    {"group": "updated", "label": "Reach out to Ben and Jason"},
                    {"group": "created", "label": "Decide our intentions regarding Ginseng ordering"},
                ],
            }
        )
        assert "Done" in result
        assert "Completed" in result
        assert "Updated" in result
        assert "Created" in result
        assert "1 task(s) created" not in result

    def test_format_capture_ack_normalizes_wrapper_labels(self):
        result = format_capture_ack(
            {
                "items": [
                    {"group": "completed", "label": "Move 'Complete Worker's Compensation form for employee' to today"},
                ]
            }
        )
        assert "Complete Worker's Compensation form for employee" in result
        assert "Move &#x27;Complete Worker" not in result

    def test_format_capture_ack_includes_reminder_sections(self):
        result = format_capture_ack(
            {
                "reminders_created": 1,
                "reminders_updated": 2,
                "items": [
                    {"group": "reminder_created", "label": "Call Patrick"},
                    {"group": "reminder_completed", "label": "Follow up with accountant"},
                    {"group": "reminder_updated", "label": "Check New York filing deadline"},
                ],
            }
        )
        assert "Reminders created" in result
        assert "Reminders completed" in result
        assert "Reminders updated" in result
        assert "Call Patrick" in result
        assert "reminder(s) created" not in result

    def test_build_applied_reply_markup_offers_show_more_and_subtasks(self):
        markup = build_applied_reply_markup(
            {
                "items": [{"group": "created", "label": f"Task {idx}"} for idx in range(8)],
                "work_item_action_batch_id": "abt_123",
                "work_item_subtasks_count": 4,
            }
        )
        assert markup is not None
        labels = [button["text"] for row in markup["inline_keyboard"] for button in row]
        assert "Show more" in labels
        assert "Show subtasks" in labels

    def test_format_action_batch_details_groups_project_and_subtask_records(self):
        text = format_action_batch_details(
            [
                {
                    "operation": "create",
                    "after_json": {"kind": "project", "title": "Get glasses at Warby Parker"},
                    "before_json": {},
                },
                {
                    "operation": "create",
                    "after_json": {"kind": "subtask", "title": "Measure pupillary distance (PD)"},
                    "before_json": {},
                },
            ],
            heading="All task changes",
        )
        assert "All task changes" in text
        assert "Project: Get glasses at Warby Parker" in text
        assert "Subtask: Measure pupillary distance (PD)" in text

    def test_format_query_answer_escapes_dynamic_content(self):
        answer = "Use <script>alert(1)</script> & keep moving."
        follow_up = "Need <more> details?"
        result = format_query_answer(answer, follow_up)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result
        assert "&amp; keep moving." in result
        assert "&lt;more&gt; details?" in result
        assert "<script>" not in result

    def test_format_query_answer_strips_internal_ids(self):
        answer = "Open tasks: Do French homework [tsk_09847f2cf427], Memorize a script (tsk_481377db4bff), and tsk_10d09b42639c."
        result = format_query_answer(answer)
        assert "tsk_09847f2cf427" not in result
        assert "tsk_481377db4bff" not in result
        assert "tsk_10d09b42639c" not in result

    def test_strip_internal_ids_removes_known_prefixes(self):
        text = "Task [tsk_123] supports goal (gol_456) and problem prb_789."
        cleaned = strip_internal_ids(text)
        assert cleaned == "Task supports goal and problem."

    def test_render_markdownish_text_converts_bold(self):
        rendered = render_markdownish_text("Top priority: **Plan Tuesday dinner** tonight.")
        assert "<b>Plan Tuesday dinner</b>" in rendered
        assert "**Plan Tuesday dinner**" not in rendered

    def test_render_markdownish_text_escapes_html_inside_bold(self):
        rendered = render_markdownish_text("Use **<script>alert(1)</script>** safely.")
        assert "<b>&lt;script&gt;alert(1)&lt;/script&gt;</b>" in rendered
        assert "<script>" not in rendered

    def test_split_telegram_text_preserves_full_content(self):
        text = ("A" * 2000) + "\n" + ("B" * 2000) + "\n" + ("C" * 2000)
        chunks = split_telegram_text(text, max_len=4096)
        assert len(chunks) == 2
        assert "".join(chunks) == text

    def test_split_telegram_text_splits_single_long_line(self):
        text = "x" * 9000
        chunks = split_telegram_text(text, max_len=4096)
        assert len(chunks) == 3
        assert "".join(chunks) == text
