from openai import OpenAI
import os
from pathlib import Path
import json

import psycopg2
from psycopg2.extras import Json, RealDictCursor


from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

MANIM_SCRIPTS = Path("C:/temp/manim_scripts")
OUTPUTS = Path("C:/temp/outputs")
MANIM_SCRIPTS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

DB_CONNECTION_STRING = "postgresql://postgres:Zk201910902!@localhost:5432/manim_db"
USE_DATABASE = True

class ManimDatabase:
    def __init__(self, connection_string: str):
        try:
            self.conn = psycopg2.connect(connection_string)
            self.conn.autocommit = True
            self.available = True
            print("[DB] Connected successfully")
        except Exception as e:
            print(f"[DB] Connection failed: {e}")
            self.conn = None
            self.available = False
    
    def save_request(self, prompt: str, analysis: dict, user_id: str = None) -> str:
        if not self.available:
            return str(uuid.uuid4())
        
        try:
            with self.conn.cursor() as cur:
                request_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO requests (
                        id, prompt, user_id, topic, domain, complexity, 
                        estimated_duration, analysis_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    request_id, prompt, user_id,
                    analysis.get('topic'), analysis.get('domain'),
                    analysis.get('complexity'), analysis.get('duration'),
                    Json(analysis)
                ))
                return request_id
        except Exception as e:
            print(f"[DB] Save request error: {e}")
            return str(uuid.uuid4())
    
    def save_generation_attempt(self, request_id: str, attempt_data: dict) -> str:
        if not self.available:
            return str(uuid.uuid4())
        
        try:
            with self.conn.cursor() as cur:
                attempt_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO generation_attempts (
                        id, request_id, attempt_number, model_version,
                        animation_plan, generated_code, code_length,
                        critique_feedback, improved_code,
                        syntax_valid, syntax_error, structure_valid,
                        quality_warnings, generation_time_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    attempt_id, request_id, attempt_data['attempt_number'],
                    'gpt-4o', attempt_data.get('plan'), attempt_data['code'],
                    len(attempt_data['code']), attempt_data.get('critique'),
                    attempt_data.get('improved_code'), attempt_data.get('syntax_valid', True),
                    attempt_data.get('syntax_error'), attempt_data.get('structure_valid', True),
                    Json(attempt_data.get('warnings', [])), attempt_data.get('generation_time_ms', 0)
                ))
                return attempt_id
        except Exception as e:
            print(f"[DB] Save attempt error: {e}")
            return str(uuid.uuid4())
    
    def save_render_job(self, request_id: str, attempt_id: str, render_data: dict) -> str:
        if not self.available:
            return str(uuid.uuid4())
        
        try:
            with self.conn.cursor() as cur:
                job_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO render_jobs (
                        id, request_id, attempt_id, final_code, script_path,
                        status, started_at, completed_at, render_duration_seconds,
                        manim_stdout, manim_stderr, return_code, video_path,
                        error_type, error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    job_id, request_id, attempt_id, render_data['code'],
                    render_data.get('script_path'), render_data['status'],
                    render_data.get('started_at'), render_data.get('completed_at'),
                    render_data.get('duration'), render_data.get('stdout'),
                    render_data.get('stderr'), render_data.get('return_code'),
                    render_data.get('video_path'), render_data.get('error_type'),
                    render_data.get('error_message')
                ))
                return job_id
        except Exception as e:
            print(f"[DB] Save render error: {e}")
            return str(uuid.uuid4())
    
    def save_ai_evaluation(self, request_id: str, render_job_id: str, evaluation: dict) -> str:
        if not self.available:
            return str(uuid.uuid4())
        
        try:
            with self.conn.cursor() as cur:
                eval_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO ai_evaluations (
                        id, request_id, render_job_id, evaluator_model,
                        visual_quality_score, educational_value_score,
                        technical_accuracy_score, pacing_timing_score,
                        clarity_score, engagement_score, overall_score,
                        strengths, weaknesses, specific_issues, suggestions,
                        predicted_satisfaction, full_evaluation_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    eval_id, request_id, render_job_id, 'gpt-4o',
                    evaluation.get('visual_quality', 0), evaluation.get('educational_value', 0),
                    evaluation.get('technical_accuracy', 0), evaluation.get('pacing_timing', 0),
                    evaluation.get('clarity', 0), evaluation.get('engagement', 0),
                    evaluation.get('overall', 0), evaluation.get('strengths'),
                    evaluation.get('weaknesses'), Json(evaluation.get('issues', [])),
                    evaluation.get('suggestions'), evaluation.get('predicted_satisfaction', 0),
                    Json(evaluation)
                ))
                return eval_id
        except Exception as e:
            print(f"[DB] Save evaluation error: {e}")
            return str(uuid.uuid4())
    
    def get_best_examples(self, domain: str = None, limit: int = 3) -> list:
        if not self.available:
            return []
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT r.prompt, r.domain, r.topic, rj.final_code, ae.overall_score
                    FROM requests r
                    JOIN render_jobs rj ON r.id = rj.request_id
                    JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                    WHERE rj.status = 'done' AND ae.overall_score >= 80
                """
                params = []
                if domain:
                    query += " AND r.domain = %s"
                    params.append(domain)
                query += " ORDER BY ae.overall_score DESC LIMIT %s"
                params.append(limit)
                
                cur.execute(query, params)
                return cur.fetchall()
        except Exception as e:
            print(f"[DB] Get examples error: {e}")
            return []
    
    def get_error_patterns(self, limit: int = 5) -> list:
        if not self.available:
            return []
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT error_category, root_cause, fix_description, occurrence_count
                    FROM error_patterns
                    WHERE NOT resolved
                    ORDER BY occurrence_count DESC
                    LIMIT %s
                """, (limit,))
                return cur.fetchall()
        except Exception as e:
            print(f"[DB] Get errors error: {e}")
            return []
    
    def record_error_pattern(self, error_data: dict):
        if not self.available:
            return
        
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT id, occurrence_count FROM error_patterns
                    WHERE error_signature = %s
                """, (error_data['signature'],))
                result = cur.fetchone()
                
                if result:
                    cur.execute("""
                        UPDATE error_patterns
                        SET occurrence_count = occurrence_count + 1, last_seen = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (result[0],))
                else:
                    cur.execute("""
                        INSERT INTO error_patterns (
                            id, error_category, error_signature, example_error_message,
                            example_code_snippet, root_cause, fix_description
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        str(uuid.uuid4()), error_data['category'], error_data['signature'],
                        error_data['message'], error_data.get('code_snippet'),
                        error_data.get('root_cause', 'Unknown'),
                        error_data.get('fix', 'Check syntax and API usage')
                    ))
        except Exception as e:
            print(f"[DB] Record error error: {e}")

db = ManimDatabase(DB_CONNECTION_STRING) if USE_DATABASE else None

LAYOUT_HELPERS = """
# === AUTO-INJECTED LAYOUT SAFETY HELPERS ===
from manim import config

def smart_text(text_str, max_width=12, font_size=24):
    '''Auto-wrap and scale text to fit screen.'''
    t = Text(text_str, font_size=font_size)
    if t.width > max_width:
        t = t.scale_to_fit_width(max_width)
    return t

def fit_to_screen(mobject, margin=1):
    '''Scale any object to fit within screen bounds.'''
    target_width = config.frame_width - margin
    target_height = config.frame_height - margin
    if mobject.width > target_width:
        mobject.scale(target_width / mobject.width)
    if mobject.height > target_height:
        mobject.scale(target_height / mobject.height)
    return mobject

def safe_position(mobject, edge=UP, buff=0.5):
    '''Position object safely at screen edge.'''
    return mobject.to_edge(edge, buff=buff)

# === END HELPERS ===

"""

GOLDEN_PATTERNS = {
    "math_function_graph": """
# PROVEN PATTERN: Function Graphing
axes = Axes(
    x_range=[-5, 5, 1],
    y_range=[-5, 5, 1],
    x_length=10,
    y_length=6,
).add_coordinates()

graph = axes.plot(lambda x: x**2, color=BLUE)
label = axes.get_graph_label(graph, label='f(x)=x²').scale(0.7)

self.play(Create(axes), run_time=1.5)
self.play(Create(graph), Write(label), run_time=2)
self.wait(2)
""",
    
    "math_group_operation": """
# PROVEN PATTERN: Group Operations
elements = VGroup(*[
    Text(str(i), font_size=36) for i in range(4)
]).arrange(RIGHT, buff=0.8)

operation_label = Text("Group G = {0,1,2,3}", font_size=28).to_edge(UP)

# Show operation: 2 + 3 = 1
elem1 = elements[2].copy().set_color(YELLOW)
elem2 = elements[3].copy().set_color(YELLOW)
result = Text("Result: 1", font_size=36, color=GREEN)

self.add(operation_label)
self.play(Create(elements))
self.wait(1)
self.play(Indicate(elem1), Indicate(elem2))
self.wait(1)
self.play(Write(result))
self.wait(2)
""",
    
    "stepbystep_calculation": """
# PROVEN PATTERN: Step-by-Step Calculation
steps = VGroup(
    Text("Given: f(x+y) = f(x) + f(y)", font_size=28),
    Text("Check: f(2+3) vs f(2)+f(3)", font_size=28, color=YELLOW),
    Text("LHS: f(5) = 10", font_size=28, color=BLUE),
    Text("RHS: f(2)+f(3) = 4+6 = 10", font_size=28, color=BLUE),
    Text(" Property holds!", font_size=32, color=GREEN)
).arrange(DOWN, aligned_edge=LEFT, buff=0.4)

for i, step in enumerate(steps):
    self.play(Write(step), run_time=1)
    self.wait(1.5)
    if i < len(steps) - 1:
        self.play(Indicate(step))
self.wait(2)
""",
    
    "algorithm_visualization": """
# PROVEN PATTERN: Algorithm Step-by-Step
array = VGroup(*[
    Square(side_length=0.8).add(Text(str(val), font_size=28))
    for val in [5, 2, 8, 1, 9]
]).arrange(RIGHT, buff=0.3)

title = Text("Sorting Algorithm", font_size=36).to_edge(UP)

self.add(title)
self.play(Create(array))
self.wait(1)

# Highlight comparison
self.play(
    array[0].animate.set_color(YELLOW),
    array[1].animate.set_color(YELLOW)
)
self.wait(1)

# Show swap
self.play(
    array[0].animate.shift(RIGHT*1.1),
    array[1].animate.shift(LEFT*1.1),
    run_time=1.5
)
self.wait(2)
"""
}


def get_domain_specific_guidance(domain: str) -> str:
    
    domain_guides = {
        'math': """
**MATHEMATICAL VISUALIZATION:**
- Show visual proofs, not just equations
- Use geometric interpretations when possible
- Animate transformations smoothly
- Show concrete examples before abstraction
- Use color to distinguish mathematical objects
- Show multiple representations (geometric, algebraic, numeric)
- Animate limiting processes and convergence
- Use number lines, coordinate systems, and graphs

Example: For derivatives:
1. Show a curve
2. Point moving along it
3. Secant line following
4. Secant → tangent as Δx → 0
5. Slope calculation updating real-time
""",
        'physics': """
**PHYSICS VISUALIZATION:**
- Show forces as colored arrows (magnitude = length)
- Animate motion with proper physics
- Use vector fields for field concepts
- Show energy transformations with color changes
- Display before/after states
- Animate time evolution with sliders/clocks
- Show action-reaction pairs
- Use particle systems for complex phenomena
""",
        'computer_science': """
**CS VISUALIZATION:**
- Use boxes/nodes for data structures
- Animate algorithm execution step-by-step with highlighting
- Show memory state changes with colors
- Use pointer arrows for references
- Display complexity with growing graphs
- Show call stacks for recursion
- Animate tree/graph traversals
- Use side-by-side comparisons for efficiency
""",
        'chemistry': """
**CHEMISTRY VISUALIZATION:**
- Show molecular structures in 3D
- Animate bond formation/breaking
- Use color for different atoms (standard CPK colors)
- Show electron movement with arrows
- Animate reaction mechanisms step-by-step
- Display energy diagrams alongside
- Show state changes with transitions
"""
    }
    
    return domain_guides.get(domain, "")

def generate_manim_code(prompt: str, analysis: dict, plan: str, attempt: int = 1) -> str:
    print(f"[GENERATING] Attempt {attempt}: Generating code...")
    golden_example = retrieve_golden_example(analysis['domain'], analysis['topic'])
    error_warnings = get_error_warnings()
    domain_guidance = get_domain_specific_guidance(analysis['domain'])
    
    if analysis['type'] == 'EDUCATIONAL_CONCEPT':
        system_msg = f"""You are a MASTER Manim animator creating {analysis['duration']//60}+ min video on "{analysis['topic']}".

=== GOLDEN EXAMPLE (COPY THIS STRUCTURE) ===
{golden_example}

{error_warnings}

=== CRITICAL SCENE MANAGEMENT RULES ===

**1. SCREEN ZONES**
Track objects by zones to prevent overlap:
- TOP: Persistent title bar
- CENTER: Main visual content (changes per scene)
- BOTTOM: Narration/explanation text
- CORNERS: Reference info (formulas, legends)

**2. CLEANUP PROTOCOL**
Always remove or replace old content before adding new:
```python
# Explicit fadeout
self.play(FadeOut(old_group))

# Transform/replace
self.play(Transform(old_text, new_text))

# Remove specific objects
self.remove(old_diagram, old_label)

# Full reset between major sections
self.clear()
self.wait(0.5)

3. **Object Lifecycle Management:**
   ```python
   # Track objects by zone
   # Track objects
    current_center = None
    current_bottom = None

    # Remove old center content
    if current_center:
        self.play(FadeOut(current_center))

    current_center = new_diagram
    self.play(Create(current_center))
    ```

4. **Persistent vs Temporary:**
   ```python
    # Persistent (stays for full video)
    title = Text("Topic").to_edge(UP)
    self.add(title)

    # Temporary (scene-specific)
    explanation = Text("...").to_edge(DOWN)
    self.play(Write(explanation))
    self.play(FadeOut(explanation))

   ```
5. UP-TO-DATE ALGORITHMS

Always consult the Manim Community documentation (https://docs.manim.community/en/stable/) to ensure usage of the latest functions, classes, and algorithms.

Replace deprecated methods with current equivalents.

Verify that your visualizations follow best practices recommended by the community.

=== STORYBOARD TO FOLLOW ===
{plan}

=== STRUCTURE ===

**Act 1: Hook (30s)**
```python
def construct(self):
    # Persistent title
    title = Text("{analysis['topic']}", font_size=48).to_edge(UP)
    self.add(title)

    # Hook visual & text
    hook_visual = create_hook()
    hook_text = Text("Question/Hook").to_edge(DOWN)
    self.play(Create(hook_visual))
    self.play(Write(hook_text))
    self.wait(3)

    # Cleanup
    self.play(FadeOut(hook_visual), FadeOut(hook_text))
    self.wait(0.5)
```

**Act 2-4: Main Content (scenes)**
For each scene:
1. Clear previous scene's content
2. Add new content
3. Animate/explain
4. Pause for comprehension
5. Remove temporary elements

```python
    # === SCENE 1: First Concept ===
    # Example Scene
    self.clear()
    self.add(title)

    scene_content = VGroup(...)
    scene_text = Text("...").to_edge(DOWN)

    self.play(FadeIn(scene_content))
    self.play(Write(scene_text))
    self.wait(3)

    self.play(Indicate(scene_content[0]))
    self.wait(2)

    # Cleanup
    self.play(FadeOut(scene_content), FadeOut(scene_text))
    self.wait(0.5)
```

**Act 5: Conclusion**
```python
    self.clear()
    summary = create_summary()
    self.play(FadeIn(summary))
    self.wait(4)
    self.play(FadeOut(summary))

```

=== DOMAIN-SPECIFIC GUIDANCE ===
{domain_guidance}

=== CODE QUALITY CHECKLIST ===
Before returning, verify:
 Clear scene transitions (no overlap)
 Proper cleanup (FadeOut/clear before new content)
 Adequate wait times
 Visual representations for all concepts
 Smooth narrative flow
 {analysis['duration']}+ seconds duration
 Engaging throughout (no boring moments)

=== EXAMPLE STRUCTURE ===
```python
from manim import *

class GeneratedScene(Scene):
    def construct(self):
        # Persistent title
        title = Text("Topic", font_size=44).to_edge(UP)
        self.add(title)

        # === SCENE 1 ===
        intro = Text("Introduction").to_edge(DOWN)
        diagram1 = Circle()
        self.play(Create(diagram1))
        self.play(Write(intro))
        self.wait(2)

        # Cleanup
        self.play(FadeOut(diagram1), FadeOut(intro))
        self.wait(0.5)

        # === SCENE 2 ===
        diagram2 = Square()
        explanation = Text("Next concept").to_edge(DOWN)
        self.play(Create(diagram2))
        self.play(Write(explanation))
        self.wait(2)

        # === FINAL ===
        self.clear()
        finale = Text("Key Takeaway")
        self.play(Write(finale))
        self.wait(3)
        self.play(FadeOut(finale))

```

Target: {analysis['duration']}+ seconds
Subtopics: {', '.join(analysis['subtopics'])}

Return ONLY complete, production-ready Manim code with proper scene management."""

    else:
        system_msg = """Create sophisticated Manim animation with proper cleanup.

Rules:
- Clean up old content before adding new
- Use FadeOut before FadeIn in same location
- Track what's on screen
- Smooth transitions

Return ONLY code."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Create: {prompt}"}
            ],
            max_tokens=15000
        )
        code = response.choices[0].message.content
        print(f"[GENERATING]  Code generated ({len(code)} chars)")
        return extract_code(code)
    except Exception as e:
        print(f"[GENERATING]  Error: {str(e)}")
        raise Exception(f"AI generation failed: {str(e)}")

def self_critique_and_improve(code: str, prompt: str, analysis: dict) -> str:
    print(f"[SELF-IMPROVE] Self-reviewing code...")
    
    system_msg = """You are a MANIM SELF-CRITIQUE & IMPROVEMENT ENGINE.

Your job is to take the previously-generated Manim code and FIX STRUCTURAL PROBLEMS
*before* it goes into the strict overlapping_fix stage.

DO NOT enforce layout zones.
DO NOT rewrite visuals unless necessary.
DO NOT restructure the entire animation.
Only apply essential cleanup and structural improvements.

===========================================================
PART 1 — COMMON ERRORS TO ELIMINATE (STRICT)
===========================================================

You MUST detect and fix:

1. **Lingering objects**
   - Old math formulas, graphs, polygons, axes, or text must be removed
     before new content appears in the same visual area.
   - Always use FadeOut(), clear(), remove() where appropriate.

2. **Bottom-edge text collisions**
   - Prevent long text lines from spilling outside the frame.
   - Scale them down automatically.

3. **Oversized or misplaced elements**
   - Scale visuals so they fit comfortably near ORIGIN.
   - No arbitrary shifts off-screen.

4. **Dense clutter**
   - No more than 3 unrelated visuals on screen at once unless grouped.
   - Use VGroup().arrange(DOWN/RIGHT) when elements logically belong together.

5. **Unbalanced pacing**
   - Add wait() after important reveals.
   - Remove excessively long sequences with no animation.

6. **Unnecessary objects**
   - Remove SVGs, ImageMobjects, emojis (replace with [OK], [X]).

7. **Missing transitions**
   - Every major step must begin with a cleared scene OR a FadeOut of old objects.

===========================================================
PART 2 — IMPROVEMENTS YOU MUST APPLY
===========================================================

You MUST:

 Add FadeOut(old_text) before writing new text  
 Add FadeOut(old_visuals) before replacing diagrams  
 Add self.clear() for major section changes  
 Use concise smooth animations (FadeIn, FadeOut, Write, Create, Transform)  
 Ensure consistent scaling: main visuals ~0.8–1.2 range  
 Keep text readable: no overflowing off-screen  

Do NOT add:
 Zone layout rules  
 New content or explanations  
 Fancy animations  
 Movement unless needed for clarity  

===========================================================
PART 3 — OUTPUT REQUIREMENTS
===========================================================

Return ONLY the improved Manim code block.
Do NOT explain changes.
Do NOT add analysis or commentary.

Your output MUST be runnable Manim Community Edition code."""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Original prompt: {prompt}\n\nCode to improve:\n{code}"}
            ],
            max_tokens=15000
        )
        improved = response.choices[0].message.content
        print(f"[SELF-IMPROVE]  Code improved")
        return extract_code(improved)
    except Exception as e:
        print(f"[SELF-IMPROVE]  Error: {str(e)}, using original")
        return code

def polish_manim_code(code: str) -> str:
    print(f"[POLISH] Polishing code...")
    
    system_msg = """Fix syntax/runtime errors in this Manim code.

Common issues:
- Undefined variables
- Missing imports
- Wrong API calls
- Indentation errors

Return ONLY corrected code."""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": code}
            ],
            max_tokens=15000
        )
        return extract_code(response.choices[0].message.content)
    except Exception as e:
        print(f"[POLISH]  Error: {str(e)}")
        return code

def overlapping_fix(code: str, prompt: str, analysis: dict) -> str:
    print(f"[AESTHETICS] Check for overlapping...")
    
    system_msg = f"""You are an expert AI specialized in generating **Manim Community Edition (CE) v0.18.0** code that is visually clean, professional, non-overlapping, and consistently structured.
Your ONLY task: take imperfect Manim code and rewrite it so the layout is clean, centered, spaced correctly, and contains NO visual overlap.

===========================
GLOBAL SCREEN LAYOUT RULES
===========================

### 1. TOP ZONE — Persistent Title Only
- The top 10–15% of the frame is reserved exclusively for a **persistent title**.
- The title is created once at the start and stays for the entire scene.
- The title must NEVER overlap visuals or bottom text.
- After each `self.clear()`, you must re-add the title.

### 2. CENTER ZONE — All Visuals
- The middle ~70% of the frame is for graphs, shapes, equations, diagrams, etc.
- All visuals must be kept **inside this region**.
- ALWAYS avoid overlap by:
  - Using `VGroup` and arranging with:
      • `arrange(DOWN)`  
      • `arrange(RIGHT)`  
      • `arrange_in_grid()`  
  - Applying `.scale_to_fit_height()` or `.scale(0.8)` when large.
  - Adding padding of **0.5–1.0 units** between items.
- Before introducing new visuals:
  - `FadeOut` or slide away all previous center visuals.
  - Do NOT stack new visuals on top of old ones.
- Visuals must never drift into the bottom text zone.

### 3. BOTTOM ZONE — Supporting Text
- Bottom 10–15% of frame is only for short explanations.
- Always use `.to_edge(DOWN)` or `.next_to(..., DOWN)`.
- Before writing new explanation, `FadeOut` the previous one.
- Explanation text may not overlap center visuals under any circumstance.

===========================
TRANSITIONS & CLEANUP RULES
===========================

### 4. Scene Segmentation
- Every conceptual step must be clearly separated using comments:
  `### SCENE 1`, `### SCENE 2`, etc.

### 5. Cleanup Requirements
- Before a new scene or major transition:
  - Use `self.clear()` **AND** re-add the persistent title.
  - Ensure **no leftover visuals** remain on screen.
  - Bottom text from the previous scene must be removed.

### 6. Animations
- Use clean, educational animations only:  
  `FadeIn`, `FadeOut`, `Create`, `Write`, `Transform`.
- Avoid unnecessary movement, rotation, bouncing, or clutter.

### 7. Variable & Object Management
- Each scene must use unique variable names (`text1`, `text2`, `graph1`, `graph2`, etc.).
- Group related elements with `VGroup` so they can be faded out together.
- Remove all unused variables.

===========================
QUALITY & AESTHETICS RULES
===========================

### 8. Code Clarity
- Use consistent indentation and spacing.
- Maintain strict visual hierarchy:
  - Title (top)
  - Visuals (center)
  - Explanation (bottom)

### 9. Validate Before Returning Code
The output MUST satisfy all of the following:

- No object overlaps another.
- No object leaves the frame unexpectedly.
- Title is persistent and never displaced.
- Bottom text always stays bottom.
- Visuals are centered, cleanly spaced, and fade out properly.
- No stacked animations without clearing.
- Code is syntactically correct for Manim CE v0.18.0.

===========================
FINAL OUTPUT REQUIREMENTS
===========================

- Produce a **single complete Scene class**.
- You MUST rewrite the input code to follow every rule.
- Do not remove content unless absolutely necessary to fix layout.
- Preserve the user’s logic and narrative.
- RETURN **ONLY** the final Manim code — no explanation, no comments besides section headers."""
        
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Original prompt: {prompt}\n\nCode to improve:\n{code}"}
            ],
            max_tokens=15000
        )
        overlapped = response.choices[0].message.content
        print(f"[AESTHETICS] Nothing is overlapping")
        return extract_code(overlapped)
    except Exception as e:
        print(f"[AESTHETICS] Error: {str(e)}, using original")
        return code

def ai_fix(code: str, prompt: str, analysis: dict) -> str:
    print(f"[DEBUGGER] AI fix")
    
    system_msg = f"""You are an AI Manim Code Debugger specialized in detecting errors, fixing them, and ensuring full compatibility with the MANIM COMMUNITY EDITION (CE) v0.18.0.
ONLY TWO VERY IMPORTANT RULES:
- Remove SVGMobject, ImageMobject
- Replace emojis with [OK], [X]

Your tasks:
1. Parse the Manim code.
2. Check for Python errors, syntax issues, logic bugs, missing imports, and wrong API usage.
3. Validate all functions, classes, and methods against the Manim Community v0.18.0 documentation:
   https://docs.manim.community/en/stable/
4. Ensure the code uses only valid:
   - classes (e.g., Scene, MovingCameraScene, Graph, NumberPlane, VGroup…)
   - animations (FadeIn, Create, Transform, Write, Uncreate…)
   - mobjects (MathTex, Text, Dot, Line, Arrow, Rectangle, SVGMobject…)
   - methods (next_to, shift, scale, animate, set_color…)
   - camera controls (self.camera.frame)
   - configuration patterns (CONFIG removed, use __init__)
5. Confirm all imports follow the current structure:
       from manim import *
6. Confirm code is scene-based and ends with a proper Scene class definition.

CODE CORRECTION RULES:
- Rewrite buggy code into fully functional Manim v0.18.0-compliant code.
- Replace deprecated features with their v0.18.0 equivalents.
- Ensure scenes are structured correctly: class MyScene(Scene): def construct(self): ...
- Fix indentations, missing parentheses, animation syntax, and transform syntax.
- Ensure animations use `.animate` correctly.
- Ensure all objects referenced in animations are defined beforehand.
- Add missing FadeOut/Uncreate or self.clear() where appropriate.
- Remove overlapping elements unless explicitly intended.

VISUAL CORRECTNESS CHECK:
- No objects should float off-screen unless intended.
- Avoid clutter: group objects (VGroup), position them with .next_to()/.to_edge()/.to_corner().
- Use consistent colors and clear camera framing.
- Use wait() where pauses are needed.
- Ensure smooth animation sequences with proper timing.

MATHEMATICAL CORRECTNESS:
- Check expressions in MathTex for syntax errors.
- Ensure symbols requiring LaTeX packages are either valid or replaced.
- Check equations for missing curly braces.

ALGORITHM / FUNCTION VALIDATION:
For any helper functions, algorithms, or utilities:
- Ensure they do not conflict with Manim's internal classes.
- Ensure they process inputs safely.
- Ensure they follow Pythonic conventions.
- Ensure that their outputs are compatible with Manim objects or animations.
- Confirm there are no side effects that break the Scene workflow.

STRICT REQUIREMENTS FOR YOUR RESPONSES:
- If code is valid, return “Code is valid” and summarize why.
- If code is invalid, return the corrected, fully functional Manim CE v0.18.0 code.
- Do NOT invent new API features. Use only what exists in the official documentation.
- Never output partial code. Output full, runnable code blocks.
- Do NOT include explanations.

OUTPUT FORMAT:
1. If perfect:
     Code is valid.
2. If issues exist:
     ```python
     # Corrected Manim CE v0.18.0-compatible code
     ...
     ```

Be strict, deterministic, and fully aligned with the official Manim CE v0.18.0 documentation.
"""
        
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Original prompt: {prompt}\n\nCode to improve:\n{code}"}
            ],
            max_tokens=15000
        )
        debugged = response.choices[0].message.content
        print(f"[DEBUGGIN] Code debugged")
        return extract_code(debugged)
    except Exception as e:
        print(f"[DEBUGGIN] Error: {str(e)}, using original")
        return code

def extract_code(text: str) -> str:
    if "```python" in text:
        return text.split("```python")[1].split("```")[0].strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            return parts[1].strip("python").strip()
    return text.strip()

def inject_helpers(code: str) -> str:
    if "from manim import *" in code:
        return code.replace("from manim import *", "from manim import *\n" + LAYOUT_HELPERS)
    return LAYOUT_HELPERS + "\n" + code

def retrieve_golden_example(domain: str, topic: str) -> str:
    print(f"[RAG] Retrieving example for {domain}/{topic}")
    
    if db and db.available:
        examples = db.get_best_examples(domain=domain, limit=1)
        if examples:
            print(f"[RAG] Found DB example (score: {examples[0]['overall_score']})")
            return f"# High-quality example (score: {examples[0]['overall_score']}/100)\n{examples[0]['final_code'][:800]}\n# ... (truncated)\n"
    if domain == 'math':
        if 'group' in topic.lower() or 'homomorphism' in topic.lower():
            return GOLDEN_PATTERNS['math_group_operation']
        elif 'function' in topic.lower() or 'graph' in topic.lower():
            return GOLDEN_PATTERNS['math_function_graph']
        elif 'calculation' in topic.lower() or 'step' in topic.lower():
            return GOLDEN_PATTERNS['stepbystep_calculation']
    
    if domain == 'computer_science':
        return GOLDEN_PATTERNS['algorithm_visualization']
    
    return ""

def get_error_warnings() -> str:
    if not db or not db.available:
        return ""
    
    patterns = db.get_error_patterns(limit=5)
    if not patterns:
        return ""
    
    warnings = "\n=== COMMON ERRORS TO AVOID ===\n"
    for pattern in patterns:
        warnings += f" {pattern['error_category']}: {pattern['root_cause']}\n"
        warnings += f"   Fix: {pattern['fix_description']}\n\n"
    
    return warnings

def evaluate_with_gpt4(code: str, video_path: str, prompt: str, execution_data: dict) -> dict:
    print(f"[EVAL] Evaluating with GPT-4...")
    
    evaluation_prompt = f"""Evaluate this Manim animation.

**Request:** {prompt}
**Status:** {execution_data['status']}
**Duration:** {execution_data.get('duration', 'N/A')}s
**Errors:** {execution_data.get('error', 'None')}

**Code Preview:**
```python
{code[:1000]}...
```

Evaluate (0-100 each):
1. Visual Quality - Layout, colors, no overlaps
2. Educational Value - Clear explanations, examples
3. Technical Accuracy - Correct math/science
4. Pacing & Timing - Appropriate speed
5. Clarity - Easy to understand
6. Engagement - Interesting, dynamic

Respond in JSON:
{{
  "visual_quality": 85,
  "educational_value": 90,
  "technical_accuracy": 80,
  "pacing_timing": 75,
  "clarity": 88,
  "engagement": 82,
  "overall": 83,
  "strengths": ["point 1", "point 2"],
  "weaknesses": ["point 1"],
  "issues": ["issue 1"],
  "suggestions": "...",
  "predicted_satisfaction": 85
}}"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an educational video evaluator."},
                {"role": "user", "content": evaluation_prompt}
            ],
            temperature=0.3
        )
        
        result_text = response.choices[0].message.content
        
        if "```json" in result_text:
            json_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            json_text = result_text.split("```")[1].split("```")[0].strip()
        else:
            json_text = result_text
        
        evaluation = json.loads(json_text)
        print(f"[EVAL]  Score: {evaluation.get('overall', 0)}/100")
        return evaluation
    except Exception as e:
        print(f"[EVAL]  Error: {e}")
        return {"overall": 0, "error": str(e)}














#RAG SYSTEM = 






#database -> 

#database of valid codes

#banned codes

#factcheck

