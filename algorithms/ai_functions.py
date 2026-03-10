"""
Core AI functions for NIMA.
All OpenAI calls live here.

Changes vs. original:
  - Removed duplicated ManimDatabase class (import from database.db)
  - Fixed model name (was 'gpt-5' in request_analysis → now uses config)
  - Merged self_critique + overlapping_fix + ai_fix into ONE review_and_fix() call
  - Added fix_render_error() that feeds Manim stderr back to the LLM
  - Richer generation prompt with 3b1b-style patterns and ValueTracker guidance
  - RAG retrieval now uses real RAG_system.retrieve_golden_example
"""

from openai import OpenAI
import os
import json
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from config import OPENAI_API_KEY, GENERATION_MODEL, FAST_MODEL
from algorithms.error_parser import parse_manim_error, format_error_for_prompt
from RAG.RAG_system import retrieve_golden_example

client = OpenAI(api_key=OPENAI_API_KEY)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYOUT HELPERS  (injected into every generated script)
# ═══════════════════════════════════════════════════════════════════════════════

LAYOUT_HELPERS = """\
# === AUTO-INJECTED LAYOUT HELPERS ===
from manim import config as _cfg

def smart_text(text_str, max_width=11, font_size=30):
    '''Wrap and scale text to fit frame width.'''
    t = Text(text_str, font_size=font_size)
    if t.width > max_width:
        t = t.scale_to_fit_width(max_width)
    return t

def fit_to_screen(mob, margin=0.8):
    '''Scale mobject so it fits inside the frame.'''
    tw = _cfg.frame_width - margin
    th = _cfg.frame_height - margin
    if mob.width > tw:
        mob.scale(tw / mob.width)
    if mob.height > th:
        mob.scale(th / mob.height)
    return mob

def safe_zone_title(text, font_size=40):
    '''Create a persistent title in the top zone.'''
    return Text(text, font_size=font_size).to_edge(UP, buff=0.3)

def start_section(scene, title_text=None, font_size=36):
    '''Begin a new section: fade out all current objects, optionally show a title.
    Returns (title_mob_or_None, section_group) — add all new objects to section_group.'''
    if scene.mobjects:
        scene.play(FadeOut(*scene.mobjects))
    section_group = VGroup()
    title_mob = None
    if title_text:
        title_mob = Text(title_text, font_size=font_size, color=BLUE).to_edge(UP, buff=0.3)
        scene.play(Write(title_mob))
    return title_mob, section_group

def end_section(scene, section_group, title_mob=None):
    '''Clean up a section: fade out the section_group (and title if given).'''
    to_remove = [section_group]
    if title_mob is not None:
        to_remove.append(title_mob)
    scene.play(FadeOut(*to_remove))

def stack(*mobs, anchor=ORIGIN, direction=DOWN, buff=0.35):
    '''Arrange mobjects vertically (or in given direction) from an anchor point.'''
    g = VGroup(*mobs).arrange(direction, buff=buff).move_to(anchor)
    return g

def clear_except(scene, *keepers):
    '''Fade out everything on screen EXCEPT the listed mobjects.'''
    to_remove = [m for m in scene.mobjects if m not in keepers]
    if to_remove:
        scene.play(FadeOut(*to_remove))

# === END HELPERS ===

"""


def inject_helpers(code: str) -> str:
    if "from manim import *" in code:
        return code.replace("from manim import *", "from manim import *\n" + LAYOUT_HELPERS)
    return LAYOUT_HELPERS + "\n" + code


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — DOMAIN GUIDANCE
# ═══════════════════════════════════════════════════════════════════════════════

