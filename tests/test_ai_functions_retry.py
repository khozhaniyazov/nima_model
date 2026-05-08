"""Retry-loop regression tests for algorithms.ai_functions._llm_text_with_retry.

Two behaviors to pin:

1. On a 524, the fallback endpoint is tried exactly once across the entire
   retry loop (previously it was thrashed on every retry because
   `used_fallback = False` was reset inside the except branch).
2. Non-524 errors never touch the fallback endpoint — they just exponentially
   back off and retry the primary.

The LLM clients are monkey-patched to record calls without hitting the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from algorithms import ai_functions


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = MagicMock(content=content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Don't actually sleep between retries during the test."""
    monkeypatch.setattr(ai_functions.time, "sleep", lambda _s: None)


def _install_primary_always_524(monkeypatch):
    """Primary endpoint always raises a 524-flavored error."""
    primary = MagicMock()
    primary.chat.completions.create.side_effect = Exception(
        "bad_response_status_code 524"
    )
    monkeypatch.setattr(ai_functions, "client", primary)
    return primary


def test_fallback_endpoint_tried_exactly_once_across_retry_loop(monkeypatch):
    primary = _install_primary_always_524(monkeypatch)

    fallback = MagicMock()
    fallback.chat.completions.create.side_effect = Exception("fallback also dead")
    monkeypatch.setattr(ai_functions, "fallback_client", fallback)

    with pytest.raises(Exception, match="LLM call failed after 3 attempts"):
        ai_functions._llm_text_with_retry(
            [{"role": "user", "content": "hi"}], "gpt-test", max_retries=3
        )

    # Primary is called on every attempt…
    assert primary.chat.completions.create.call_count == 3
    # …but the fallback endpoint is called at most once even though every
    # primary attempt produces a 524. This pins the fix for the
    # `used_fallback = False` reset bug.
    assert fallback.chat.completions.create.call_count == 1


def test_fallback_success_short_circuits_retry_loop(monkeypatch):
    primary = _install_primary_always_524(monkeypatch)

    fallback = MagicMock()
    fallback.chat.completions.create.return_value = _FakeResponse("fallback-ok")
    monkeypatch.setattr(ai_functions, "fallback_client", fallback)

    result = ai_functions._llm_text_with_retry(
        [{"role": "user", "content": "hi"}], "gpt-test", max_retries=3
    )

    assert result == "fallback-ok"
    # The loop returns as soon as the fallback succeeds — primary is only hit
    # once before the fallback rescue, and fallback is only called once.
    assert primary.chat.completions.create.call_count == 1
    assert fallback.chat.completions.create.call_count == 1


def test_non_524_errors_do_not_touch_fallback(monkeypatch):
    primary = MagicMock()
    primary.chat.completions.create.side_effect = Exception("rate_limit_exceeded")
    monkeypatch.setattr(ai_functions, "client", primary)

    fallback = MagicMock()
    monkeypatch.setattr(ai_functions, "fallback_client", fallback)

    with pytest.raises(Exception, match="LLM call failed after 2 attempts"):
        ai_functions._llm_text_with_retry(
            [{"role": "user", "content": "hi"}], "gpt-test", max_retries=2
        )

    assert primary.chat.completions.create.call_count == 2
    # Fallback endpoint must never be consulted for non-524 failures — the
    # fallback path is reserved for gateway timeouts, not generic errors.
    assert fallback.chat.completions.create.call_count == 0
