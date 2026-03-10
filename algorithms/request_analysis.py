"""
Request analysis — classifies a user prompt and creates an animation storyboard.
"""
from openai import OpenAI
import os
import re

from dotenv import load_dotenv
load_dotenv()

from config import OPENAI_API_KEY, GENERATION_MODEL, FAST_MODEL
from algorithms.template_registry import TEMPLATES

def _is_codex_model(model: str) -> bool:
    return "codex" in (model or "").lower()


def _llm_text(prompt_messages, model: str) -> str:
    if _is_codex_model(model):
        parts = []
        for m in prompt_messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            parts.append(f"[{role.upper()}]\n{content}")
        input_text = "\n\n".join(parts)
        resp = client.responses.create(model=model, input=input_text)
        return resp.output_text

    response = client.chat.completions.create(model=model, messages=prompt_messages)
    return response.choices[0].message.content

    """Classify the prompt and extract metadata needed to drive generation."""
    print("[ANALYZE] Analyzing request type...")

    system_msg = """\
You are a classifier for an educational animation generator (Manim CE).

Determine the following about the user's request:
1. TYPE: EDUCATIONAL_CONCEPT | DETAILED_ANIMATION | SIMPLE_ANIMATION
2. COMPLEXITY: BASIC | INTERMEDIATE | ADVANCED
3. TOPIC: The main subject in 2–6 words
4. SUBTOPICS: 3–8 comma-separated subtopics to cover
5. DURATION: Target video length in seconds
   - BASIC educational: 120–240s
   - INTERMEDIATE educational: 240–480s
   - ADVANCED educational: 480–720s
   - Simple animations: 30–90s
6. DEPTH: SURFACE | MODERATE | DEEP
7. DOMAIN: math | physics | computer_science | chemistry | general

Respond in this EXACT format (one key per line):
TYPE: [type]
COMPLEXITY: [level]
TOPIC: [topic]
SUBTOPICS: [subtopic1, subtopic2, ...]
DURATION: [integer seconds]
DEPTH: [depth]
DOMAIN: [domain]
APPROACH: [1 sentence: main teaching approach]
"""

    defaults = {
        "type": "EDUCATIONAL_CONCEPT",
        "complexity": "INTERMEDIATE",
        "topic": prompt[:60],
        "subtopics": [],
        "duration": 300,
        "depth": "MODERATE",
        "domain": "math",
        "approach": "visual explanation with concrete examples",
    }

    try:
        result = _llm_text(
            [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Classify this request: {prompt}"},
            ],
            model=FAST_MODEL,
        )

        analysis = dict(defaults)
        for line in result.split("\n"):
            line = line.strip()
            if line.startswith("TYPE:"):
                analysis["type"] = line[5:].strip()
            elif line.startswith("COMPLEXITY:"):
                analysis["complexity"] = line[11:].strip()
            elif line.startswith("TOPIC:"):
                analysis["topic"] = line[6:].strip()
            elif line.startswith("SUBTOPICS:"):
                raw = line[10:].strip()
                analysis["subtopics"] = [s.strip() for s in raw.split(",") if s.strip()]
            elif line.startswith("DURATION:"):
                m = re.search(r"\d+", line)
                if m:
                    analysis["duration"] = int(m.group())
            elif line.startswith("DEPTH:"):
                analysis["depth"] = line[6:].strip()
            elif line.startswith("DOMAIN:"):
                analysis["domain"] = line[7:].strip()
            elif line.startswith("APPROACH:"):
                analysis["approach"] = line[9:].strip()

        print(f"[ANALYZE] [OK] type={analysis['type']} domain={analysis['domain']} duration={analysis['duration']}s")
        return analysis

    except Exception as e:
        print(f"[ANALYZE] [ERR] {e} — using defaults")
        return defaults


