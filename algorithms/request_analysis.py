from openai import OpenAI
from pathlib import Path
import os
import re

from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def analyze_request_type(prompt: str) -> dict:
    print(f"[ANALYZE] Analyzing request type...")
    
    system_msg = """You are a request classifier for an educational animation generator.

Determine:
1. TYPE: DETAILED_ANIMATION / EDUCATIONAL_CONCEPT / SIMPLE_ANIMATION
2. COMPLEXITY: BASIC / INTERMEDIATE / ADVANCED
3. TOPIC: Main subject
4. SUBTOPICS: Key subtopics (3-8 for comprehensive coverage)
5. DURATION: Optimal video length in seconds (180-900 for educational, 30-120 for animations)
6. DEPTH: SURFACE / MODERATE / DEEP
7. DOMAIN: math / physics / computer_science / chemistry / general

For educational content:
- BASIC: 180-300 seconds
- INTERMEDIATE: 300-600 seconds  
- ADVANCED: 600-900 seconds

Respond in format:
TYPE: [type]
COMPLEXITY: [level]
TOPIC: [topic]
SUBTOPICS: [subtopic1, subtopic2, ...]
DURATION: [seconds]
DEPTH: [depth]
DOMAIN: [domain]
APPROACH: [teaching approach]
"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Classify: {prompt}"}
            ],
        )
        
        result = response.choices[0].message.content
        
        analysis = {
            'type': 'EDUCATIONAL_CONCEPT',
            'complexity': 'INTERMEDIATE',
            'topic': '',
            'subtopics': [],
            'duration': 300,
            'depth': 'MODERATE',
            'domain': 'general',
            'approach': ''
        }
        
        for line in result.split('\n'):
            if line.startswith('TYPE:'):
                analysis['type'] = line.replace('TYPE:', '').strip()
            elif line.startswith('COMPLEXITY:'):
                analysis['complexity'] = line.replace('COMPLEXITY:', '').strip()
            elif line.startswith('TOPIC:'):
                analysis['topic'] = line.replace('TOPIC:', '').strip()
            elif line.startswith('SUBTOPICS:'):
                subtopics = line.replace('SUBTOPICS:', '').strip()
                analysis['subtopics'] = [s.strip() for s in subtopics.split(',')]
            elif line.startswith('DURATION:'):
                try:
                    analysis['duration'] = int(re.search(r'\d+', line).group())
                except:
                    analysis['duration'] = 300
            elif line.startswith('DEPTH:'):
                analysis['depth'] = line.replace('DEPTH:', '').strip()
            elif line.startswith('DOMAIN:'):
                analysis['domain'] = line.replace('DOMAIN:', '').strip()
            elif line.startswith('APPROACH:'):
                analysis['approach'] = line.replace('APPROACH:', '').strip()
        
        print(f"[ANALYZE] Type: {analysis['type']}, Domain: {analysis['domain']}, Duration: {analysis['duration']}s")
        return analysis
        
    except Exception as e:
        print(f"[ANALYZE]  Error: {str(e)}")
        return {
            'type': 'EDUCATIONAL_CONCEPT',
            'complexity': 'INTERMEDIATE',
            'topic': prompt,
            'subtopics': [],
            'duration': 300,
            'depth': 'MODERATE',
            'domain': 'general',
            'approach': 'comprehensive visualization'
        }

def create_animation_plan(prompt: str, analysis: dict) -> str:
    print(f"[PLAN] Creating animation storyboard...")
    
    system_msg = """You are an animation director creating a detailed scene plan.

For the given topic, generate a fully detailed MANIM ANIMATION PLAN.

STRUCTURE:
Break the animation into well-defined scenes. Each scene must follow this format:

SCENE X (start–end seconds): [Scene title]
- Visual Elements:
  List every object that appears (shapes, graphs, axes, equations, matrices, characters, arrows, highlights, images, etc.)
- Animation:
  Describe exactly what happens (Write, FadeIn, Transform, Indicate, Create, MoveAlongPath, ReplacementTransform, etc.)
  Include timing beats and pacing notes (e.g., “pause here for 1s for comprehension”).
