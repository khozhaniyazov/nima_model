"""Smoke tests for `config` — fail-fast behavior and env→attribute resolution.

These guard against regressions in:
  - The "config.py is the only env reader" rule (CONTRIBUTING.md).
  - The fail-fast on USE_DATABASE=true without DB_CONNECTION_STRING.
"""
from __future__ import annotations

import importlib
import sys

import pytest


def _reload_config(monkeypatch, env: dict[str, str]):
    """Reload the `config` module under a fresh environment.

    We need a real reload (not just `import config`) because env reads happen
    at import time. Each test wipes its own `config` from `sys.modules` so the
    surrounding test session's cached config is not disturbed. We also stub
    `dotenv.load_dotenv` so a developer's local `.env` file (which may set
    e.g. DB_CONNECTION_STRING) doesn't bleed into these tests.
    """
    # Wipe relevant env vars so this test is hermetic regardless of caller env.
    for key in (
        "USE_DATABASE",
        "DB_CONNECTION_STRING",
        "STREAM_PROVIDER_USE_SUBPROCESS",
        "STREAM_PROVIDER_FAILURE_COOLDOWN",
        "REQUEST_ANALYSIS_USE_SUBPROCESS",
        "EDGE_TTS_VOICE",
    ):
        monkeypatch.delenv(key, raising=False)
    # OPENAI_API_KEY is required for downstream imports; keep it set.
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Neutralize .env loading inside config.py so tests are hermetic.
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    sys.modules.pop("config", None)
    return importlib.import_module("config")


def test_use_database_without_connection_string_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="DB_CONNECTION_STRING"):
        _reload_config(monkeypatch, {"USE_DATABASE": "true"})
    # Restore a safe config for any later tests in the session.
    _reload_config(monkeypatch, {"USE_DATABASE": "false"})


def test_use_database_false_does_not_require_connection_string(monkeypatch):
    cfg = _reload_config(monkeypatch, {"USE_DATABASE": "false"})
    assert cfg.USE_DATABASE is False
    assert cfg.DB_CONNECTION_STRING == ""


def test_streaming_subprocess_flag_default_true(monkeypatch):
    cfg = _reload_config(monkeypatch, {"USE_DATABASE": "false"})
    assert cfg.STREAM_PROVIDER_USE_SUBPROCESS is True


def test_streaming_subprocess_flag_can_be_disabled(monkeypatch):
    cfg = _reload_config(
        monkeypatch,
        {"USE_DATABASE": "false", "STREAM_PROVIDER_USE_SUBPROCESS": "false"},
    )
    assert cfg.STREAM_PROVIDER_USE_SUBPROCESS is False


def test_request_analysis_timeout_is_int(monkeypatch):
    cfg = _reload_config(
        monkeypatch,
        {"USE_DATABASE": "false", "REQUEST_ANALYSIS_TIMEOUT": "42"},
    )
    assert cfg.REQUEST_ANALYSIS_TIMEOUT == 42


def test_request_analysis_timeout_handles_zero_openai_timeout(monkeypatch):
    """OPENAI_TIMEOUT=0 should not clamp planning timeout to floor (10s).

    The fallback expression is `min(OPENAI_TIMEOUT or 60, 60)`; the `or 60`
    guards against the degenerate `OPENAI_TIMEOUT=0` case, which would
    otherwise produce a 10s planning timeout via `max(10, 0)`.
    """
    cfg = _reload_config(
        monkeypatch,
        {"USE_DATABASE": "false", "OPENAI_TIMEOUT": "0"},
    )
    assert cfg.REQUEST_ANALYSIS_TIMEOUT == 60


def test_edge_tts_voice_env_override(monkeypatch):
    cfg = _reload_config(
        monkeypatch,
        {"USE_DATABASE": "false", "EDGE_TTS_VOICE": "en-GB-RyanNeural"},
    )
    assert cfg.EDGE_TTS_VOICE == "en-GB-RyanNeural"
