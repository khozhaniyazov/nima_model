"""Smoke tests for algorithms.template_registry.

This module is a pure-data layout registry plus a keyword-based `choose_template`
router. The goal here is not to pin the exact keyword mapping (it evolves) but
to guarantee the contract the rest of the pipeline relies on:

- every key in TEMPLATES has the required structural fields
- `choose_template` always returns either None or a key that actually exists in
  TEMPLATES, for every domain the router knows about
- unknown domains never crash; they return None
"""

from __future__ import annotations

import pytest

from algorithms.template_registry import TEMPLATES, choose_template


REQUIRED_KEYS = {"name", "slots", "beats", "notes"}


def test_every_template_has_required_fields():
    assert TEMPLATES, "registry must not be empty"
    for key, spec in TEMPLATES.items():
        missing = REQUIRED_KEYS - set(spec)
        assert not missing, f"template {key!r} missing {sorted(missing)}"
        assert isinstance(spec["slots"], list) and spec["slots"], (
            f"template {key!r} slots must be a non-empty list"
        )
        assert isinstance(spec["beats"], int) and spec["beats"] > 0, (
            f"template {key!r} beats must be a positive int"
        )
        assert isinstance(spec["notes"], str) and spec["notes"].strip(), (
            f"template {key!r} notes must be a non-empty string"
        )


@pytest.mark.parametrize(
    "prompt,domain",
    [
        ("derivative of sin(x) at x=0", "math"),
        ("prove that sqrt(2) is irrational", "math"),
        ("area under the curve y=x^2", "math"),
        ("linear transformation of a matrix", "math"),
        ("bubble sort step by step", "computer_science"),
        ("dfs traversal of a binary tree", "computer_science"),
        ("sine wave propagation", "physics"),
        ("oscillation of a pendulum", "physics"),
        ("reaction mechanism of an organic bond", "chemistry"),
        ("electron orbital shell", "chemistry"),
    ],
)
def test_choose_template_returns_a_real_registry_key(prompt, domain):
    picked = choose_template(prompt, domain)
    assert picked is None or picked in TEMPLATES, (
        f"choose_template({prompt!r}, {domain!r}) returned {picked!r} "
        f"which is not a registered template"
    )


@pytest.mark.parametrize("domain", ["", "unknown", "biology", "literature", None])
def test_choose_template_returns_none_for_unsupported_domains(domain):
    assert choose_template("anything at all", domain) is None


def test_choose_template_handles_empty_prompt():
    # The router is keyword-based and must not crash on an empty input; a
    # blank prompt can legitimately mean "no template match yet".
    assert choose_template("", "math") is None
    assert choose_template(None, "math") is None  # type: ignore[arg-type]
