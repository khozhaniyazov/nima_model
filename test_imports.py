"""Quick import and wiring verification — run with: python test_imports.py"""
import os
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["USE_DATABASE"] = "false"

# ── config ────────────────────────────────────────────────────────────────────
import config
assert config.GENERATION_MODEL == "gpt-4o", "Wrong model"
assert config.FAST_MODEL == "gpt-4o-mini", "Wrong fast model"
print(f"[OK] config — GENERATION_MODEL={config.GENERATION_MODEL}, FAST_MODEL={config.FAST_MODEL}")

# ── error_parser ──────────────────────────────────────────────────────────────
from algorithms.error_parser import parse_manim_error, format_error_for_prompt

# Test AttributeError
sample = (
    "Traceback (most recent call last):\n"
    '  File "test.py", line 42, in construct\n'
    "    self.play(Create(axes))\n"
    "AttributeError: 'Axes' object has no attribute 'foo'\n"
)
parsed = parse_manim_error(sample)
assert parsed["error_type"] == "AttributeError", f"Got {parsed['error_type']}"
assert parsed["line_number"] == 42, f"Got {parsed['line_number']}"
print(f"[OK] error_parser AttributeError — type={parsed['error_type']}, line={parsed['line_number']}")

# Test new CairoError
cairo_sample = "cairo.Error: Invalid matrix (not invertible)\n"
parsed_cairo = parse_manim_error(cairo_sample)
assert parsed_cairo["error_type"] == "CairoError", f"Expected CairoError, got {parsed_cairo['error_type']}"
print(f"[OK] error_parser CairoError — type={parsed_cairo['error_type']}")

# Test AnimationError
anim_sample = "There are no animations\n"
parsed_anim = parse_manim_error(anim_sample)
assert parsed_anim["error_type"] == "AnimationError", f"Expected AnimationError, got {parsed_anim['error_type']}"
print(f"[OK] error_parser AnimationError — type={parsed_anim['error_type']}")

# Test LaTeX emergency stop
latex_sample = "! Emergency stop.\nl.3 \\begin{"
parsed_latex = parse_manim_error(latex_sample)
assert parsed_latex["error_type"] == "LaTeXError", f"Expected LaTeXError, got {parsed_latex['error_type']}"
print(f"[OK] error_parser LaTeXError (emergency stop) — type={parsed_latex['error_type']}")

# ── code_digest ───────────────────────────────────────────────────────────────
from algorithms.code_digest import (
    ensure_scene_class, validate_python_syntax,
    validate_names_and_imports, validate_manim_code, check_code_quality
)

# Basic syntax check
test_code = (
    "from manim import *\n"
    "class GeneratedScene(Scene):\n"
    "    def construct(self):\n"
    "        self.play(Create(Circle()))\n"
    "        self.wait(3)\n"
)
ok, err = validate_python_syntax(test_code)
assert ok, f"Syntax error: {err}"
print(f"[OK] code_digest — syntax valid={ok}")

# Structure check - now requires self.play()
ok_struct, err_struct = validate_manim_code(test_code)
assert ok_struct, f"Structure error: {err_struct}"
print(f"[OK] code_digest — structure valid={ok_struct}")

# Safety check — SAFE code
is_safe, issues = validate_names_and_imports(test_code)
assert is_safe, f"False positive safety flag: {issues}"
print(f"[OK] code_digest — safe code correctly passes AST check")

# Safety check — DANGEROUS code (os.system)
bad_code = "import os\nfrom manim import *\nclass GeneratedScene(Scene):\n    def construct(self):\n        os.system('rm -rf /')\n        self.wait(1)\n"
is_safe_bad, bad_issues = validate_names_and_imports(bad_code)
assert not is_safe_bad, "Should flag os import as forbidden"
print(f"[OK] code_digest — dangerous import correctly flagged: {bad_issues[0][:50]}")

# Safety check — SVGMobject
svg_code = "from manim import *\nclass GeneratedScene(Scene):\n    def construct(self):\n        obj = SVGMobject('icon.svg')\n        self.wait(1)\n"
is_safe_svg, svg_issues = validate_names_and_imports(svg_code)
assert not is_safe_svg, "Should flag SVGMobject"
print(f"[OK] code_digest — SVGMobject correctly flagged: {svg_issues[0][:50]}")

# Quality checks
passes, warns = check_code_quality(test_code)
print(f"[OK] code_digest — quality passes={passes}, warnings={len(warns)}")

# ── RAG_system ────────────────────────────────────────────────────────────────
from RAG.RAG_system import retrieve_patterns, retrieve_golden_example

# Test basic retrieval
patterns = retrieve_patterns("math", "derivatives limits", ["tangent line", "secant"], limit=2)
assert len(patterns) > 0, "No patterns returned"
print(f"[OK] RAG_system — retrieved {len(patterns)} patterns for derivatives:")
for p in patterns:
    note = p['notes'][:60].encode('ascii', 'replace').decode()
    print(f"     - {note}")

# Test new domains
econ_patterns = retrieve_patterns("general", "supply demand market", ["equilibrium", "price"], limit=2)
assert len(econ_patterns) > 0, "No economics patterns returned"
print(f"[OK] RAG_system — economics patterns retrieved: {econ_patterns[0]['notes'][:50]}")

# Test multi-word phrase scoring
phrase_patterns = retrieve_patterns("math", "binary tree graph", ["bst", "traversal"], limit=2)
assert len(phrase_patterns) > 0, "No CS patterns returned"
print(f"[OK] RAG_system — phrase matched: {phrase_patterns[0]['notes'][:50]}")

# Test golden example non-empty
golden = retrieve_golden_example("math", "eigenvalue", ["eigenvector", "matrix"])
assert len(golden) > 100, f"Golden example too short: {len(golden)} chars"
print(f"[OK] RAG golden example — {len(golden)} chars")

# ── ai_functions import ───────────────────────────────────────────────────────
import sys

class _FakeOpenAI:
    def __init__(self, **kw): pass
sys.modules["openai"] = type(sys)("openai")
sys.modules["openai"].OpenAI = _FakeOpenAI

from algorithms import ai_functions  # type: ignore
print("[OK] algorithms.ai_functions — imported successfully")

# Verify prompt improvements
assert "CRASH" in ai_functions.GENERATION_SYSTEM, "GENERATION_SYSTEM missing crash rules"
assert "RULE 1" in ai_functions.REVIEW_SYSTEM, "REVIEW_SYSTEM missing numbered rules"
assert "LaTeXError" in ai_functions.FIX_SYSTEM, "FIX_SYSTEM missing LaTeXError recipe"
print("[OK] Prompts — GENERATION_SYSTEM, REVIEW_SYSTEM, FIX_SYSTEM all upgraded")

# ── app.py render flag check ──────────────────────────────────────────────────
with open("app.py", "r") as f:
    app_src = f.read()
assert "-pqh" not in app_src, "Old -pqh flag still present in app.py!"
assert "-qh" in app_src, "New -qh flag not found in app.py"
assert "validate_names_and_imports" in app_src, "AST validator not wired into app.py"
print("[OK] app.py — render flag is -qh, AST validator wired in")

print()
print("=" * 55)
print("ALL CHECKS PASSED")
print("=" * 55)