def get_domain_specific_guidance(domain: str) -> str:
    guides = {
        "math": """\
**MATHEMATICAL VISUALIZATION — REQUIRED TECHNIQUES:**
- Prefer MathTex over Text for all equations. Color-code key sub-expressions.
- Use ValueTracker + always_redraw for live parameter animations (derivative, limit, etc.).
- Use TracedPath to draw curves as a dot moves.
- Use TransformMatchingTex for elegant step-by-step equation proofs.
- Show geometric interpretations alongside algebraic forms.
- For function graphs: use Axes with add_coordinates(), get_graph_label().
- For integrals: use axes.get_riemann_rectangles() with a live n_tracker.
- For series/convergence: overlay successive approximations in distinct colors.

**LINEAR ALGEBRA TOPICS (matrix, determinant, transform, eigenvector, basis):**
- ALWAYS show basis vectors i_hat=(1,0) and j_hat=(0,1) as colored arrows FIRST
- Show the unit square formed by basis vectors BEFORE any transformation
- Apply the matrix by transforming i_hat, j_hat, AND the unit square simultaneously
- For determinants: show area comparison (unit area → parallelogram area)
- NumberPlane MUST use subtle styling: background_line_style={"stroke_opacity": 0.15}
- Focus the viewer's attention on vectors and shapes, NOT the grid
- Use Transform/ReplacementTransform to morph shapes — never self.clear()
""",
        "physics": """\
**PHYSICS VISUALIZATION — REQUIRED TECHNIQUES:**
- Represent forces as colored Arrow objects (length ∝ magnitude).
- Use ArrowVectorField or StreamLines for field visualizations.
- ValueTracker controls time; always_redraw updates positions each frame.
- Show energy as color (e.g., BLUE = low KE, RED = high KE).
- Use DashedLine for reference / equilibrium lines.
- Label x/y axes clearly; show units in axis labels.
""",
        "computer_science": """\
**CS VISUALIZATION — REQUIRED TECHNIQUES:**
- Arrays: Row of Rectangle+Text VGroups, color YELLOW for active comparison, GREEN for sorted.
- Trees: Circle+Text nodes, Line edges, build level-by-level with LaggedStart.
- Graphs: Dot nodes + Line edges, highlight traversal path with color changes.
- Use Text for pseudocode steps, Show each step as it executes.
- Avoid using real file I/O or external images — all visuals must be pure Manim objects.
""",
        "chemistry": """\
**CHEMISTRY VISUALIZATION — REQUIRED TECHNIQUES:**
- Build molecules from Dot (atoms) + Line (bonds).
- Use standard CPK colors: H=WHITE, C=GREY, O=RED, N=BLUE, S=YELLOW.
- Show reaction mechanisms: curved Arrow from bond to bond.
- Animate bond breaking: Uncreate the Line, then separate atom Dots.
- Side-by-side: reactants on LEFT, products on RIGHT, arrow in MIDDLE.
""",
    }
    return guides.get(domain, "")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — ERROR WARNINGS FROM DB
# ═══════════════════════════════════════════════════════════════════════════════

def get_error_warnings(db=None) -> str:
    if not db or not db.available:
        return ""
    try:
        patterns = db.get_error_patterns(limit=5)
        if not patterns:
            return ""
        w = "\n=== RECURRING ERRORS TO AVOID ===\n"
        for p in patterns:
            w += f"  [ERR] {p['error_category']}: {p['root_cause']}\n"
            w += f"    Fix: {p['fix_description']}\n\n"
        return w
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — MAIN CODE GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

