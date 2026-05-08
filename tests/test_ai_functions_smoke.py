"""Smoke tests for algorithms.ai_functions helpers that don't hit the network.

The module's network-bound functions (generate / review / polish / etc.) are
indirectly exercised by tests/test_ai_functions_retry.py. Here we pin the
pure helpers: prompt assembly, guidance selection, code extraction, helper
injection, and the codex-vs-chat model predicate.
"""

from __future__ import annotations

from algorithms import ai_functions


def test_is_codex_model_detects_codex_variants():
    assert ai_functions._is_codex_model("gpt-5.2-codex")
    assert ai_functions._is_codex_model("CODEX-experimental")
    assert not ai_functions._is_codex_model("gpt-4o-mini")
    assert not ai_functions._is_codex_model("")
    assert not ai_functions._is_codex_model(None)  # type: ignore[arg-type]


def test_extract_code_strips_python_fenced_block():
    payload = "preamble\n```python\nfrom manim import *\n\nclass S(Scene): pass\n```\ntrailing"
    out = ai_functions.extract_code(payload)
    assert out.startswith("from manim import *")
    assert "```" not in out
    assert "trailing" not in out


def test_extract_code_strips_bare_fenced_block():
    payload = "```\nprint('hello')\n```"
    out = ai_functions.extract_code(payload)
    assert "print('hello')" in out
    assert "```" not in out


def test_extract_code_returns_input_when_no_fence():
    plain = "from manim import *\n\nclass S(Scene): pass"
    assert ai_functions.extract_code(plain) == plain


def test_inject_helpers_inserts_right_after_manim_import():
    code = "from manim import *\n\nclass Scene1(Scene):\n    pass\n"
    out = ai_functions.inject_helpers(code)
    assert out.startswith("from manim import *\n")
    assert ai_functions.LAYOUT_HELPERS in out
    # Helpers must land BEFORE the Scene class so its methods can see them.
    assert out.index(ai_functions.LAYOUT_HELPERS) < out.index("class Scene1")


def test_inject_helpers_prepends_when_no_manim_import():
    code = "class S:\n    pass\n"
    out = ai_functions.inject_helpers(code)
    assert out.startswith(ai_functions.LAYOUT_HELPERS)
    assert out.endswith("class S:\n    pass\n")


def test_domain_specific_guidance_is_nonempty_for_known_domains():
    for domain in ("math", "physics", "computer_science", "chemistry"):
        guidance = ai_functions.get_domain_specific_guidance(domain)
        assert guidance.strip(), f"{domain} guidance unexpectedly blank"


def test_domain_specific_guidance_returns_empty_for_unknown_domain():
    assert ai_functions.get_domain_specific_guidance("biology") == ""
    assert ai_functions.get_domain_specific_guidance("") == ""


def test_get_error_warnings_safely_handles_missing_or_unavailable_db():
    class _DB:
        available = False

    assert ai_functions.get_error_warnings(None) == ""
    assert ai_functions.get_error_warnings(_DB()) == ""
