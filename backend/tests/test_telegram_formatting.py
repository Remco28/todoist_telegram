"""Phase 4 Telegram formatting tests (spec case 10)."""
from common.telegram import (
    escape_html, format_today_plan, format_focus_mode,
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
        assert "<code>" in result
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

    def test_escape_html_covers_required_chars(self):
        assert escape_html("<") == "&lt;"
        assert escape_html(">") == "&gt;"
        assert escape_html("&") == "&amp;"
        assert escape_html("safe text") == "safe text"
