# Code Conventions

**Analysis Date:** 2026-04-04

## Python Style

**Style Guide:** PEP 8 with snake_case naming

**Key Conventions:**
- Python modules: `snake_case.py`
- Python functions: `snake_case()`
- Python classes: `PascalCase`
- Variables: `snake_case`
- Private helpers: prefix with `_`

**Imports:**
- `from manim import *` for generated code
- `from manim import *` plus optional `import numpy as np` only allowed
- Forbidden: `os`, `sys`, `subprocess`, `pathlib`, `manimlib`

## Manim CE Patterns

**Scene Structure:**
```python
class GeneratedScene(Scene):
    def construct(self):
        # All animation code here
```

**Zone Layout (strict):**
- TOP (10%): Section titles only → `.to_edge(UP, buff=0.3)`
- CENTER (75%): All visuals → use `VGroup.arrange()`
- BOTTOM (15%): Explanation text → `.to_edge(DOWN, buff=0.4)`

**Cleanup Pattern (BANNED: self.clear()):**
```python
# WRONG - breaks visual continuity
self.clear()

# CORRECT - selective fade out
self.play(FadeOut(*self.mobjects))
```

**Section Lifecycle (multi-step scenes):**
```python
sec = start_section(self, "Section Title")
sec.add(obj1, obj2)
sec.play(Write(obj1))
# ...
sec.end()
```

**Lambda Closure in Loops:**
```python
# WRONG - late binding
dots = [always_redraw(lambda: Dot(x=i)) for i in range(5)]

# CORRECT - capture at creation
dots = [always_redraw(lambda i=i: Dot(x=i)) for i in range(5)]
```

## API Corrections (Common Mistakes)

| Wrong | Correct |
|-------|---------|
| `axes.get_graph(f)` | `axes.plot(f, x_range=[a,b])` |
| `VGroup([a, b])` | `VGroup(a, b)` (no list) |
| `Sector(angle=90)` | `Sector(angle=PI/2)` (radians) |
| `axes.c2p(x, y, 0)` | `axes.c2p(x, y)` (2 args only) |
| `obj.color = RED` | `obj.set_color(RED)` |
| `arrow.tip.length = X` | Use `max_tip_length_to_length_ratio` in constructor |
| `DashedArrow(...)` | `DashedLine(...).add_tip()` |
| `eq[0][k]` (MathTex) | `get_part_by_tex()`, `set_color_by_tex()` |
| `SVGMobject(...)` | `Polygon`, `Circle`, `Square` |
| `ImageMobject(...)` | `colored Rectangle` |
| `from manimlib import` | `from manim import *` |

## NumberPlane Styling
```python
plane = NumberPlane(
    background_line_style={"stroke_opacity": 0.15},
    faded_line_style={"stroke_opacity": 0.08},
    faded_line_ratio=3,
).set_opacity(0.3)
```

## Error Handling

**Validation Functions in `algorithms/code_digest.py`:**
- `validate_python_syntax()` - AST parse check
- `validate_names_and_imports()` - Security check (forbidden imports/calls)
- `validate_manim_code()` - Scene structure check
- `check_code_quality()` - Quality heuristics
- `validate_latex_strings()` - LaTeX syntax check

**Error Parser in `algorithms/error_parser.py`:**
- `parse_manim_error()` - Parse stderr to structured error
- `format_error_for_prompt()` - Format for LLM fix prompt

**Overlap Detection in `algorithms/overlap_detector.py`:**
- `detect_position_collisions()` - Same position warnings
- `detect_object_accumulation()` - Too many creates without cleanup
- `detect_missing_section_cleanup()` - Comment sections without cleanup
- `detect_long_construct()` - Complex scenes without helpers
- `detect_stale_copies()` - .copy() without original removal

---

*Conventions analysis: 2026-04-04*