- Text / Narration:
  Write any on-screen text OR voiceover lines. Prefer minimal text and rely on visuals when possible.
- Transitions:
  Specify transition style to next scene (FadeOut, Dissolve, Slide, Camera pan, Zoom-in, etc.)
- Cleanup:
  Specify what must be removed before the next scene (FadeOut, Uncreate, self.clear, removal of labels while keeping axes, etc.)

ADDITIONAL REQUIREMENTS:
- Include durations for each scene (e.g., 0–7s, 7–18s).
- Ensure no scene has overlapping content unless intentional.
- Replace pure text explanations with visual metaphors whenever possible.
- Maintain a clean visual hierarchy (foreground vs. background objects).
- Include camera movements where helpful (zoom on key expressions, pan to new section).
- Ensure every major segment ends with proper cleanup (FadeOut, Uncreate, or self.clear).
- Include transitions that feel smooth and logical.
- Scenes should build understanding step-by-step (progressive reveal).
- Include optional alternative visual ideas when relevant.

RULES FOR ELEMENT PLACEMENT AND SCENE MANAGEMENT:

1. **Initial Placement**
   - Introduce the first element at the **center of the screen**.
   - Any subsequent elements must not overlap with existing ones.

2. **Dynamic Relocation (Swim Strategy)**
   - When a new element is introduced, all existing elements **should smoothly move to an unoccupied position**:
     - Use corners/edges first: `UPPER_LEFT`, `UPPER_RIGHT`, `LOWER_LEFT`, `LOWER_RIGHT`.
     - Then intermediate positions: `TOP_CENTER`, `BOTTOM_CENTER`, `CENTER_LEFT`, `CENTER_RIGHT`.
   - Movement should be animated using `.animate.shift(...)` or `.animate.move_to(...)` for smooth transitions.

3. **Stacking & Hierarchy**
   - Avoid vertical or horizontal stacking that blocks previously displayed equations or visuals.
   - Keep related elements together (group with `VGroup`) and move them as a single unit.
   - Maintain clear **visual hierarchy**: titles at top, main equation slightly below, supporting calculations grouped nearby.

4. **Scene Flow**
   - Introduce new elements one at a time.
   - Apply `wait()` after each introduction to allow viewers to comprehend.
   - After introducing a new element, **relocate older elements** if needed to make space.

5. **Automatic Cleanup**
   - Fade out or uncreate elements only when they are no longer referenced.
   - Prefer `FadeOut(element)` over `self.clear()` unless transitioning to a completely new major scene.

6. **Camera Management**
   - Pan or zoom subtly to focus on the new element if it’s far from the center.
   - Avoid abrupt jumps.

7. **Colors & Consistency**
   - Maintain consistent coloring and font sizes for types of elements:
     - Primary equations: BLUE or RED
     - Supporting calculations: YELLOW or GREEN
     - Titles: WHITE

8. **Output Requirements**
   - Return only the **Manim code** implementing the placement strategy.
   - Include comments marking:
     - Initial placement
     - Element relocation
     - FadeOut/cleanup actions
   - Ensure no element visually overlaps another at any point.
   - Use `VGroup` to manage groups of related elements.

EXAMPLE STRATEGY (conceptual):
1. Introduce Equation 1 at CENTER.
2. Introduce Equation 2:
   - Animate Equation 1 to UPPER_LEFT
   - Place Equation 2 at CENTER
3. Introduce Equation 3:
   - Animate Equation 1 to UPPER_LEFT (already there, no change)
   - Animate Equation 2 to UPPER_RIGHT
   - Place Equation 3 at CENTER
4. Repeat as new elements are introduced, keeping elements moving to **available zones**.


OUTPUT:
Return ONLY the full scene-by-scene plan using the required format.
"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Create scene plan for: {prompt}\n\nDuration: {analysis['duration']}s\nSubtopics: {', '.join(analysis['subtopics'])}"}
            ],
        )
        
        plan = response.choices[0].message.content
        print(f"[PLAN]  Storyboard created")
        return plan
        
    except Exception as e:
        print(f"[PLAN]  Error: {str(e)}")
        return "No detailed plan available"
