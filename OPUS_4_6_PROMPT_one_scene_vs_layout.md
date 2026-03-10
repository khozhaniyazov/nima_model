# Prompt for Opus 4.6 — NIMA: single-scene rule vs. overlapping renders

You are Opus 4.6 (expert in Manim CE + LLM codegen pipelines). I’m working on **NIMA**, a Flask app that generates Manim CE code with an LLM, reviews/fixes it, and renders it.

## Goal
Diagnose why NIMA frequently produces **overlapping elements** and propose a concrete plan to improve layout reliability **without breaking render success**.

I want your output to be a practical, implementable recommendation for:
- prompt rules (generation + review),
- safe helper APIs the model should use,
- optional static checks / auto-fixes,
- and (optionally) how to support multi-scene safely.

## Current behavior
- Renders usually succeed (good), but **visual layout is often a mess** (overlaps, stacked equations, leftover objects).
- The UI remains responsive because rendering is async (thread-based).

## Pipeline details (important)
### Rendering is hardwired to ONE scene
NIMA effectively forces the code to be a single Scene named `GeneratedScene`.

There are **three independent enforcement points**:

1) **LLM review/fix system prompt** forces the structure:
   - In `algorithms/ai_functions.py` → `REVIEW_SYSTEM`, **RULE 2**:
     - Code MUST have exactly `class GeneratedScene(Scene): def construct(self):`
     - Rename any other Scene subclass to `GeneratedScene`

2) **Static post-processing** forces/wraps to `GeneratedScene`:
   - In `algorithms/code_digest.py` → `ensure_scene_class(code)`:
     - If code has any `class X(Scene)`, it renames the first to `GeneratedScene`.
     - Otherwise it wraps raw code inside a `GeneratedScene(Scene)` class.

3) **Manim render command** always renders only `GeneratedScene`:
   - In `app.py` → `_run_manim(...)`:
     - `manim script.py GeneratedScene -ql --media_dir ... --output_file ...`

**Net effect:** even if the model generates multiple Scene classes, the pipeline collapses them and only renders one.

### Layout guidance exists but overlaps persist
The prompts already include layout advice like:
- “use VGroup.arrange() for spacing”
- “fade out between sections”
- “no self.clear(); use FadeOut(*self.mobjects)”

Yet overlaps still happen because the code generation frequently leaves old mobjects alive and then places new ones at the same coordinates.

## Concrete overlap bug found (example)
Job id: `8f91df78` (Euclidean algorithm). Generated script: `C:\temp\manim_scripts\video_8f91df78.py`.

In the recap section, there was a direct coordinate collision:
- `gcd_final` is positioned at `ORIGIN + UP*0.4` and remains on-screen.
- Then the recap chain is created and also moved to `ORIGIN + UP*0.4`.
- No FadeOut/cleanup happens between them.

A surgical patch fixed that specific collision (fade out `gcd_final` before recap), but the user still observed significant overlapping elsewhere — indicating **systemic scene hygiene/layout issues**, not a single missed FadeOut.

## Why the single-scene rule may be contributing
Single-scene is great for reliability (Manim always has a known entrypoint), but it encourages:
- very long `construct()` functions,
- accumulation of `self.mobjects`,
- frequent reuse of the same anchor positions,
- and fragile transforms/copies leaving duplicates behind.

Without a strong “section lifecycle” discipline, overlap becomes inevitable.

## What I want from you
Provide a detailed, opinionated plan covering:

### A) Best approach if we KEEP one Scene
Give a strict pattern for “sections” inside one scene that prevents overlap:
- A `hud/title` group that can persist,
- A `section_group` that contains everything else,
- Required cleanup: `FadeOut(section_group)` and `section_group.clear()` before building the next section,
- A recommended API for coloring that avoids fragile deep indexing after transforms:
  - Prefer `set_color_by_tex()` or `set_color_by_tex_to_color_map` over `eq[0][7]` indexing.

Also propose **helper functions** to inject into generated code to enforce this pattern (NIMA already has `inject_helpers()`):
- `start_section(title: str) -> (title_mob, section_group)`
- `end_section(section_group)`
- `stack(*mobs, anchor=ORIGIN, direction=DOWN, buff=...)`
- `safe_to_edge(mob, edge, buff)`
- `clear_except(*keepers)`

### B) How to adjust prompts
Propose concrete edits to the generation/review prompts that make overlap less likely.
Examples:
- Require every new section to begin with `self.play(FadeOut(*self.mobjects))` *or* `FadeOut(section_group)`.
- Ban repeated `move_to(ORIGIN + UP*...)` for unrelated content unless previous is removed.
- Ban “copy() and keep original” unless original is explicitly removed.

### C) Static checks / heuristics
Propose static validators/auto-fixes that can detect high-risk overlap patterns:
- repeated `.move_to(ORIGIN + UP*0.4)` on multiple objects without intervening FadeOut,
- multiple `Write()` calls with no corresponding FadeOut for previous content,
- many objects in `self.mobjects` at section boundaries.

### D) OPTIONAL: safe multi-scene support
If you think multi-scene is the real fix, propose a safe scheme:
- Require scenes named `Scene01..SceneNN` (no gaps)
- Auto-discover scene names from code
- Render all scenes in one manim call: `manim script.py Scene01 Scene02 ...`
- Concatenate outputs with ffmpeg
- Add a max-scene cap (e.g., <=6 scenes)

But: single-scene reliability matters; do not propose multi-scene unless it’s clearly worth it.

## Output format
Reply with:
1) A clear recommendation (keep one scene with section lifecycle vs multi-scene)
2) Concrete prompt rules (bullet list)
3) Proposed helper APIs to inject (signatures + short examples)
4) Optional static checks (what to detect + how to fix)
5) A short “why this works” rationale.
