"""Unit tests for ``algorithms._streaming_child``.

The module is the production code path for LLM provider calls (the parent
``streaming.py`` invokes it as a subprocess via ``python -m
algorithms._streaming_child``). Before extraction this code lived inside an
inline heredoc and had zero coverage. These tests exercise the helpers
directly, plus a simulated end-to-end ``run()`` with a fake openai SDK
injected via ``sys.modules``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from algorithms import _streaming_child, streaming


# ---------------------------------------------------------------------------
# is_max_tokens_unsupported
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message, expected",
    [
        # Canonical OpenAI
        (
            "Error code: 400 - {'error': {'message': "
            "'Unsupported parameter: max_output_tokens', "
            "'type': 'invalid_request_error'}}",
            True,
        ),
        # Azure phrasing
        (
            "The parameter 'max_tokens' is not supported with this model. "
            "Use 'max_completion_tokens' instead.",
            True,
        ),
        # Proxy phrasing
        ("Parameter 'max_completion_tokens' is not allowed for this endpoint.", True),
        # Unrelated 400 — must NOT trigger
        (
            "Error code: 400 - {'error': {'message': 'Unsupported parameter: temperature'}}",
            False,
        ),
        # Generic timeout — no token hint at all
        ("Request timed out after 60s", False),
        # Has token hint but no rejection phrase — must not trigger
        ("max_tokens=2200", False),
    ],
)
def test_is_max_tokens_unsupported(message, expected):
    assert _streaming_child.is_max_tokens_unsupported(RuntimeError(message)) is expected


# ---------------------------------------------------------------------------
# create_with_retry
# ---------------------------------------------------------------------------


def test_create_with_retry_no_error_passes_through():
    calls = []

    def fake_create(**kwargs):
        calls.append(dict(kwargs))
        return "ok"

    out = _streaming_child.create_with_retry(
        fake_create, log=lambda _msg: None, model="m", max_tokens=2200
    )
    assert out == "ok"
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 2200


def test_create_with_retry_drops_max_tokens_and_retries():
    calls = []
    log_lines = []

    def fake_create(**kwargs):
        calls.append(dict(kwargs))
        if "max_tokens" in kwargs:
            raise RuntimeError(
                "Error code: 400 - {'error': {'message': "
                "'Unsupported parameter: max_output_tokens'}}"
            )
        return "retry-ok"

    out = _streaming_child.create_with_retry(
        fake_create, log=log_lines.append, model="m", max_tokens=2200
    )
    assert out == "retry-ok"
    assert len(calls) == 2
    assert "max_tokens" in calls[0]
    assert "max_tokens" not in calls[1]
    # log_lines should contain exactly one retry message.
    assert log_lines == [_streaming_child._RETRY_LOG_LINE]


def test_create_with_retry_propagates_unrelated_errors():
    def fake_create(**kwargs):
        raise RuntimeError("internal server error")

    with pytest.raises(RuntimeError, match="internal server error"):
        _streaming_child.create_with_retry(fake_create, log=lambda _: None, max_tokens=10)


def test_create_with_retry_propagates_when_no_max_tokens_in_kwargs():
    """If the caller didn't pass max_tokens we must NOT retry on the rejection."""

    def fake_create(**kwargs):
        raise RuntimeError("Unsupported parameter: max_tokens")

    with pytest.raises(RuntimeError, match="Unsupported parameter"):
        _streaming_child.create_with_retry(fake_create, log=lambda _: None, model="m")


def test_create_with_retry_does_not_loop_when_second_call_raises():
    """Bounded at one retry by construction."""
    calls = []

    def fake_create(**kwargs):
        calls.append(dict(kwargs))
        raise RuntimeError("Unsupported parameter: max_output_tokens")

    with pytest.raises(RuntimeError):
        _streaming_child.create_with_retry(
            fake_create, log=lambda _: None, max_tokens=2200
        )
    # First call has max_tokens, retry drops it, second call raises again — stop.
    assert len(calls) == 2
    assert "max_tokens" in calls[0]
    assert "max_tokens" not in calls[1]


# ---------------------------------------------------------------------------
# write_response
# ---------------------------------------------------------------------------


def _make_streamed_chunks(text: str, *, chunk_size: int = 8):
    chunks = []
    for i in range(0, len(text), chunk_size):
        delta = SimpleNamespace(content=text[i : i + chunk_size])
        choice = SimpleNamespace(delta=delta)
        chunks.append(SimpleNamespace(choices=[choice]))
    return chunks


def _make_final_response(text: str):
    msg = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


def test_write_response_streamed(tmp_path: Path):
    out = tmp_path / "out.txt"
    chunks = _make_streamed_chunks("from manim import *\nclass GeneratedScene(Scene): pass\n")
    _streaming_child.write_response(iter(chunks), out, stream=True)
    assert out.read_text(encoding="utf-8") == (
        "from manim import *\nclass GeneratedScene(Scene): pass\n"
    )


def test_write_response_streamed_skips_empty_deltas(tmp_path: Path):
    out = tmp_path / "out.txt"
    # Mix of empty and populated deltas — the openai SDK does emit empty ones.
    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="a"))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=""))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="b"))]),
    ]
    _streaming_child.write_response(iter(chunks), out, stream=True)
    assert out.read_text(encoding="utf-8") == "ab"


def test_write_response_non_streamed(tmp_path: Path):
    out = tmp_path / "out.txt"
    _streaming_child.write_response(
        _make_final_response("hello"), out, stream=False
    )
    assert out.read_text(encoding="utf-8") == "hello"