GENERATION_SYSTEM = """\
You are an expert Manim Community Edition (CE v0.18) animator.
Your output is educational video code that rivals 3Blue1Brown in quality.
You MUST output ONLY runnable Python code — no prose, no markdown fences.

═══════════════════════════════════════════════════════════════════════
EXACT OUTPUT FORMAT — FOLLOW THIS TEMPLATE EXACTLY
═══════════════════════════════════════════════════════════════════════
from manim import *
import numpy as np

class GeneratedScene(Scene):
    def construct(self):
        # === SCENE 1: Title / Hook (0–10s) ===
        title = Text("Your Title Here", font_size=48, color=BLUE)
        subtitle = Text("One-line hook", font_size=28, color=WHITE)
        title_group = VGroup(title, subtitle).arrange(DOWN, buff=0.4).center()
        self.play(Write(title), FadeIn(subtitle, shift=UP * 0.3))
        self.wait(2)
        self.play(FadeOut(title_group))

        # === SCENE 2: Build Intuition (10–30s) ===
        # Show the SIMPLEST version of the concept first.
        # Start with prerequisites and building blocks.
        # Example: for a matrix transformation, first show i_hat and j_hat.

        # === SCENE 3: Core Visual (30–50s) ===
        # Build up complexity step by step.
        # Transform existing objects instead of removing and recreating.
        # Example: Transform the unit square into parallelogram.

        # === SCENE 4: Insight / Aha Moment (50–60s) ===
        # Show the key comparison, calculation, or result.
        # Example: show area comparison, reveal the determinant formula.

        # === FINAL: Summary (last 10s) ===
        summary = Text("Key takeaway here", font_size=36)
        self.play(Write(summary))
        self.wait(3)

═══════════════════════════════════════════════════════════════════════
ALLOWED IMPORTS — ONLY THESE TWO, NOTHING ELSE
═══════════════════════════════════════════════════════════════════════
  from manim import *
  import numpy as np          # only if you use np.* functions

NEVER import: os, sys, subprocess, pathlib, manimlib, manim.mobject.*, etc.
NEVER use: open(), exec(), eval(), os.system(), __import__()

═══════════════════════════════════════════════════════════════════════
API CORRECTIONS — THESE MISTAKES WILL CRASH THE RENDER
═══════════════════════════════════════════════════════════════════════
[CRASH] axes.get_graph(f)            → [FIX] axes.plot(f, x_range=[a,b])
[CRASH] axes.get_axis_labels(x, y)  → [FIX] axes.get_axis_labels(x_label="x", y_label="y")
[CRASH] CONFIG = {"color": ...}     → [FIX] set in __init__ or as class attr
[CRASH] VGroup([a, b, c])           → [FIX] VGroup(a, b, c)  (no list!)
[CRASH] Matrix([[1,2],[3,4]])        → [FIX] use IntegerMatrix or DecimalMatrix if possible
[CRASH] SVGMobject("file.svg")      → [FIX] build from Circle/Square/Polygon
[CRASH] ImageMobject("img.png")     → [FIX] build from colored Rectangle/Circle
[CRASH] obj.color = RED             → [FIX] obj.set_color(RED)
[CRASH] Text("...").move_to(TOP)    → [FIX] .to_edge(UP, buff=0.3)
[CRASH] self.play(obj)              → [FIX] self.play(Create(obj)) or FadeIn(obj)
[CRASH] Sector(angle=90)            → [FIX] Sector(angle=PI/2)  — radians only!
[CRASH] from manimlib import *      → [FIX] from manim import *
[CRASH] axes.c2p(x, y, 0)          → [FIX] axes.c2p(x, y)  — 2 args only!
[CRASH] arrow.get_length()          → [FIX] np.linalg.norm(arrow.get_vector())
[CRASH] DashedArrow(...)             → [FIX] DashedLine(...).add_tip()  — DashedArrow does not exist
[CRASH] arrow.tip.length = 0.2       → [FIX] use max_tip_length_to_length_ratio param in Arrow()
[CRASH] obj.tip.length = X           → [FIX] .tip.length is read-only; set tip size in constructor

LAMBDA CLOSURE BUG — MOST COMMON CRASH IN LOOPS:
  WRONG: dots = [always_redraw(lambda: Dot(axes.c2p(i, f(i)))) for i in vals]
  RIGHT: dots = [always_redraw(lambda i=i: Dot(axes.c2p(i, f(i)))) for i in vals]
  # Always bind loop variables as default args in lambdas!

═══════════════════════════════════════════════════════════════════════
SCREEN LAYOUT — STRICT ZONES
═══════════════════════════════════════════════════════════════════════
TOP    (10%): Persistent section title only → Text(...).to_edge(UP, buff=0.3)
CENTER (75%): All visuals → use VGroup.arrange() to prevent overlap
BOTTOM (15%): Explanation text only → Text(...).to_edge(DOWN, buff=0.4)

═══════════════════════════════════════════════════════════════════════
TRANSITIONS — CRITICAL FOR QUALITY
═══════════════════════════════════════════════════════════════════════
  NEVER use self.clear()! It destroys visual context and breaks continuity.

  SECTION LIFECYCLE (use the injected helpers):
    # Start each major section by cleaning up the previous one:
    title, section = start_section(self, "Section Title")
    
    # Add objects to the section group for easy cleanup:
    eq = MathTex(r"f(x) = x^2")
    section.add(eq)
    self.play(Write(eq))
    
    # End the section before starting the next:
    end_section(self, section, title)

  If not using helpers, MANUALLY ensure:
    - self.play(FadeOut(*self.mobjects)) before each new topic
    - Or selectively: self.play(FadeOut(old_group))

  GOOD transitions (use these):
    # Selectively remove objects from the previous scene:
    self.play(FadeOut(old_group))

    # Morph related objects into their next form:
    self.play(Transform(old_eq, new_eq))
    self.play(ReplacementTransform(simple_shape, complex_shape))
    self.play(FadeTransform(old_title, new_title))

  BAD transitions (NEVER do these):
    self.clear()            # ← BANNED — kills all context
    self.remove(obj)        # ← invisible removal, confusing to viewer

═══════════════════════════════════════════════════════════════════════
VISUAL STYLING — GRIDS AND PLANES
═══════════════════════════════════════════════════════════════════════
  NumberPlane MUST always use subtle styling so it supports but does not
  dominate the visual scene:

    plane = NumberPlane(
        x_range=[-5, 5], y_range=[-4, 4],
        background_line_style={"stroke_opacity": 0.15},
        faded_line_style={"stroke_opacity": 0.08},
        faded_line_ratio=3,
    ).set_opacity(0.3)

  NEVER use bare NumberPlane() — the default grid is too bold and visually
  overpowers vectors, shapes, and transformations.

═══════════════════════════════════════════════════════════════════════
PEDAGOGICAL STRUCTURE — HOW TO EXPLAIN CONCEPTS
═══════════════════════════════════════════════════════════════════════
  Every concept MUST follow this progression:
    1. PREREQUISITE — show the simplest building blocks first
    2. BUILD UP     — add complexity one step at a time
    3. FULL CONCEPT — show the complete result
    4. INSIGHT      — highlight the key takeaway or comparison

  NEVER just show formula → result. Always include intermediate visual steps.
  NEVER introduce a complex result without first showing its building blocks.

  Example for "determinant of a matrix":
    1. Show i_hat=(1,0) and j_hat=(0,1) arrows on a subtle grid
    2. Show the unit square formed by these basis vectors
    3. Apply the matrix transformation → watch i_hat, j_hat, and square change
    4. Show area comparison: unit square area=1 → parallelogram area=|det|
    5. Reveal the determinant formula as the scaling factor

═══════════════════════════════════════════════════════════════════════
QUALITY REQUIREMENTS
═══════════════════════════════════════════════════════════════════════
1. Use MathTex (not Text) for ALL formulas and equations
2. Color-code sub-expressions: eq[0][3:5].set_color(YELLOW)
3. Use ValueTracker + always_redraw for any changing parameter
4. Each major concept: introduce → animate → wait(2) → transition → next
5. Minimum self.wait() distribution: ≥1s after each reveal, ≥2s at concept end
6. VGroup all related objects: title+underline, equation+label, etc.
7. Scene ends at exactly the target duration (pace wait() times accordingly)
8. Use LaggedStart for groups of objects appearing together
9. Prefer Transform/ReplacementTransform for related objects over FadeOut+FadeIn
10. Keep visual focus on the CONCEPT, not on grids, axes, or decorations
"""


