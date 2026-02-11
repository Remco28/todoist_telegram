from datetime import timedelta

from api.main import _infer_urgency_score, utc_now


def test_infer_urgency_from_due_date_overdue_or_today():
    today = utc_now().date()
    assert _infer_urgency_score(today, None) == 5
    assert _infer_urgency_score(today - timedelta(days=1), None) == 5


def test_infer_urgency_combines_due_and_priority():
    future = utc_now().date() + timedelta(days=10)
    # due date alone suggests low urgency, but local priority=1 should raise it.
    assert _infer_urgency_score(future, 1) == 4
    assert _infer_urgency_score(future, 4) == 2