def create_animation_plan(prompt: str, analysis: dict) -> str:
    """Generate a detailed scene-by-scene storyboard for the animator."""
    print("[PLAN] Creating animation storyboard...")

    system_msg = """\
You are a Manim animation director. Create a precise, scene-by-scene plan.

For each scene use this format:

### SCENE N (start–end seconds): [Short scene title]
- Visual Objects: [List every Manim object needed]
- Animation Sequence: [What happens, in order, with timing]
- On-Screen Text: [Short text/formulas to display]
- ValueTracker/Dynamic: [Any live-updating elements?]
- Cleanup: [Which objects to FadeOut before the next scene]
- Transition: [How we move to the next scene — prefer Transform over FadeOut+FadeIn]

PEDAGOGICAL REQUIREMENTS (CRITICAL):
- Every concept MUST follow a "conceptual ladder":
    prerequisite → simple case → build up → full concept → takeaway
- NEVER plan a scene that is just "show formula then show result"
- ALWAYS include intermediate visual steps between introduction and conclusion
- For any transformation topic: show basis/starting state FIRST, then transform
- For any formula topic: show the geometric/visual meaning, not just the symbols

TRANSITION REQUIREMENTS:
- Plan transitions that maintain visual context
- Use Transform to morph related objects instead of removing and recreating
- NEVER plan a step that says "clear the screen" or "remove everything"
- Prefer ReplacementTransform for evolving objects (e.g., equation step-by-step)

VISUAL QUALITY:
- Grids/planes should be subtle background elements, not the main focus
- Keep the viewer's attention on the concept, not on decorations
- Every scene should have a clear focal point

REQUIREMENTS:
- Cover every subtopic in the provided list
- Each scene should be 20–60 seconds
- Include a hook (Scene 1) and a summary (last scene)
- Prefer dynamic visuals (ValueTracker, TracedPath) over static text dumps
- Every scene MUST end with explicit cleanup instructions
- Suggest which PROVEN PATTERNS are appropriate for each scene

Return ONLY the storyboard text.
"""

    try:
        plan = _llm_text(
            [
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": (
                        f"Create a storyboard for: {prompt}\n"
                        f"Duration: {analysis['duration']}s\n"
                        f"Complexity: {analysis['complexity']}\n"
                        f"Subtopics: {', '.join(analysis.get('subtopics', []))}\n"
                        f"Teaching approach: {analysis.get('approach', '')}"
                    ),
                },
            ],
            model=GENERATION_MODEL,
        )
        print("[PLAN] [OK] Storyboard created")
        return plan
    except Exception as e:
        print(f"[PLAN] [ERR] {e}")
        return "No detailed plan — create a clear educational animation covering the topic step by step."


def create_plan_json(prompt: str, analysis: dict, template_name: str = None) -> str:
    """Generate a plan-first JSON (v1) for deterministic compilation.

    If template_name is provided, the model must follow that template's slots.
    Returns a JSON string compatible with algorithms/plan/schema.py.
    """
    print("[PLAN] Creating plan JSON (v1)...")

    template_block = ""
    if template_name and template_name in TEMPLATES:
        t = TEMPLATES[template_name]
        template_block = (
            f"\nTEMPLATE SELECTED: {template_name}\n"
            f"Slots: {', '.join(t['slots'])}\n"
            f"Beats: {t['beats']}\n"
            f"Notes: {t['notes']}\n"
        )

    system_msg = f"""\
You generate plan-first JSON for Manim (schema v1). Output ONLY JSON.

Schema keys:
- version: "v1"
- meta: {{"name": string, "template"?: string}}
- objects: list of object specs
- beats: list of beat actions

Object spec:
  {{"id": str, "kind": one of [Text, MathTex, VGroup, NumberPlane, Axes, Dot, Line, Arrow, Rectangle, Circle, Square, Polygon],
   "zone": one of [top, center, bottom, full],
   "style": {{"color"?: "BLUE"|"YELLOW"|..., "font_size"?: int, "stroke_width"?: float, "stroke_opacity"?: float, "fill_opacity"?: float}},
   "params": {{"text"?: str, "tex"?: str}}}}

Beat action:
  {{"op": "create"|"write"|"fade_in"|"fade_out"|"transform"|"move_to"|"arrange"|"set_color"|"wait",
   "target"?: object id, "source"?: object id, "run_time"?: float, "wait"?: float}}

Rules:
- Always include a top title object and a bottom caption object.
- Use zones for placement (top/center/bottom) and keep visuals in center.
- Keep it deterministic; do not include arbitrary code.
- Keep the plan concise (6–10 objects, 4–6 beats).
{template_block}
"""

    try:
        plan_json = _llm_text(
            [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Create a plan JSON for: {prompt}"},
            ],
            model=GENERATION_MODEL,
        )
        print("[PLAN] [OK] Plan JSON created")
        return plan_json
    except Exception as e:
        print(f"[PLAN] [ERR] {e}")
        return ""