def test_write_response_non_streamed_handles_none_content(tmp_path: Path):
    out = tmp_path / "out.txt"
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
    )
    _streaming_child.write_response(response, out, stream=False)
    assert out.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# run() with a fake openai SDK injected
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_openai(monkeypatch):
    """Inject a fake ``openai`` module into ``sys.modules`` for the duration of the test."""
    seen = {"calls": []}

    class _Completions:
        def create(self, **kwargs):
            seen["calls"].append(dict(kwargs))
            if seen["calls"][0].get("_first_call_should_fail"):
                # Pop the trigger so the retry succeeds.
                seen["calls"][0].pop("_first_call_should_fail", None)
                raise RuntimeError(
                    "Error code: 400 - {'error': {'message': "
                    "'Unsupported parameter: max_output_tokens'}}"
                )
            if kwargs.get("stream"):
                return _make_streamed_chunks("hello")
            return _make_final_response("hello-final")

    class _Chat:
        completions = _Completions()

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None, timeout=None):
            self.api_key = api_key
            self.base_url = base_url
            self.timeout = timeout
            self.chat = _Chat()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    return seen


def test_run_streamed(tmp_path: Path, fake_openai):
    payload = {
        "api_key": "k",
        "base_url": "http://example",
        "model": "gpt-test",
        "timeout": 30,
        "stream": True,
        "max_tokens": 2200,
        "messages": [{"role": "user", "content": "hi"}],
    }
    payload_path = tmp_path / "payload.json"
    output_path = tmp_path / "output.txt"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    rc = _streaming_child.run(str(payload_path), str(output_path))

    assert rc == 0
    assert output_path.read_text(encoding="utf-8") == "hello"
    assert len(fake_openai["calls"]) == 1
    assert fake_openai["calls"][0]["model"] == "gpt-test"
    assert fake_openai["calls"][0]["stream"] is True


def test_run_non_streamed(tmp_path: Path, fake_openai):
    payload = {
        "api_key": "k",
        "base_url": None,
        "model": "gpt-test",
        "timeout": 30,
        "stream": False,
        "max_tokens": 2200,
        "messages": [{"role": "user", "content": "hi"}],
    }
    payload_path = tmp_path / "payload.json"
    output_path = tmp_path / "output.txt"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    rc = _streaming_child.run(str(payload_path), str(output_path))

    assert rc == 0
    assert output_path.read_text(encoding="utf-8") == "hello-final"


# ---------------------------------------------------------------------------
# Real subprocess smoke: `python -m algorithms._streaming_child` from cwd
# ---------------------------------------------------------------------------


def test_module_invokable_via_dash_m_prints_usage():
    """`python -m algorithms._streaming_child` must resolve from project root.

    Verifies the parent's `-m` plus `cwd=project_root` plumbing is correct
    end-to-end. With no args the module exits 2 and writes 'usage:' to stderr.
    """
    project_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "algorithms._streaming_child"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Parent plumbing: cwd forwarding + child [STREAM] stdout re-emission
# ---------------------------------------------------------------------------


def test_subprocess_invocation_uses_dash_m_and_project_root_cwd(monkeypatch, capsys):
    """`_generate_with_provider_subprocess` must spawn child with -m and cwd=project_root."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["cwd"] = kwargs.get("cwd")
        captured["timeout"] = kwargs.get("timeout")
        captured["capture_output"] = kwargs.get("capture_output")
        # Pretend the child wrote nothing to the output file; we won't read
        # output content because we monkeypatch tempfile to a known dir below.
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(streaming.subprocess, "run", fake_run)
    # Make the fake openai import a no-op so payload construction succeeds.
    monkeypatch.setattr(streaming, "STREAM_PROVIDER", "zjuapi")
    streaming._PROVIDER_COOLDOWNS.clear()
    monkeypatch.setitem(streaming.STREAM_PROVIDERS["zjuapi"], "api_key", "k")
    monkeypatch.setitem(streaming.STREAM_PROVIDERS["zjuapi"], "base_url", "zju")

    context = streaming.NarrativeContext(prompt="demo", domain="math")
    streaming._generate_with_provider_subprocess(
        "make code", context, "zjuapi", stream=False
    )

    cmd = captured["cmd"]
    assert cmd[0] == sys.executable
    assert "-m" in cmd
    m_idx = cmd.index("-m")
    assert cmd[m_idx + 1] == "algorithms._streaming_child"
    project_root = Path(streaming.__file__).resolve().parent.parent
    assert captured["cwd"] == str(project_root)
    assert captured["capture_output"] is True


def test_parent_reemits_child_stream_stdout_lines(monkeypatch, capsys):
    """Parent must scan child stdout and re-emit any `[STREAM]`-prefixed line."""

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "boring noise\n"
                "[STREAM] child: provider rejected max_tokens; retrying without it\n"
                "more noise\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(streaming.subprocess, "run", fake_run)
    monkeypatch.setattr(streaming, "STREAM_PROVIDER", "zjuapi")
    streaming._PROVIDER_COOLDOWNS.clear()
    monkeypatch.setitem(streaming.STREAM_PROVIDERS["zjuapi"], "api_key", "k")
    monkeypatch.setitem(streaming.STREAM_PROVIDERS["zjuapi"], "base_url", "zju")

    context = streaming.NarrativeContext(prompt="demo", domain="math")
    streaming._generate_with_provider_subprocess(
        "make code", context, "zjuapi", stream=False
    )

    out = capsys.readouterr().out
    assert "[STREAM] child: provider rejected max_tokens" in out
    assert "boring noise" not in out
    assert "more noise" not in out