def generate_manim_code(prompt: str, analysis: dict, plan: str, attempt: int = 1, db=None, segment_durations: dict = None) -> str:
    print(f"[GENERATE] Attempt {attempt}: generating code...")

    golden = retrieve_golden_example(
        analysis["domain"],
        analysis["topic"],
        analysis.get("subtopics", []),
        db=db
    )
    error_warnings = get_error_warnings(db)
    domain_guidance = get_domain_specific_guidance(analysis["domain"])

    # Build timing contract if voiceover durations are available
    timing_contract = ""
    if segment_durations:
        timing_lines = []
        for seg_id, info in segment_durations.items():
            dur = info["duration"]
            timing_lines.append(f"  {seg_id}: exactly {dur:.1f} seconds of animation")
        timing_contract = (
            "\n\n=== TIMING CONTRACT (MUST FOLLOW — narration audio is pre-recorded) ===\n"
            "Each scene's total animation time (sum of all run_time + wait) MUST equal\n"
            "the specified duration so visuals sync with the voice-over.\n"
            + "\n".join(timing_lines) +
            "\nIf a scene's animations are shorter than its duration, pad with self.wait().\n"
            "If longer, compress run_time values proportionally.\n"
        )

    system_msg = f"""{GENERATION_SYSTEM}

{error_warnings}

=== DOMAIN-SPECIFIC GUIDANCE ===
{domain_guidance}

=== PROVEN PATTERNS TO BUILD FROM ===
(Study these carefully — use their techniques in your code)

{golden}

=== ANIMATION STORYBOARD TO FOLLOW ===
{plan}
{timing_contract}
=== FINAL CHECKLIST ===
Before returning, verify:
 [OK] class GeneratedScene(Scene) with def construct(self)
 [OK] All imports via: from manim import *
 [OK] No SVGMobject, ImageMobject, or emoji
 [OK] Every section cleans up before the next (FadeOut / self.clear() + re-add title)
 [OK] Adequate wait() after each concept reveal
 [OK] Video targets ~{analysis['duration']} seconds total
 [OK] MathTex used for all formulas (not Text)
 [OK] ValueTracker used if showing a changing parameter

Target duration: {analysis['duration']} seconds
Topic: {analysis['topic']}
Subtopics: {', '.join(analysis.get('subtopics', []))}

Return ONLY the complete, runnable Manim Python code. No prose, no explanation."""

    response = client.chat.completions.create(
        model=GENERATION_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Create a Manim animation for: {prompt}"},
        ],
        max_completion_tokens=16000,
    )
    code = response.choices[0].message.content
    print(f"[GENERATE] [OK] {len(code)} chars generated")
    return extract_code(code)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — SINGLE COMBINED REVIEW PASS