def create_narrated_plan(prompt: str, analysis: dict) -> str:
    """Generate a structured JSON timeline with narration text per segment.

    Used when voiceover is enabled.  Each segment contains narration text
    that will be sent to TTS, and the measured audio duration will drive
    the Manim animation timing.

    Returns a JSON string with:
    {
      "segments": [
        {
          "id": "scene_1",
          "title": "...",
          "narration": "spoken text for this segment",
          "visual_description": "what Manim should show",
          "estimated_duration": 8
        },
        ...
      ]
    }
    """
    print("[PLAN] Creating narrated animation timeline...")

    system_msg = """\
You are a Manim animation director AND narrator. Create a scene timeline with
narration text that will be spoken aloud over each scene.

Return ONLY valid JSON with this structure:
{
  "segments": [
    {
      "id": "scene_1",
      "title": "Hook / Opening",
      "narration": "The spoken narration for this segment. Write natural, conversational English suited for voice-over. 2-4 sentences max per segment.",
      "visual_description": "What the Manim animation should show: objects, transforms, text on screen. Be specific about Manim objects.",
      "estimated_duration": 8
    }
  ]
}

NARRATION RULES:
- Write for speech: short sentences, no jargon, no LaTeX notation in narration
- For math, spell it out: "two x squared" not "2x^2"
- Each segment should be 5–15 seconds of narration
- Start with a hook, end with a takeaway
- Narration should DESCRIBE what the viewer sees, not repeat on-screen text
- Use pauses implied by sentence breaks for visual breathing room

VISUAL DESCRIPTION RULES:
- Reference specific Manim objects: NumberPlane, MathTex, Arrow, Dot, ValueTracker
- Describe animations: FadeIn, Transform, Create, Write
- NOTE which objects persist vs which fade out
- Each scene should have a clear focal point

SEGMENT COUNT:
- BASIC topics: 4–8 segments
- INTERMEDIATE: 6–12 segments
- ADVANCED: 10–18 segments

Return ONLY the JSON. No markdown fences, no explanation."""

    try:
        plan_text = _llm_text(
            [
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": (
                        f"Create a narrated animation timeline for: {prompt}\n"
                        f"Duration: {analysis['duration']}s\n"
                        f"Complexity: {analysis['complexity']}\n"
                        f"Subtopics: {', '.join(analysis.get('subtopics', []))}\n"
                        f"Teaching approach: {analysis.get('approach', '')}"
                    ),
                },
            ],
            model=GENERATION_MODEL,
        ).strip()

        # Strip markdown fences if present
        if plan_text.startswith("```"):
            lines = plan_text.split("\n")
            plan_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # Validate JSON
        import json
        data = json.loads(plan_text)
        assert "segments" in data, "Missing 'segments' key"
        assert len(data["segments"]) > 0, "No segments"
        for seg in data["segments"]:
            assert "id" in seg, "Segment missing 'id'"
            assert "narration" in seg, "Segment missing 'narration'"

        print(f"[PLAN] [OK] Narrated timeline: {len(data['segments'])} segments")
        return plan_text

    except Exception as e:
        print(f"[PLAN] [ERR] Narrated plan failed: {e}")
        # Fallback: a minimal single-segment plan
        import json
        fallback = {
            "segments": [{
                "id": "scene_1",
                "title": "Full Animation",
                "narration": f"Let me explain {analysis.get('topic', 'this concept')} step by step.",
                "visual_description": "Show the concept with clear visual progression.",
                "estimated_duration": analysis.get("duration", 60),
            }]
        }
        return json.dumps(fallback)
