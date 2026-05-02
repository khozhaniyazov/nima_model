"""Subprocess entry point for LLM provider generation.

Run as a child process by ``algorithms.streaming._generate_with_provider_subprocess``
so that timeout kills are real (the parent uses ``subprocess.run(..., timeout=...)``).

Invocation:
    python -X utf8 -m algorithms._streaming_child <payload_path> <output_path>

The payload JSON file must contain::

    {
        "api_key": str,
        "base_url": str | None,
        "model": str,
        "timeout": int,
        "stream": bool,
        "max_tokens": int,
        "messages": list[dict],
    }

The child writes the response content (or streamed chunks concatenated) to
``output_path`` as it arrives. On the ``Unsupported parameter: max_tokens``
class of 400 errors emitted by some upstream proxies, the child drops
``max_tokens`` from the request and retries exactly once. The retry is logged
to stdout so the parent's ``capture_output=True`` surfaces it in operator
logs.

This module deliberately has no side effects at import time so it can be
unit-tested. The CLI behavior is gated behind ``if __name__ == "__main__"``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


_MAX_TOKEN_HINTS = ("max_tokens", "max_completion_tokens", "max_output_tokens")
_MAX_TOKEN_REJECT_PHRASES = (
    "unsupported parameter",
    "unrecognized",
    "is not supported",
    "not allowed",
    "is not allowed",
    "not permitted",
)

_RETRY_LOG_LINE = (
    "[STREAM] child: provider rejected max_tokens; retrying without it"
)


def is_max_tokens_unsupported(exc: BaseException) -> bool:
    """Return True if ``exc`` looks like a 'reject max_tokens' error.

    Matches both the canonical OpenAI ``Unsupported parameter`` phrasing and
    the common Azure / proxy variants. The matcher requires both a rejection
    phrase AND a token-hint substring to keep false positives low.
    """
    msg = str(exc).lower()
    if not any(p in msg for p in _MAX_TOKEN_REJECT_PHRASES):
        return False
    return any(h in msg for h in _MAX_TOKEN_HINTS)


def create_with_retry(create, *, log=print, **kwargs: Any):
    """Call ``create(**kwargs)``; on a max_tokens rejection, drop the cap and retry once.

    ``create`` is any callable matching ``client.chat.completions.create`` —
    factored out of the hot path so this helper is trivial to unit-test
    against a fake.

    ``log`` is the line-emitter used to surface the retry. The default
    ``print`` writes to stdout so the parent's ``capture_output=True`` picks
    it up. Tests pass a list-append spy.
    """
    try:
        return create(**kwargs)
    except Exception as exc:
        if "max_tokens" in kwargs and is_max_tokens_unsupported(exc):
            kwargs.pop("max_tokens", None)
            log(_RETRY_LOG_LINE)
            return create(**kwargs)
        raise


def _extract_completion_text(response) -> str:
    """Pull the text content out of a non-streaming chat completion response.

    Some upstream proxies (observed in production with ``zjuapi.com`` / gpt-5.4
    on 2026-05-02, job ``smoke-course-be35f4``) return ``chat.completions.create
    (stream=False)`` as a raw ``str`` rather than a typed ``ChatCompletion``.
    Without a defensive shim, the next attribute access (``.choices[0]``) raises
    ``AttributeError: 'str' object has no attribute 'choices'``, which the
    parent surfaces as a misleading ``Empty or very short response (0 chars)``
    while silently triggering the deterministic fallback.

    This helper accepts the canonical typed shape, the raw-string shape, and
    a handful of dict-shaped variants seen in proxy responses, and raises a
    clear ``TypeError`` when none match so the parent can log something
    actionable instead of swallowing the trace.
    """
    if response is None:
        raise TypeError("provider returned None instead of a chat completion")
    if isinstance(response, str):
        # Raw text — proxy already unwrapped the completion. Caller writes
        # whatever the model emitted.
        return response
    if isinstance(response, dict):
        # OpenAI-shape dict: {"choices": [{"message": {"content": "..."}}]}.
        # Be permissive about a few common proxy aliases.
        choices = response.get("choices") or []
        if choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message") or {}
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content
                # Some proxies put the text directly on the choice.
                text = first.get("text")
                if isinstance(text, str):
                    return text
        # Bare ``{"content": "..."}`` — last-resort shape.
        content = response.get("content")
        if isinstance(content, str):
            return content
        raise TypeError(
            f"provider returned dict without recognised completion shape: keys={sorted(response)[:6]}"
        )
    # Typed ChatCompletion path. Guard against missing choices so a malformed
    # SDK object also surfaces a clean message instead of an IndexError.
    choices = getattr(response, "choices", None)
    if not choices:
        raise TypeError(
            f"provider response of type {type(response).__name__} has no usable choices"
        )
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    return content or ""


def write_response(response, output_path: Path, *, stream: bool) -> None:
    """Persist either a streamed chunk iterator or a single completion to disk."""
    with output_path.open("w", encoding="utf-8", errors="replace") as out:
        if stream:
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    out.write(chunk.choices[0].delta.content)
                    out.flush()
        else:
            out.write(_extract_completion_text(response))
            out.flush()


def run(payload_path: str, output_path: str) -> int:
    """CLI entry — load payload, call OpenAI, stream to output. Returns exit code."""
    from openai import OpenAI

    payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    client = OpenAI(
        api_key=payload["api_key"],
        base_url=payload.get("base_url"),
        timeout=payload.get("timeout") or 60,
    )

    def _create(**kwargs):
        # Stream flag is forwarded into the SDK call as-is.
        return client.chat.completions.create(**kwargs)

    def _stdout_flush(line: str) -> None:
        print(line, flush=True)

    response = create_with_retry(
        _create,
        log=_stdout_flush,
        model=payload["model"],
        messages=payload["messages"],
        stream=payload["stream"],
        max_tokens=payload["max_tokens"],
    )

    write_response(response, Path(output_path), stream=bool(payload["stream"]))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python -m algorithms._streaming_child <payload> <output>", file=sys.stderr)
        sys.exit(2)
    sys.exit(run(sys.argv[1], sys.argv[2]))