# (replaces: self_critique_and_improve + overlapping_fix + ai_fix)
# ═══════════════════════════════════════════════════════════════════════════════

REVIEW_SYSTEM = """\
You are a strict Manim CE v0.18 code reviewer and fixer.
Take the generated code and fix ALL issues in ONE pass.
Return ONLY the complete corrected Python code. No prose.

RULE 1 — IMPORTS: Keep only `from manim import *` and optionally `import numpy as np`.
  Remove any other import. Never import os, sys, subprocess, manimlib.

RULE 2 — STRUCTURE: Code MUST have exactly:
  class GeneratedScene(Scene):
      def construct(self):
  Rename any other Scene subclass to GeneratedScene.

RULE 3 — FORBIDDEN OBJECTS: Remove these and replace with Manim-native equivalents.
  SVGMobject → Polygon / Circle / Square
  ImageMobject → colored Rectangle
  Emojis in Text() → plain ASCII

RULE 4 — API FIXES (apply all that apply):
  axes.get_graph(f)       → axes.plot(f, x_range=[a,b])
  CONFIG = {}             → remove; use __init__ params
  VGroup([a,b])           → VGroup(a, b)  (unpack the list!)
  obj.color = RED         → obj.set_color(RED)
  Sector(angle=90)        → Sector(angle=PI/2)
  axes.c2p(x, y, 0)       → axes.c2p(x, y)

RULE 4b — NONEXISTENT CLASSES & READ-ONLY PROPERTIES:
  DashedArrow(...)        → DashedLine(...).add_tip()  (DashedArrow does not exist!)
  arrow.tip.length = X    → set tip_length in Arrow() constructor or use max_tip_length_to_length_ratio
  obj.color = RED         → obj.set_color(RED)

RULE 5 — LAMBDA CLOSURES: In every list comprehension or for loop creating
  always_redraw lambdas, bind loop variable as default arg:
    WRONG: lambda: Dot(func(i))    ← i is late-bound
    RIGHT: lambda i=i: Dot(func(i)) ← i captured at creation

RULE 6 — LAYOUT: Ensure no two objects occupy the same screen region.
  - Titles: .to_edge(UP, buff=0.3)
  - Body text: .to_edge(DOWN, buff=0.4)
  - Visuals: center area, use VGroup.arrange() for spacing
  - Before each new section: FadeOut everything from the previous section
  - PREFER using start_section(self, "Title") and end_section(self, group) helpers
  - NEVER place two different objects at the same coordinates without FadeOut between them
  - When using .copy(), ALWAYS FadeOut or remove the original before showing the copy
  - Use stack(obj1, obj2, obj3) helper to arrange multiple objects vertically

RULE 7 — PACING: Every self.play() block must eventually be followed by
  self.wait() ≥ 1.0. If ≥ 5 consecutive self.play() calls lack a wait, add one.

RULE 8 — CLEANUP: Preserve all visual content and narrative intent.
  Do not add explanatory comments. Output code only.

RULE 9 — GRID STYLING: If NumberPlane() is used without opacity styling,
  add background_line_style={"stroke_opacity": 0.15} and call .set_opacity(0.3).
  The grid must NEVER dominate the visual scene.

RULE 10 — NO SELF.CLEAR(): Replace every self.clear() call with:
  self.play(FadeOut(*self.mobjects))
  This preserves visual continuity instead of abruptly wiping the screen.

RULE 11 — BASIS VECTORS: If the code shows a linear transformation
  (apply_matrix, matrix, determinant) but does NOT show basis vectors
  (i_hat / j_hat arrows at (1,0) and (0,1)), ADD them before the transformation.
  Basis vectors are essential for understanding what the transformation does.
"""


