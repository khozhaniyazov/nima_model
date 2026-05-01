# NIMA — Fixing Aesthetics via Narrative Freedom + Layout Guardrails

## Problem (current)
NIMA’s LLM generates **Manim code** without reliable **scene awareness**:
- Elements overlap on screen.
- Objects don’t disappear on time.
- Layout becomes cluttered/off-screen.
- Overall aesthetics suffer because time/layout/occlusion aren’t treated as first-class constraints.

## Goal
Preserve **narrative freedom** (what to teach and in what sequence), while enforcing **layout/time hygiene** so outputs are consistently watchable.

## Chosen approach ("A" — minimal publishable)
Implement a **two-pass pipeline**:

1) **Scene Plan (JSON) generation** — the model outputs a structured plan (objects + beats).
2) **Deterministic compilation** — convert the plan into Manim code using a small layout engine.
3) **Validation (+ optional single repair)** — run checks (overlap/off-screen/lingering) and, if needed, ask the model to revise the *plan* once.

This provides variety in the story/steps while constraining placement to prevent visual errors.

---

## 1) Scene Plan JSON (schema v0)
### Required fields
- `title` (string)
- `objects` (list)
- `beats` (list)

### Objects
Each object must declare:
- `id` (string)
- `kind` (enum): `Title | Text | Math | Axes | Graph | Group`
- `zone` (enum): `TITLE | LEFT | RIGHT | FOOTER`
- `content` (string; for `Axes/Graph` may be a mini-DSL or parameters)

Optional object fields:
- `style`: font size, color, weight
- `max_width`: clamp width to zone
- `pin`: boolean (if true, allowed to persist across beats)

### Beats (timeline)
Each beat should be a small step in the narrative:
- `show`: list of object ids
- `hide`: list of object ids

Optional beat actions (keep minimal initially):
- `transform`: `{from: <id>, to: <id>}`
- `highlight`: `<id>`

### Example
```json
{
  "title": "Derivative of x^2",
  "objects": [
    {"id":"t","kind":"Title","zone":"TITLE","content":"Derivative of x^2","pin":true},
    {"id":"eq1","kind":"Math","zone":"LEFT","content":"f(x)=x^2"},
    {"id":"eq2","kind":"Math","zone":"LEFT","content":"f'(x)=2x"},
    {"id":"txt1","kind":"Text","zone":"RIGHT","content":"Use the power rule."}
  ],
  "beats": [
    {"show":["t","eq1","txt1"],"hide":[]},
    {"show":["eq2"],"hide":["eq1"]}
  ]
}
```

---

## 2) Layout engine (soft constraints, not rigid templates)
Use a fixed set of **zones** with margins. The model can choose narrative steps freely, but placement is constrained.

### Zones
- `TITLE`: top band, full width
- `LEFT`: left ~55% of screen
- `RIGHT`: right ~45% of screen
- `FOOTER`: bottom band (optional)

### Placement rules
- Every object is placed within its zone using deterministic helpers (`to_edge`, `shift`, consistent margins).
- Objects within the same zone are auto-arranged with `VGroup(...).arrange(DOWN, ...)` (or `RIGHT` for inline sequences).
- Clamp object width to zone (scale down if needed).

This prevents overlap/off-screen issues without forcing identical videos.

---

## 3) Validators (guardrails)
Run these checks on the compiled scene (before full render if possible):
1. **Off-screen check**: any object outside camera frame bounds.
2. **Overlap check** (within same zone): overlap area ratio above threshold.
3. **Clutter check**: too many visible objects at once (e.g., > 6).
4. **Lingering objects**: non-pinned objects must be hidden by the final beat.
5. **Tiny text**: scaled font/height below minimum threshold.
6. **Integrity**: beat references valid ids; no empty beats.

### Repair loop
If validation fails:
- Provide the model with the error list and ask for a revised **plan JSON** (not code).
- Limit to 1 repair iteration for predictability.

---

## Implementation notes (suggested file layout)
- `algorithms/scene_plan.py`: schema validation + normalization
- `algorithms/layout.py`: zones + deterministic placement helpers
- `algorithms/compiler.py`: plan → Manim Scene code
- integrate into existing pipeline: `prompt → plan → compile → validate → render`

---

## Why this meets the stated preference
- **Narrative freedom preserved**: model decides *what* steps to show and in what order.
- **Aesthetics stabilized**: deterministic layout + validators prevent overlap/lingering/off-screen.
- **Not “boring templates”**: composition is consistent, but content and beat structure can vary widely.
