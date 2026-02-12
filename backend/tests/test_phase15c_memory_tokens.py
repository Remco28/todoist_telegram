from common import memory
from common.config import settings


def test_token_estimator_mode_heuristic_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "MEMORY_PRECISE_TOKEN_ESTIMATOR", False)
    assert memory.token_estimator_mode() == "heuristic"


def test_token_estimator_mode_precise_when_available(monkeypatch):
    monkeypatch.setattr(settings, "MEMORY_PRECISE_TOKEN_ESTIMATOR", True)
    monkeypatch.setattr(memory, "_estimate_tokens_precise", lambda text: 7)
    assert memory.token_estimator_mode() == "precise_cl100k_base"
    assert memory.estimate_tokens("hello world") == 7


def test_token_estimator_mode_fallback_when_precise_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "MEMORY_PRECISE_TOKEN_ESTIMATOR", True)
    monkeypatch.setattr(memory, "_estimate_tokens_precise", lambda text: None)
    assert memory.token_estimator_mode() == "heuristic_fallback"
    # Heuristic fallback: len("abcdefghij") // 4 + 1 = 3
    assert memory.estimate_tokens("abcdefghij") == 3


def test_enforce_budget_includes_token_estimator_metadata(monkeypatch):
    monkeypatch.setattr(settings, "MEMORY_PRECISE_TOKEN_ESTIMATOR", False)
    result = memory.enforce_budget(
        policy="policy",
        summary="summary",
        hot_turns=["a", "b"],
        entities=["c"],
        query="hello",
        applied_max=500,
    )
    assert result["metadata"]["token_estimator"] == "heuristic"
    assert isinstance(result["metadata"]["estimated_used"], int)