def review_and_fix(code: str, prompt: str, analysis: dict) -> str:
    """Single pass that replaces self_critique + overlapping_fix + ai_fix."""
    print("[REVIEW] Combined review pass...")
    try:
        response = client.chat.completions.create(
            model=GENERATION_MODEL,
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM},
                {"role": "user", "content": f"Prompt context: {prompt}\n\nCode to fix:\n{code}"},
            ],
            max_completion_tokens=16000,
        )
        fixed = extract_code(response.choices[0].message.content)
        print("[REVIEW] [OK] Review pass complete")
        return fixed
    except Exception as e:
        print(f"[REVIEW] [ERR] Error: {e}, using original")
        return code


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — RENDER-ERROR SELF-HEALING
# ═══════════════════════════════════════════════════════════════════════════════

FIX_SYSTEM = """\
You are a Manim CE v0.18 runtime error fixer.
The code failed to render. Apply the EXACT fix for the error type shown.
Return ONLY the complete corrected Python code. No prose.

FIX RECIPES BY ERROR TYPE:

AttributeError (wrong API method or property):
  - axes.get_graph → axes.plot
  - obj.color = X  → obj.set_color(X)
  - Check Manim CE v0.18 docs for correct method name

TypeError (wrong args or types):
  - VGroup([a,b]) → VGroup(a, b)  (never pass a list)
  - Sector(angle=90) → Sector(angle=PI/2)  (radians!)
  - axes.c2p(x,y,0) → axes.c2p(x,y)

NameError (undefined variable or class):
  - Add `from manim import *` if missing
  - Check spelling of Manim class names (e.g., NumberPLane → NumberPlane)
  - If referencing a variable after self.clear() or FadeOut, redefine it

ImportError:
  - Only `from manim import *` is permitted; remove all other imports
  - Never use internal manim modules (manim.mobject.*, manim.animation.*)

LaTeXError (MathTex / Tex compile failure):
  - Use raw strings: r"\frac{1}{2}" not "\\frac{1}{2}"
  - Remove unusual packages or commands; stick to basic LaTeX math
  - Replace complex expressions with simpler equivalents
  - Check for unmatched braces { }

fileNotFoundError / SVGMobject / ImageMobject:
  - Replace SVGMobject with Polygon, Circle, or Square
  - Replace ImageMobject with a colored Rectangle

RecursionError (infinite updater):
  - Check always_redraw lambda — it must not call self.play() internally
  - Use rate_func or ValueTracker instead of recursive calls

ZeroDivisionError:
  - Add `if denominator != 0:` guard before division
  - Use max(val, 1e-9) to clamp small denominators

Cairo / Pango / font error:
  - Remove special unicode characters from Text()
  - Use only ASCII in Text(); put math in MathTex()

ffmpeg / codec error:
  - Remove any direct file I/O; Manim handles output automatically
  - Do not call subprocess or os.system

RULES:
- Fix only the specific reported error. Keep all visual content intact.
- Preserve the class GeneratedScene(Scene) structure.
"""



def fix_render_error(code: str, stderr: str, prompt: str) -> str:
    """
    Feed the Manim stderr back to the LLM for a targeted fix.
    Called between render retries.
    """
    parsed = parse_manim_error(stderr)
    error_summary = format_error_for_prompt(parsed)
    print(f"[FIX] Runtime error: {parsed['error_type']} — {parsed['error_message'][:80]}")

    try:
        response = client.chat.completions.create(
            model=GENERATION_MODEL,
            messages=[
                {"role": "system", "content": FIX_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"RENDER ERROR:\n{error_summary}\n\n"
                        f"ORIGINAL PROMPT: {prompt}\n\n"
                        f"CODE THAT FAILED:\n{code}"
                    ),
                },
            ],
            max_completion_tokens=16000,
        )
        fixed = extract_code(response.choices[0].message.content)
        print("[FIX] [OK] Error fix applied")
        return fixed
    except Exception as e:
        print(f"[FIX] [ERR] Fix failed: {e}")
        return code


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def extract_code(text: str) -> str:
    """Strip markdown fences and return raw Python."""
    if "```python" in text:
        return text.split("```python")[1].split("```")[0].strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            return parts[1].lstrip("python").strip()
    return text.strip()


def polish_manim_code(code: str) -> str:
    """Lightweight syntax fixer — used when syntax validation fails."""
    print("[POLISH] Fixing syntax errors...")
    try:
        response = client.chat.completions.create(
            model=FAST_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Fix Python/Manim syntax errors in this code. "
                        "Return ONLY corrected code. No explanation."
                    ),
                },
                {"role": "user", "content": code},
            ],
            max_completion_tokens=16000,
        )
        return extract_code(response.choices[0].message.content)
    except Exception as e:
        print(f"[POLISH] [ERR] {e}")
        return code


# ═══════════════════════════════════════════════════════════════════════════════
# EVALUATION
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_with_gpt4(code: str, video_path: str, prompt: str, execution_data: dict) -> dict:
    """
    Score the generated animation based on code quality and execution result.
    Note: we can score code quality statically; actual visual quality requires
    a vision model to watch the video — that's a future improvement.
    """
    print("[EVAL] Evaluating...")
    eval_prompt = f"""Evaluate this Manim animation code.

Request: {prompt}
Render status: {execution_data['status']}
Render duration: {execution_data.get('duration', 'N/A')}s
Errors: {execution_data.get('error', 'None')}

Code (first 1500 chars):
```python
{code[:1500]}
```

Score each dimension 0–100:
1. layout_quality   — no overlaps, clean zones, good spacing
2. educational_value — explains the concept clearly with visuals
3. technical_accuracy — correct math/science/CS
4. pacing — appropriate wait() times and scene flow
5. manim_quality — idiomatic Manim CE (ValueTracker, MathTex, VGroup, etc.)

Respond ONLY with valid JSON (no markdown):
{{
  "layout_quality": 0,
  "educational_value": 0,
  "technical_accuracy": 0,
  "pacing": 0,
  "manim_quality": 0,
  "overall": 0,
  "strengths": ["..."],
  "weaknesses": ["..."],
  "issues": ["..."],
  "suggestions": "...",
  "predicted_satisfaction": 0
}}"""

    try:
        response = client.chat.completions.create(
            model=FAST_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert educational video evaluator. Return only JSON."},
                {"role": "user", "content": eval_prompt},
            ],
            temperature=0.2,
        )
        raw = response.choices[0].message.content.strip()
        # Strip any accidental markdown
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        evaluation = json.loads(raw)

        # Compute overall if not present
        if "overall" not in evaluation or evaluation["overall"] == 0:
            dims = ["layout_quality", "educational_value", "technical_accuracy", "pacing", "manim_quality"]
            vals = [evaluation.get(d, 0) for d in dims]
            evaluation["overall"] = int(sum(vals) / len(vals)) if vals else 0

        # Alias for DB schema compatibility
        evaluation.setdefault("visual_quality", evaluation.get("layout_quality", 0))
        evaluation.setdefault("pacing_timing", evaluation.get("pacing", 0))
        evaluation.setdefault("clarity", evaluation.get("educational_value", 0))
        evaluation.setdefault("engagement", evaluation.get("manim_quality", 0))

        print(f"[EVAL] [OK] Overall score: {evaluation['overall']}/100")
        return evaluation
    except Exception as e:
        print(f"[EVAL] [ERR] {e}")
        return {"overall": 0, "error": str(e)}
