"""Streaming scene splitter and stitching regression checks."""

import sys
import shutil
from types import SimpleNamespace
from pathlib import Path

from config import OUTPUTS
from algorithms import streaming
from algorithms.course import course_plan_is_thin, upgrade_course_plan_data
from algorithms.lecture import lecture_plan_is_thin, upgrade_lecture_plan_data
from algorithms.media_tools import VideoValidationResult
from algorithms.shorts import short_plan_is_visually_thin, upgrade_short_plan_data
from algorithms.standard import standard_plan_is_thin, upgrade_standard_plan_data
from algorithms.streaming import _find_scene_video, split_plan_into_scenes, stitch_scenes


class _FakeLLMChunk:
    def __init__(self, text):
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=text))]


class _FakeLLMResponse:
    def __init__(self, text):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=text))]


def test_short_mode_truncation_preserves_final_question():
    plan = {
        "video_mode": "short",
        "min_scenes": 2,
        "max_scenes": 5,
        "segments": [
            {
                "id": f"scene_{i}",
                "narration": f"Content segment {i}",
                "visual_description": f"Visual {i}",
                "estimated_duration": 8,
                "type": "content",
            }
            for i in range(6)
        ]
        + [
            {
                "id": "final_question",
                "narration": "What changes if the starting value is different?",
                "visual_description": "Show the final question",
                "estimated_duration": 5,
                "type": "question",
            }
        ],
    }

    scenes = split_plan_into_scenes(plan, max_scenes=5)

    assert len(scenes) <= 5
    assert scenes[-1]["scene_id"] == "final_question"
    assert scenes[-1]["type"] == "question"
    print("[OK] streaming split - short mode keeps final question when truncating")


def test_beats_plan_uses_mode_scene_bounds():
    topics = ["parabola", "tangent", "slope", "area", "matrix", "eigenvector"]
    plan = {
        "video_mode": "standard",
        "min_scenes": 4,
        "max_scenes": 6,
        "beats": [
            {
                "description": f"Beat {i}: explain {topic}.",
                "animation": f"Animate {topic}",
                "duration": 5,
            }
            for i, topic in enumerate(topics)
        ],
    }

    scenes = split_plan_into_scenes(plan, max_scenes=6)

    assert len(scenes) >= 4
    assert len(scenes) <= 6
    assert all(scene.get("animation_steps") for scene in scenes)
    print("[OK] streaming split - beats plans pass through mode bounds")


def test_malformed_plan_items_fall_back_to_safe_scene():
    plan = {
        "video_mode": "standard",
        "min_scenes": 1,
        "max_scenes": 3,
        "segments": "not-a-list",
        "description": "Fallback concept",
        "plan": "Explain the fallback concept visually.",
    }

    scenes = split_plan_into_scenes(plan, max_scenes=3)

    assert len(scenes) == 1
    assert scenes[0]["scene_id"] == "scene_0"
    assert scenes[0]["description"] == "Fallback concept."
    print("[OK] streaming split - malformed plan fields fall back safely")


def test_malformed_numeric_plan_fields_use_safe_defaults():
    plan = {
        "video_mode": "standard",
        "min_scenes": "many",
        "max_scenes": "also-many",
        "segments": [
            {
                "id": "scene_0",
                "narration": "First sentence. Second sentence.",
                "estimated_duration": "soon",
            }
        ],
    }

    scenes = split_plan_into_scenes(plan, max_scenes=3)

    assert scenes
    assert all(isinstance(scene["duration_hint"], int) for scene in scenes)
    assert all(scene["duration_hint"] >= 1 for scene in scenes)
    print("[OK] streaming split - malformed numeric fields use defaults")


def test_plan_text_cleanup_drops_dangling_fragments():
    plan = {
        "video_mode": "short",
        "segments": [
            {
                "id": "scene_0",
                "narration": "That scale change has a name. The eigenvalue. If the.",
                "visual_description": "Show the vector stretch. When the.",
                "estimated_duration": 8,
            }
        ],
    }

    scenes = split_plan_into_scenes(plan, max_scenes=5)

    assert scenes[0]["description"] == "That scale change has a name. The eigenvalue."
    assert scenes[0]["narration"] == "That scale change has a name. The eigenvalue."
    assert scenes[0]["animation_steps"] == ["Show the vector stretch."]
    print("[OK] streaming split - dangling plan fragments are removed")


def test_plan_text_cleanup_drops_short_trailing_clause_fragments():
    plan = {
        "video_mode": "short",
        "segments": [
            {
                "id": "scene_0",
                "narration": "This curve looks calm. But move to the right, and.",
                "visual_description": "Now the pattern pops. At x equals one, the slope.",
                "estimated_duration": 8,
            },
            {
                "id": "scene_1",
                "narration": "Here is the tangent line. At this point, it tilts up.",
                "visual_description": "Keep the complete second sentence.",
                "estimated_duration": 8,
            },
        ],
    }

    scenes = split_plan_into_scenes(plan, max_scenes=5)

    assert scenes[0]["description"] == "This curve looks calm."
    assert scenes[0]["animation_steps"] == ["Now the pattern pops."]
    assert scenes[1]["description"] == "Here is the tangent line. At this point, it tilts up."
    print("[OK] streaming split - short trailing clause fragments are removed")


def test_dedupe_does_not_violate_min_scene_bound():
    plan = {
        "video_mode": "standard",
        "min_scenes": 3,
        "max_scenes": 3,
        "segments": [
            {
                "id": "scene_0",
                "narration": "Alpha setup. Alpha movement. Alpha conclusion.",
                "estimated_duration": 12,
            },
            {
                "id": "scene_1",
                "narration": "Alpha setup. Alpha movement. Alpha conclusion.",
                "estimated_duration": 12,
            },
        ],
    }

    scenes = split_plan_into_scenes(plan, max_scenes=3)

    assert len(scenes) == 3
    print("[OK] streaming split - dedupe preserves minimum scene bound")


def test_short_mode_chooses_high_contrast_template_for_proof_topics():
    template = streaming.choose_visual_template(
        "Explain the Fundamental Theorem of Arithmetic by factoring 60",
        {"domain": "math", "video_mode": "short", "aspect": "9:16"},
    )

    assert template == "dark-blueprint"
    print("[OK] streaming template - short proof topics use high contrast")


def test_lecture_mode_prefers_light_academic_template():
    template = streaming.choose_visual_template(
        "Make an academic lecture about eigenvalues and matrices",
        {"domain": "math", "video_mode": "lecture", "aspect": "16:9"},
    )

    assert template == "light-notebook"
    print("[OK] streaming template - lecture mode uses academic board styling")


def test_stream_generate_tries_next_provider_after_timeout(monkeypatch):
    calls = []
    fake_code = "from manim import *\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None, timeout=None):
            self.base_url = base_url
            self.timeout = timeout
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append((self.base_url, self.timeout, kwargs.get("stream")))
            if self.base_url == "zju":
                raise TimeoutError("Request timed out")
            return [_FakeLLMChunk(fake_code)] if kwargs.get("stream") else _FakeLLMResponse(fake_code)

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("STREAM_PROVIDER_USE_SUBPROCESS", "false")
    monkeypatch.setattr(streaming, "STREAM_PROVIDER", "auto")
    streaming._PROVIDER_COOLDOWNS.clear()
    for name, base_url in [("zjuapi", "zju"), ("wenwen", "wen"), ("openai", "openai")]:
        monkeypatch.setitem(streaming.STREAM_PROVIDERS[name], "api_key", "key")
        monkeypatch.setitem(streaming.STREAM_PROVIDERS[name], "base_url", base_url)
        monkeypatch.setitem(streaming.STREAM_PROVIDERS[name], "timeout", 7)

    context = streaming.NarrativeContext(prompt="demo", domain="math")
    generated = "".join(streaming.stream_generate("make code", context))

    assert "class GeneratedScene" in generated
    assert calls == [("zju", 10, True), ("wen", 10, True)]
    assert streaming._provider_attempt_order("auto")[0] == "wenwen"
    print("[OK] streaming providers - timeout advances to next provider")


def test_stream_generate_uses_non_streaming_directly_for_single_provider(monkeypatch):
    calls = []
    fake_code = "from manim import *\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None, timeout=None):
            self.base_url = base_url
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append((self.base_url, kwargs.get("stream")))
            if kwargs.get("stream"):
                raise RuntimeError("streaming unsupported")
            return _FakeLLMResponse(fake_code)

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("STREAM_PROVIDER_USE_SUBPROCESS", "false")
    monkeypatch.setattr(streaming, "STREAM_PROVIDER", "zjuapi")
    streaming._PROVIDER_COOLDOWNS.clear()
    monkeypatch.setitem(streaming.STREAM_PROVIDERS["zjuapi"], "api_key", "key")
    monkeypatch.setitem(streaming.STREAM_PROVIDERS["zjuapi"], "base_url", "zju")

    context = streaming.NarrativeContext(prompt="demo", domain="math")
    generated = "".join(streaming.stream_generate("make code", context))

    assert "class GeneratedScene" in generated
    assert calls == [("zju", False)]
    print("[OK] streaming providers - single provider uses direct non-streaming")


def test_sanitize_generated_code_removes_literal_text_prefixes():
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        title = Text('textPrime pieces')
        subtitle = Text("label: Same factors")
"""

    cleaned = streaming._sanitize_generated_code(code)

    assert "textPrime" not in cleaned
    assert "label: Same" not in cleaned
    assert "Text('Prime pieces')" in cleaned
    assert 'Text("Same factors")' in cleaned
    print("[OK] streaming sanitize - literal text prefixes removed")


def test_sanitize_generated_code_repairs_common_scene_contract_leaks():
    code = """Here is the code:
class GeneratedScene(Scene):
    def construct(self):
        group = VGroup(Text("A"), Text("B")).arrange(CENTER)
        self.play(FadeIn(group))
"""

    cleaned = streaming._sanitize_generated_code(code)

    assert cleaned.startswith("from manim import *")
    assert ".arrange(RIGHT)" in cleaned
    assert "Here is the code" not in cleaned
    print("[OK] streaming sanitize - scene contract leaks repaired")


def test_sanitize_generated_code_removes_unsupported_dash_array():
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        a = Circle().set_stroke(dash_array=[0.08, 0.08])
        b = Circle().set_stroke(color=BLUE, dash_array=[0.08, 0.08], width=2)
        c = Circle().set_stroke(dash_array=(0.08, 0.08), width=3)
"""

    cleaned = streaming._sanitize_generated_code(code)

    assert "dash_array" not in cleaned
    assert "set_stroke()" in cleaned
    assert "set_stroke(color=BLUE, width=2)" in cleaned
    assert "set_stroke(width=3)" in cleaned
    print("[OK] streaming sanitize - unsupported set_stroke dash arrays removed")


def test_sanitize_generated_code_removes_invalid_one_cell_grid_overlay():
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        label = VGroup(
            BackgroundRectangle(Text("A")),
            RoundedRectangle(),
            Text("A"),
        ).arrange_in_grid(rows=1, cols=1).move_to(ORIGIN)
"""

    cleaned = streaming._sanitize_generated_code(code)

    assert "arrange_in_grid(rows=1, cols=1)" not in cleaned
    assert ").move_to(ORIGIN)" in cleaned
    print("[OK] streaming sanitize - invalid one-cell overlay grids removed")


def test_sanitize_generated_code_injects_focus_helpers():
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        label = Text("A")
        self.play(FadeIn(label))
"""

    cleaned = streaming._sanitize_generated_code(code)

    assert "# NIMA focus helpers" in cleaned
    assert "def focus_transition" in cleaned
    assert "def fit_to_safe_frame" in cleaned
    compile(cleaned, "<focus_helpers>", "exec")
    print("[OK] streaming sanitize - focus helpers injected into scenes")


def test_lecture_font_size_floor_is_enforced():
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        tiny = Text("small proof note", font_size=18)
        ok = Text("readable", font_size=30)
        self.add(tiny, ok)
"""

    adjusted = streaming._enforce_minimum_font_size(code, 24)

    assert "font_size=18" not in adjusted
    assert "font_size=24" in adjusted
    assert "font_size=30" in adjusted
    print("[OK] streaming sanitize - lecture font floor is enforced")


def test_sanitize_generated_code_repairs_simple_blur_to_focus_depth():
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        old_layer = VGroup(Text("old"))
        self.play(Blur(old_layer))
"""

    cleaned = streaming._sanitize_generated_code(code)

    assert "Blur(" not in cleaned
    assert "old_layer.animate.set_opacity(0.22)" in cleaned
    assert streaming._reject_known_bad_patterns(cleaned) is None
    print("[OK] streaming sanitize - simple blur calls become opacity depth")


def test_focus_transition_is_treated_as_real_animation():
    from algorithms.code_digest import validate_manim_code

    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        old_layer = VGroup(Text("old"))
        self.add(old_layer)
        active = Text("new")
        focus_transition(self, old_layer, active, run_time=1.4)
        self.wait(0.2)
"""

    cleaned = streaming._sanitize_generated_code(code)
    ok, error = validate_manim_code(cleaned)

    assert ok, error
    assert abs(streaming._estimate_manim_code_duration(cleaned) - 1.6) < 0.001
    print("[OK] streaming validation - focus_transition counts as animation")


def test_injected_focus_helpers_do_not_mask_static_standard_scene():
    context = streaming.NarrativeContext.from_analysis(
        "Make a standard explainer",
        {"domain": "general", "video_mode": "standard", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "standard"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        title = Text("Chapter")
        a = Text("Point one")
        b = Text("Point two")
        c = Text("Point three")
        d = Text("Point four")
        self.play(Write(title))
        self.play(FadeIn(a))
        self.play(FadeIn(b))
        self.play(FadeIn(c))
        self.play(FadeIn(d))
        self.wait(20)
"""

    cleaned = streaming._sanitize_generated_code(code)
    error = streaming._reject_standard_engagement_code(
        cleaned,
        context,
        {"duration_hint": 30},
    )

    assert error
    assert "text-card" in error
    print("[OK] streaming validation - focus helpers do not mask static scenes")


def test_known_bad_patterns_reject_fragile_blur_filters():
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        old_layer = VGroup(Text("old"))
        self.play(Blur(old_layer))
"""

    error = streaming._reject_known_bad_patterns(code)

    assert error
    assert "Unsupported blur filter" in error
    assert "BackgroundRectangle" in error
    print("[OK] streaming validation - fragile blur filters are rejected")


def test_known_bad_patterns_reject_matrix_without_latex(monkeypatch):
    import algorithms.code_digest as code_digest

    monkeypatch.setattr(code_digest, "latex_toolchain_available", lambda: False)
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        matrix = Matrix([["a", "b"], ["c", "d"]])
        self.play(FadeIn(matrix))
"""

    error = streaming._reject_known_bad_patterns(code)

    assert error
    assert "Matrix(...)" in error
    assert "LaTeX is unavailable" in error
    print("[OK] streaming validation - Matrix is blocked without LaTeX")


def test_layout_hygiene_rejects_static_overlap_in_streaming_path():
    context = streaming.NarrativeContext.from_analysis(
        "Make a standard explainer",
        {"domain": "general", "video_mode": "standard", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "standard"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        first = Text("First idea").move_to(ORIGIN)
        second = Text("Second idea").move_to(ORIGIN)
        self.play(Write(first))
        self.play(Write(second))
        self.wait(2)
"""

    cleaned = streaming._sanitize_generated_code(code)
    error = streaming._reject_layout_hygiene_code(
        cleaned,
        context,
        {"duration_hint": 20, "type": "content"},
    )

    assert error
    assert "Static layout hygiene risk" in error
    assert "[OVERLAP]" in error
    print("[OK] streaming validation - static overlap detector gates streaming scenes")


def test_layout_hygiene_does_not_block_moderate_accumulation_only():
    context = streaming.NarrativeContext.from_analysis(
        "Make a lecture scene",
        {"domain": "math", "video_mode": "lecture", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "lecture"
    original_detector = streaming.detect_static_layout_risks
    try:
        streaming.detect_static_layout_risks = lambda _code: [
            "[ACCUMULATION] weighted create-load 17 but only ~2 cleaned up. Risk."
        ]
        error = streaming._reject_layout_hygiene_code(
            "from manim import *\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n",
            context,
            {"duration_hint": 35, "type": "content"},
        )
    finally:
        streaming.detect_static_layout_risks = original_detector

    assert error is None
    print("[OK] streaming validation - moderate accumulation remains render-validated")


def test_unbounded_long_text_is_rejected_before_edge_crowding():
    context = streaming.NarrativeContext.from_analysis(
        "Make an academic lecture",
        {"domain": "math", "video_mode": "lecture", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "lecture"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        prompt = Text(
            "What line would fail if one assumption behind eigenvalues and matrices were removed?",
            font_size=30,
            color=BLACK,
        ).move_to(ORIGIN)
        self.play(Write(prompt), run_time=1)
        self.wait(2)
"""

    error = streaming._reject_unbounded_long_text_code(
        streaming._sanitize_generated_code(code),
        context,
        {"duration_hint": 10, "type": "question"},
    )

    assert error
    assert "without a width guard" in error

    guarded = code.replace(
        ").move_to(ORIGIN)",
        ")\n        if prompt.width > 9.2:\n            prompt.scale_to_fit_width(9.2)\n        prompt.move_to(ORIGIN)",
    )
    assert (
        streaming._reject_unbounded_long_text_code(
            streaming._sanitize_generated_code(guarded),
            context,
            {"duration_hint": 10, "type": "question"},
        )
        is None
    )
    print("[OK] streaming validation - long text needs width guard")


def test_lecture_allows_moderate_text_line_without_width_guard():
    context = streaming.NarrativeContext.from_analysis(
        "Make an academic lecture",
        {"domain": "math", "video_mode": "lecture", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "lecture"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        closing_line = Text(
            "This theorem is a map from matrix action to invariant directions.",
            font_size=26,
            color=BLACK,
        ).move_to(ORIGIN)
        self.play(Write(closing_line), run_time=1)
        self.wait(2)
"""

    assert (
        streaming._reject_unbounded_long_text_code(
            streaming._sanitize_generated_code(code),
            context,
            {"duration_hint": 10, "type": "content"},
        )
        is None
    )
    print("[OK] streaming validation - moderate lecture text is render-validated")


def test_course_and_lecture_reject_excessive_static_padding_needs():
    course_context = streaming.NarrativeContext.from_analysis(
        "Make a course lesson",
        {"domain": "general", "video_mode": "course", "aspect": "16:9"},
    )
    course_context.domain_state["video_mode"] = "course"
    lecture_context = streaming.NarrativeContext.from_analysis(
        "Make an academic lecture",
        {"domain": "math", "video_mode": "lecture", "aspect": "16:9"},
    )
    lecture_context.domain_state["video_mode"] = "lecture"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        dot = Dot()
        circle = Circle()
        line = Line(LEFT, RIGHT)
        self.play(Create(dot), run_time=1)
        self.play(Transform(dot, circle), run_time=1)
        self.play(Create(line), run_time=1)
        self.wait(14)
"""

    course_error = streaming._reject_course_instructional_code(
        streaming._sanitize_generated_code(code),
        course_context,
        {"duration_hint": 30, "type": "content"},
    )
    lecture_error = streaming._reject_lecture_academic_code(
        streaming._sanitize_generated_code(code),
        lecture_context,
        {"duration_hint": 30, "type": "content"},
    )

    assert course_error and "Course content runtime is too short" in course_error
    assert lecture_error and "Lecture scene runtime is too short" in lecture_error
    print("[OK] streaming validation - long-form scenes cannot lean on static padding")


def test_render_validation_sanitizes_after_latex_downgrade():
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        label = MathTex(r"\\text{Prime pieces}", color=WHITE)
        self.play(FadeIn(label))
        self.wait(1)
"""
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        script_path = cmd[1]
        captured["code"] = open(script_path, encoding="utf-8").read()

        class Result:
            returncode = 1
            stderr = "intentional stop"
            stdout = ""

        return Result()

    import algorithms.code_digest as code_digest

    original_run = streaming.subprocess.run
    original_latex_available = code_digest.latex_toolchain_available
    try:
        streaming.subprocess.run = fake_run
        code_digest.latex_toolchain_available = lambda: False

        _, success, error = streaming._render_single_scene(
            code,
            "latex_text_prefix_probe",
            "latex_text_prefix_probe",
            0,
            timeout_seconds=1,
        )
    finally:
        streaming.subprocess.run = original_run
        code_digest.latex_toolchain_available = original_latex_available

    assert success is False
    assert error == "intentional stop"
    assert "textPrime" not in captured["code"]
    assert (
        "Text('Prime pieces'" in captured["code"]
        or 'Text("Prime pieces"' in captured["code"]
    )
    print("[OK] streaming render - sanitizer runs after LaTeX fallback")


def test_short_fallback_scene_is_runnable_plain_manim_code():
    context = streaming.NarrativeContext.from_analysis(
        "Explain Bayes' theorem using a medical test example with false positives.",
        {"domain": "math", "video_mode": "short", "aspect": "9:16"},
    )
    scene_plan = {"description": "Now compare positives and false alarms."}

    code = streaming._make_short_fallback_scene_code(scene_plan, context)

    assert code.startswith("from manim import *")
    assert "class GeneratedScene" in code
    assert "MathTex" not in code
    assert "textPrime" not in code
    compile(code, "<short_fallback>", "exec")
    print("[OK] streaming fallback - short fallback emits runnable Manim code")


def test_short_fallback_uses_topic_specific_lines():
    cases = [
        (
            "Explain Bayes' theorem using a medical test example with false positives.",
            "9 true positives",
            1,
        ),
        (
            "Explain the Fundamental Theorem of Arithmetic by factoring 60 and 84 into primes.",
            "84 = 2 x 2 x 3 x 7",
            0,
        ),
        (
            "Explain Dijkstra's algorithm on a weighted graph and show how shortest paths are updated.",
            "relax neighbors",
            1,
        ),
    ]

    for prompt, expected, scene_index in cases:
        context = streaming.NarrativeContext.from_analysis(
            prompt, {"domain": "math", "video_mode": "short", "aspect": "9:16"}
        )
        context.scene_index = scene_index
        code = streaming._make_short_fallback_scene_code(
            {"description": "fallback scene"}, context
        )
        assert expected in code

    print("[OK] streaming fallback - short fallback uses topic-specific lines")


def test_short_fallback_final_scene_keeps_question_contract():
    context = streaming.NarrativeContext.from_analysis(
        "Explain Dijkstra's algorithm on a weighted graph.",
        {"domain": "math", "video_mode": "short", "aspect": "9:16"},
    )
    context.domain_state["video_mode"] = "short"
    context.domain_state["total_scenes"] = 4
    context.scene_index = 3

    code = streaming._make_short_fallback_scene_code(
        {"description": "Ask the viewer to predict the next node."},
        context,
    )

    assert "Your turn" in code
    assert "which node is next?" in code
    assert "smallest distance wins" in code
    print("[OK] streaming fallback - final short scene keeps question contract")


def test_stitch_scenes_uses_requested_fps():
    clip_a = OUTPUTS / "stitch_fps_clip_a.mp4"
    clip_b = OUTPUTS / "stitch_fps_clip_b.mp4"
    output = OUTPUTS / "stitch_fps_output.mp4"
    clip_a.parent.mkdir(parents=True, exist_ok=True)
    clip_a.write_bytes(b"clip-a")
    clip_b.write_bytes(b"clip-b")
    commands = []

    original_run = streaming.subprocess.run
    try:
        def fake_run(cmd, **kwargs):
            commands.append(cmd)

            class FakeCompletedProcess:
                returncode = 0
                stderr = ""

            out_path = cmd[-1]
            with open(out_path, "wb") as handle:
                handle.write(b"stitched")
            return FakeCompletedProcess()

        streaming.subprocess.run = fake_run
        assert stitch_scenes([str(clip_a), str(clip_b)], str(output), fps=10) == str(
            output
        )
    finally:
        streaming.subprocess.run = original_run
        for path in (clip_a, clip_b, output):
            if path.exists():
                path.unlink()

    assert any("fps=10" in " ".join(command) for command in commands), commands
    assert any(
        command[index : index + 2] == ["-r", "10"]
        for command in commands
        for index in range(len(command) - 1)
    ), commands
    print("[OK] streaming stitch - requested fps is preserved")


def test_find_scene_video_ignores_legacy_global_outputs():
    original_outputs = streaming.OUTPUTS
    temp_outputs = OUTPUTS / "streaming_find_scene_test"
    if temp_outputs.exists():
        shutil.rmtree(temp_outputs)
    try:
        streaming.OUTPUTS = temp_outputs
        unrelated = temp_outputs / "videos" / "1080p60" / "GeneratedScene.mp4"
        unrelated.parent.mkdir(parents=True, exist_ok=True)
        unrelated.write_bytes(b"unrelated")

        assert _find_scene_video("video_lookup", 2) is None

        specific = (
            temp_outputs
            / "videos"
            / "video_lookup_scene2"
            / "480p30"
            / "video_lookup_scene2.mp4"
        )
        specific.parent.mkdir(parents=True, exist_ok=True)
        specific.write_bytes(b"specific")

        assert _find_scene_video("video_lookup", 2) == specific
    finally:
        streaming.OUTPUTS = original_outputs
        if temp_outputs.exists():
            shutil.rmtree(temp_outputs)

    print("[OK] streaming lookup - legacy global outputs ignored")


def test_streaming_scene_prompt_includes_rag_patterns():
    original_retrieve = streaming.retrieve_golden_example
    captured = {}

    def fake_retrieve(domain, topic, subtopics):
        captured["domain"] = domain
        captured["topic"] = topic
        captured["subtopics"] = list(subtopics)
        return "RAG_MARKER: use ValueTracker with always_redraw for continuity"

    try:
        streaming.retrieve_golden_example = fake_retrieve
        context = streaming.NarrativeContext.from_analysis(
            "Explain eigenvectors visually",
            {"domain": "math", "duration": 30},
        )
        context.domain_state["total_scenes"] = 1
        context.scene_index = 0
        prompt = streaming._build_scene_prompt(
            {
                "description": "Show a vector keeping its direction",
                "animation_steps": ["Draw basis vectors", "Apply matrix transform"],
                "objects": ["vector", "matrix"],
            },
            context,
            8,
        )
    finally:
        streaming.retrieve_golden_example = original_retrieve

    assert captured["domain"] == "math"
    assert captured["topic"] == "Show a vector keeping its direction"
    assert "vector" in captured["subtopics"]
    assert "RAG_MARKER" in prompt
    assert "RELEVANT PROVEN MANIM PATTERNS" in prompt
    print("[OK] streaming prompt - RAG patterns are injected into default path")


def test_short_scene_prompt_uses_phone_safe_rag_notes_not_wide_code():
    original_retrieve_patterns = streaming.retrieve_patterns

    def fake_retrieve_patterns(domain, topic, subtopics, limit=2):
        return [
            {
                "tags": ["graph", "wide", "axes"],
                "notes": "Wide axes technique that should be adapted",
                "pattern": "WIDE_PATTERN_SHOULD_NOT_APPEAR",
            }
        ]

    try:
        streaming.retrieve_patterns = fake_retrieve_patterns
        context = streaming.NarrativeContext.from_analysis(
            "Explain Bayes theorem as a short",
            {
                "domain": "math",
                "duration": 58,
                "video_mode": "short",
                "aspect": "9:16",
            },
        )
        context.domain_state["video_mode"] = "short"
        context.domain_state["aspect"] = "9:16"
        context.domain_state["total_scenes"] = 1
        context.scene_index = 0
        prompt = streaming._build_scene_prompt(
            {
                "description": "Show positive tests as a stacked phone card",
                "animation_steps": ["Show population", "Highlight true positives"],
                "objects": ["card", "labels"],
            },
            context,
            8,
        )
    finally:
        streaming.retrieve_patterns = original_retrieve_patterns

    assert "SHORT VERTICAL MANIM PATTERN" in prompt
    assert "Wide axes technique that should be adapted" in prompt
    assert "WIDE_PATTERN_SHOULD_NOT_APPEAR" not in prompt
    assert "Short-mode adaptation" in prompt
    print("[OK] streaming prompt - short RAG uses phone-safe notes")


def test_scene_frame_quality_failure_triggers_recovery():
    context = streaming.NarrativeContext.from_analysis(
        "Explain a scene", {"domain": "general", "duration": 30}
    )
    original_validate = streaming.validate_video_file
    original_analyze = streaming.analyze_video_frames
    original_recover = streaming._recover_render_failure
    calls = {"recover": 0}

    try:
        streaming.validate_video_file = lambda path: VideoValidationResult(
            ok=True, size_bytes=2048
        )

        def fake_analyze(path, max_frames=4):
            if "bad" in str(path):
                return {
                    "ok": False,
                    "score": 10,
                    "warnings": ["4/4 sampled frames look blank"],
                    "sampled_frames": 4,
                    "frames": [],
                }
            return {
                "ok": True,
                "score": 100,
                "warnings": [],
                "sampled_frames": 4,
                "frames": [],
            }

        def fake_recover(*args, **kwargs):
            calls["recover"] += 1
            return "good_scene.mp4", True, "", context

        streaming.analyze_video_frames = fake_analyze
        streaming._recover_render_failure = fake_recover

        path, ok, err, _ = streaming._accept_or_recover_scene_render(
            scene_num=0,
            scene_plan={"description": "bad scene"},
            context=context,
            video_path="bad_scene.mp4",
            success=True,
            error_msg="",
            filename="video_quality",
            job_id="job",
            render_resolution=None,
            quality_flag="-ql",
            fps=30,
            scene_timeout_seconds=None,
        )
    finally:
        streaming.validate_video_file = original_validate
        streaming.analyze_video_frames = original_analyze
        streaming._recover_render_failure = original_recover

    assert ok is True
    assert err == ""
    assert path == "good_scene.mp4"
    assert calls["recover"] == 1
    print("[OK] streaming render - severe scene frame quality triggers recovery")


def test_short_scene_non_severe_quality_warning_keeps_creative_scene():
    context = streaming.NarrativeContext.from_analysis(
        "Explain a short scene",
        {
            "domain": "general",
            "duration": 58,
            "video_mode": "short",
            "aspect": "9:16",
        },
    )
    context.domain_state["video_mode"] = "short"
    original_validate = streaming.validate_video_file
    original_analyze = streaming.analyze_video_frames
    original_recover = streaming._recover_render_failure
    original_fallback = streaming._render_short_fallback_scene
    calls = {"recover": 0, "fallback": 0}

    try:
        streaming.validate_video_file = lambda path: VideoValidationResult(
            ok=True, size_bytes=2048
        )
        streaming.analyze_video_frames = lambda path, max_frames=4: {
            "ok": True,
            "score": 80,
            "warnings": ["1/4 sampled frames have tiny content"],
            "sampled_frames": 4,
            "frames": [{"tiny_content": True}],
            "ocr": {"text_frames": 0, "summary": {}},
        }

        def fake_recover(*args, **kwargs):
            calls["recover"] += 1
            return None, False, "retry failed", context

        def fake_fallback(*args, **kwargs):
            calls["fallback"] += 1
            return "fallback_scene.mp4", True, "", context

        streaming._recover_render_failure = fake_recover
        streaming._render_short_fallback_scene = fake_fallback

        path, ok, err, _ = streaming._accept_or_recover_scene_render(
            scene_num=0,
            scene_plan={"description": "phone scene"},
            context=context,
            video_path="low_score_scene.mp4",
            success=True,
            error_msg="",
            filename="video_quality",
            job_id="job",
            render_resolution=(720, 1280),
            quality_flag="-ql",
            fps=10,
            scene_timeout_seconds=None,
        )
    finally:
        streaming.validate_video_file = original_validate
        streaming.analyze_video_frames = original_analyze
        streaming._recover_render_failure = original_recover
        streaming._render_short_fallback_scene = original_fallback

    assert ok is True
    assert err == ""
    assert path == "low_score_scene.mp4"
    assert calls == {"recover": 0, "fallback": 0}
    print("[OK] streaming render - non-severe short quality warning keeps creative scene")


def test_standard_scene_quality_warning_requests_recovery_once():
    context = streaming.NarrativeContext.from_analysis(
        "Explain a standard scene",
        {
            "domain": "general",
            "duration": 240,
            "video_mode": "standard",
            "aspect": "16:9",
        },
    )
    context.domain_state["video_mode"] = "standard"
    original_validate = streaming.validate_video_file
    original_analyze = streaming.analyze_video_frames
    original_recover = streaming._recover_render_failure
    calls = {"recover": 0}

    try:
        streaming.validate_video_file = lambda path: VideoValidationResult(
            ok=True, size_bytes=4096
        )
        def fake_analyze(path, max_frames=4):
            if path == "recovered_scene.mp4":
                return {
                    "ok": True,
                    "score": 84,
                    "warnings": [],
                    "sampled_frames": 4,
                    "frames": [
                        {"blank": False, "tiny_content": False, "cluttered": False}
                        for _ in range(4)
                    ],
                    "ocr": {"summary": {"max_overlap_ratio": 0.0}},
                }
            return {
                "ok": False,
                "score": 64,
                "warnings": [
                    "1/4 sampled frames have tiny content",
                    "2/4 sampled frames crowd frame edges",
                ],
                "sampled_frames": 4,
                "frames": [
                    {"blank": False, "tiny_content": True, "cluttered": False},
                    {"blank": False, "tiny_content": False, "cluttered": False},
                    {"blank": False, "tiny_content": False, "cluttered": False},
                    {"blank": False, "tiny_content": False, "cluttered": False},
                ],
                "ocr": {"summary": {"max_overlap_ratio": 0.31}},
            }

        streaming.analyze_video_frames = fake_analyze

        def fake_recover(*args, **kwargs):
            calls["recover"] += 1
            return "recovered_scene.mp4", True, "", context

        streaming._recover_render_failure = fake_recover

        path, ok, err, _ = streaming._accept_or_recover_scene_render(
            scene_num=0,
            scene_plan={"description": "standard scene"},
            context=context,
            video_path="warning_scene.mp4",
            success=True,
            error_msg="",
            filename="video_quality",
            job_id="job",
            render_resolution=None,
            quality_flag="-ql",
            fps=10,
            scene_timeout_seconds=None,
        )
    finally:
        streaming.validate_video_file = original_validate
        streaming.analyze_video_frames = original_analyze
        streaming._recover_render_failure = original_recover

    assert ok is True
    assert err == ""
    assert path == "recovered_scene.mp4"
    assert calls["recover"] == 1
    print("[OK] streaming render - standard quality warnings request recovery once")


def test_short_plan_upgrade_replaces_static_text_plan_with_motion_beats():
    class Profile:
        mode = "short"
        target_duration = 58

    plan = {
        "video_mode": "short",
        "segments": [
            {
                "id": "scene_0",
                "type": "content",
                "narration": "Here is the main idea.",
                "visual_description": "Show title text and a few bullet labels.",
                "estimated_duration": 12,
            },
            {
                "id": "scene_1",
                "type": "question",
                "narration": "What changes?",
                "visual_description": "Show the question text.",
                "estimated_duration": 8,
            },
        ],
    }

    upgraded = upgrade_short_plan_data(
        plan,
        "Make a viral short explaining Dijkstra on a weighted graph",
        {"topic": "dijkstra algorithm", "domain": "computer_science"},
        Profile(),
    )
    scenes = split_plan_into_scenes(upgraded, max_scenes=5)

    assert short_plan_is_visually_thin(plan) is True
    assert len(scenes) == 5
    assert upgraded["short_strategy"] == "replaced_thin_plan_with_social_beats"
    assert all(scene.get("required_motions") for scene in scenes)
    assert "weighted graph" in scenes[0]["visual_description"].lower()
    assert scenes[-1]["type"] == "question"
    print("[OK] streaming short plan - static text plans become motion beats")


def test_short_scene_prompt_contains_social_motion_contract():
    context = streaming.NarrativeContext.from_analysis(
        "Make a viral Dijkstra short",
        {
            "domain": "computer_science",
            "duration": 58,
            "video_mode": "short",
            "aspect": "9:16",
        },
    )
    context.domain_state["video_mode"] = "short"
    context.domain_state["aspect"] = "9:16"
    context.domain_state["total_scenes"] = 5
    prompt = streaming._build_scene_prompt(
        {
            "description": "Relax the graph.",
            "visual_description": "Move a token along edges and overwrite labels.",
            "required_motions": ["move token", "overwrite label", "pulse node"],
            "short_directives": ["No text cards."],
            "forbidden_visuals": ["static title card"],
            "objects": ["weighted graph", "distance badges"],
        },
        context,
        11,
    )

    assert "SHORT SOCIAL SCENE CONTRACT" in prompt
    assert "REQUIRED MOTIONS" in prompt
    assert "move token" in prompt
    assert "static title card" in prompt
    print("[OK] streaming prompt - short scenes carry motion contract")


def test_static_short_code_is_rejected_before_render():
    context = streaming.NarrativeContext.from_analysis(
        "Make a viral short",
        {"domain": "general", "video_mode": "short", "aspect": "9:16"},
    )
    context.domain_state["video_mode"] = "short"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        title = Text("Hook")
        a = Text("Point one")
        b = Text("Point two")
        self.play(Write(title))
        self.play(FadeIn(a))
        self.play(FadeIn(b))
        self.wait(2)
"""

    error = streaming._reject_static_short_code(code, context)

    assert error
    assert "text-card" in error
    print("[OK] streaming quality - static short code rejected pre-render")


def test_short_code_duration_estimator_reads_multiline_run_times():
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.play(
            FadeIn(Text("A")),
            run_time=0.4,
        )
        self.play(Indicate(Dot()), run_time=0.6)
        self.wait(1.2)
"""

    estimated = streaming._estimate_manim_code_duration(code)

    assert abs(estimated - 2.2) < 0.01, estimated
    print("[OK] streaming duration - estimator reads multiline run_time values")


def test_short_code_under_duration_is_rejected():
    context = streaming.NarrativeContext.from_analysis(
        "Make a viral short",
        {"domain": "general", "video_mode": "short", "aspect": "9:16"},
    )
    context.domain_state["video_mode"] = "short"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        dot = Dot()
        circle = Circle()
        line = Line(LEFT, RIGHT)
        self.play(Create(circle), run_time=0.5)
        self.play(MoveAlongPath(dot, line), run_time=0.8)
        self.play(Indicate(circle), run_time=0.5)
        self.wait(0.8)
"""

    error = streaming._reject_short_duration_code(
        code,
        context,
        {"duration_hint": 11},
    )

    assert error
    assert "too short" in error
    print("[OK] streaming duration - under-length short code is rejected")


def test_short_scene_duration_padding_uses_final_frame_clone():
    calls = {}
    original_probe = streaming.probe_media_duration_seconds
    original_run = streaming.subprocess.run
    original_validate = streaming.validate_video_file
    try:
        streaming.probe_media_duration_seconds = lambda path: 6.0

        def fake_run(cmd, **kwargs):
            calls["cmd"] = cmd
            Path(cmd[-1]).write_bytes(b"padded")

            class FakeCompletedProcess:
                returncode = 0
                stdout = ""
                stderr = ""

            return FakeCompletedProcess()

        streaming.subprocess.run = fake_run
        streaming.validate_video_file = lambda path, min_duration_seconds=0.25: VideoValidationResult(
            ok=True,
            size_bytes=2048,
            duration_seconds=11.0,
        )

        padded = streaming._pad_scene_to_min_duration(
            str(OUTPUTS / "short_duration_probe.mp4"),
            11,
            fps=10,
            scene_num=2,
        )
    finally:
        streaming.probe_media_duration_seconds = original_probe
        streaming.subprocess.run = original_run
        streaming.validate_video_file = original_validate
        path = OUTPUTS / "short_duration_probe_padded.mp4"
        if path.exists():
            path.unlink()

    assert padded.endswith("_padded.mp4")
    assert any("tpad=stop_mode=clone" in str(part) for part in calls["cmd"])
    assert "-an" in calls["cmd"]
    print("[OK] streaming duration - short scenes are padded to planned beat length")


def test_standard_plan_upgrade_replaces_thin_plan_with_youtube_chapters():
    class Profile:
        mode = "standard"
        target_duration = 240
        max_scenes = 12

    plan = {
        "video_mode": "standard",
        "target_duration": 240,
        "segments": [
            {
                "id": "scene_0",
                "type": "content",
                "narration": "Explain binary search.",
                "visual_description": "Show a title.",
                "estimated_duration": 20,
            },
            {
                "id": "scene_1",
                "type": "question",
                "narration": "What is the midpoint?",
                "visual_description": "Show the question text.",
                "estimated_duration": 10,
            },
        ],
    }

    upgraded = upgrade_standard_plan_data(
        plan,
        "Make a 4 minute standard YouTube explainer about binary search",
        {"topic": "binary search", "domain": "computer_science"},
        Profile(),
    )
    scenes = split_plan_into_scenes(upgraded, max_scenes=12)

    assert standard_plan_is_thin(plan) is True
    assert upgraded["standard_strategy"] == "replaced_thin_plan_with_youtube_chapters"
    assert len(scenes) == 8
    assert all(scene.get("type") == "content" for scene in scenes)
    assert all(scene.get("standard_directives") for scene in scenes)
    assert any("naive" in scene.get("title", "").lower() for scene in scenes)
    print("[OK] streaming standard plan - thin plans become YouTube chapters")


def test_standard_plan_upgrade_removes_stale_scene_shapes():
    class Profile:
        mode = "standard"
        target_duration = 240
        max_scenes = 12

    plan = {
        "video_mode": "Standard 2-5 min",
        "target_duration": 240,
        "scenes": [
            {
                "id": "stale_scene",
                "description": "A generic scene the splitter used to split into parts.",
                "animation": ["Show a title", "Explain the concept"],
                "duration": 12,
                "type": "content",
            }
        ],
    }

    upgraded = upgrade_standard_plan_data(
        plan,
        "Make a standard YouTube explainer about binary search",
        {"topic": "binary search", "domain": "computer_science"},
        Profile(),
    )
    scenes = split_plan_into_scenes(upgraded, max_scenes=12)

    assert "scenes" not in upgraded
    assert "beats" not in upgraded
    assert upgraded["video_mode"] == "standard"
    assert len(scenes) == 8
    assert scenes[0]["scene_id"] == "scene_0"
    assert scenes[0]["title"] == "Cold Open"
    print("[OK] streaming standard plan - stale scene shapes cannot bypass upgrade")


def test_standard_plan_upgrade_enforces_duration_floor_on_rich_plans():
    class Profile:
        mode = "standard"
        target_duration = 240
        max_scenes = 12

    plan = {
        "video_mode": "standard",
        "target_duration": 240,
        "segments": [
            {
                "id": f"scene_{idx}",
                "type": "content",
                "narration": f"Explain chapter {idx}.",
                "visual_description": "Animate boxes, transform the window, and reveal the comparison.",
                "estimated_duration": 10,
                "objects": ["boxes", "window", "pointer"],
                "required_motions": ["animate boxes", "transform window", "reveal comparison"],
            }
            for idx in range(8)
        ],
    }

    upgraded = upgrade_standard_plan_data(
        plan,
        "Make a 4 minute standard YouTube explainer about binary search",
        {"topic": "binary search", "domain": "computer_science"},
        Profile(),
    )
    scenes = split_plan_into_scenes(upgraded, max_scenes=12)

    assert upgraded["standard_strategy"] == "enriched_existing_plan_with_youtube_contract"
    assert min(scene["duration_hint"] for scene in scenes) >= 30
    print("[OK] streaming standard plan - rich plans keep standard duration floor")


def test_standard_plan_upgrade_replaces_generic_request_analysis_fallback():
    class Profile:
        mode = "standard"
        target_duration = 240
        max_scenes = 12

    generic_segments = [
        {
            "id": "scene_1",
            "title": "Hook / Opening",
            "narration": (
                "Let's begin with a simple picture of standard youtube-style "
                "explainer binary search moving. Think of one concrete situation "
                "so the main idea feels natural before any formal details."
            ),
            "visual_description": "Animate boxes, transform the window, and reveal a label.",
            "estimated_duration": 20,
            "type": "content",
        },
        {
            "id": "scene_2",
            "title": "standard",
            "narration": (
                "Now test standard with a quick what-if scenario. Notice what "
                "changes and what stays invariant in standard youtube-style "
                "explainer binary search moving."
            ),
            "visual_description": "Animate a pointer and transform a highlighted window.",
            "estimated_duration": 20,
            "type": "content",
        },
        {
            "id": "scene_3",
            "title": "youtube-style",
            "narration": (
                "Build intuition for youtube-style by connecting symbols to "
                "geometry. Then keep one practical rule you can reuse."
            ),
            "visual_description": "Animate boxes and reveal a rule.",
            "estimated_duration": 20,
            "type": "content",
        },
        {
            "id": "scene_4",
            "title": "explainer",
            "narration": "Let's zoom in on explainer with one concrete case.",
            "visual_description": "Move a marker and transform labels.",
            "estimated_duration": 20,
            "type": "content",
        },
        {
            "id": "scene_5",
            "title": "Takeaway",
            "narration": "Now connect the final relationship back to the main idea.",
            "visual_description": "Animate the final relationship.",
            "estimated_duration": 20,
            "type": "content",
        },
    ]
    plan = {
        "video_mode": "standard",
        "target_duration": 240,
        "segments": generic_segments,
    }

    upgraded = upgrade_standard_plan_data(
        plan,
        (
            "Make a 4 minute standard YouTube-style explainer for binary search "
            "using sorted boxes and a moving search window."
        ),
        {"topic": "standard youtube-style explainer binary search moving"},
        Profile(),
    )
    scenes = split_plan_into_scenes(upgraded, max_scenes=12)

    assert upgraded["standard_strategy"] == "replaced_thin_plan_with_youtube_chapters"
    assert scenes[0]["title"] == "Cold Open"
    assert "binary search" in scenes[0]["narration"].lower()
    assert "standard youtube-style explainer" not in scenes[0]["narration"].lower()
    print("[OK] streaming standard plan - generic fallback gets replaced")


def test_standard_scene_prompt_contains_youtube_contract_and_rag_reference():
    context = streaming.NarrativeContext.from_analysis(
        "Make a standard binary search explainer",
        {
            "domain": "computer_science",
            "duration": 240,
            "video_mode": "standard",
            "aspect": "16:9",
        },
    )
    context.domain_state["video_mode"] = "standard"
    context.domain_state["total_scenes"] = 8
    prompt = streaming._build_scene_prompt(
        {
            "description": "Show the naive scan failing.",
            "visual_description": "Move a pointer through sorted boxes, then reveal wasted work.",
            "required_motions": ["move pointer", "highlight rejected boxes"],
            "standard_directives": ["Keep the sorted array as the recurring anchor."],
            "forbidden_visuals": ["text-only chapter card"],
            "objects": ["sorted boxes", "midpoint pointer", "search window"],
            "retention_hook": True,
        },
        context,
        30,
    )

    assert "STANDARD YOUTUBE EXPLAINER CONTRACT" in prompt
    assert "STANDARD 16:9 MANIM PATTERN" in prompt
    assert "FOCUS LAYER PATTERN" in prompt
    assert "fit_to_safe_frame" in prompt
    assert "safe inner frame" in prompt
    assert "do not use literal blur filters" in prompt
    assert "Keep the sorted array as the recurring anchor." in prompt
    assert "text-only chapter card" in prompt
    print("[OK] streaming prompt - standard scenes carry YouTube contract")


def test_static_standard_code_is_rejected_before_render():
    context = streaming.NarrativeContext.from_analysis(
        "Make a standard explainer",
        {"domain": "general", "video_mode": "standard", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "standard"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        title = Text("Chapter")
        a = Text("Point one")
        b = Text("Point two")
        c = Text("Point three")
        d = Text("Point four")
        self.play(Write(title))
        self.play(FadeIn(a))
        self.play(FadeIn(b))
        self.play(FadeIn(c))
        self.play(FadeIn(d))
        self.wait(20)
"""

    error = streaming._reject_standard_engagement_code(
        code,
        context,
        {"duration_hint": 30},
    )

    assert error
    assert "text-card" in error
    print("[OK] streaming quality - static standard code rejected pre-render")


def test_standard_code_under_duration_or_full_fadeout_is_rejected():
    context = streaming.NarrativeContext.from_analysis(
        "Make a standard explainer",
        {"domain": "general", "video_mode": "standard", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "standard"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        boxes = VGroup(Rectangle(), Rectangle(), Rectangle())
        pointer = Dot()
        line = Line(LEFT, RIGHT)
        self.play(Create(boxes), run_time=1.0)
        self.play(MoveAlongPath(pointer, line), run_time=1.0)
        self.play(Indicate(boxes), run_time=1.0)
        self.play(FadeOut(*self.mobjects), run_time=0.5)
        self.wait(0.1)
"""

    error = streaming._reject_standard_engagement_code(
        code,
        context,
        {"duration_hint": 30},
    )

    assert error
    assert "too short" in error
    print("[OK] streaming duration - under-length standard code is rejected")


def test_standard_scenelet_duration_accepts_ten_to_thirty_second_range():
    context = streaming.NarrativeContext.from_analysis(
        "Make a standard explainer",
        {"domain": "general", "video_mode": "standard", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "standard"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        boxes = VGroup(Rectangle(), Rectangle(), Rectangle())
        pointer = Dot()
        line = Line(LEFT, RIGHT)
        self.play(Create(boxes), run_time=4.0)
        self.play(MoveAlongPath(pointer, line), run_time=5.0)
        self.play(Indicate(boxes), run_time=4.0)
        self.wait(5.5)
"""

    error = streaming._reject_standard_engagement_code(
        code,
        context,
        {"duration_hint": 28},
    )

    assert error is None
    print("[OK] streaming duration - standard accepts 10-30s scenelets")


def test_unanchored_always_redraw_text_is_rejected():
    bad_code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        tracker = ValueTracker(0)
        label = always_redraw(lambda: Text(f"value {tracker.get_value():.0f}"))
        group = VGroup(Rectangle(), label).arrange(RIGHT)
        self.add(group)
"""
    good_code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        tracker = ValueTracker(0)
        box = Rectangle()
        label = always_redraw(lambda: Text(f"value {tracker.get_value():.0f}").next_to(box, UP, buff=0.3))
        self.add(box, label)
"""

    assert streaming._reject_known_bad_patterns(bad_code)
    assert streaming._reject_known_bad_patterns(good_code) is None
    print("[OK] streaming quality - unanchored dynamic text is rejected")


def test_standard_deterministic_fallback_is_valid_manim_code():
    from algorithms.code_digest import validate_manim_code, validate_python_syntax

    variant_plans = [
        (0, {"title": "Binary search fallback 0", "duration_hint": 24}),
        (1, {"title": "Binary search fallback 1", "duration_hint": 24}),
        (2, {"title": "Binary search fallback 2", "duration_hint": 24}),
        (
            1,
            {
                "title": "Linear Search Scans the Array",
                "description": "The obvious method checks values one by one",
                "duration_hint": 24,
            },
        ),
        (
            2,
            {
                "title": "Binary Search Needs Order",
                "description": "The array must be sorted and in order",
                "duration_hint": 24,
            },
        ),
        (
            4,
            {
                "title": "Comparison Counting Payoff",
                "description": "The comparison count gap grows larger",
                "duration_hint": 24,
            },
        ),
        (
            5,
            {
                "title": "Takeaway and Best Use",
                "description": "End with the mental model and best use",
                "duration_hint": 24,
            },
        ),
    ]

    for scene_index, scene_plan in variant_plans:
        context = streaming.NarrativeContext.from_analysis(
            "Make a standard explainer about binary search",
            {"domain": "computer_science", "video_mode": "standard", "aspect": "16:9"},
        )
        context.domain_state["video_mode"] = "standard"
        context.scene_index = scene_index
        code = streaming._make_standard_fallback_scene_code(scene_plan, context)

        syntax_ok, syntax_err = validate_python_syntax(code)
        structure_ok, structure_err = validate_manim_code(code)

        assert syntax_ok, syntax_err
        assert structure_ok, structure_err
        assert streaming._reject_known_bad_patterns(code) is None
        assert streaming._reject_standard_engagement_code(
            code, context, {"duration_hint": 24}
        ) is None
    print("[OK] streaming fallback - standard deterministic variants are valid")


def test_standard_generation_timeout_uses_deterministic_fallback(monkeypatch):
    context = streaming.NarrativeContext.from_analysis(
        "Make a standard explainer about binary search",
        {"domain": "computer_science", "video_mode": "standard", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "standard"

    def fake_stream_generate(_prompt, _context):
        raise TimeoutError("openai generation exceeded 90s")

    monkeypatch.setattr(streaming, "stream_generate", fake_stream_generate)
    scene_plan = {"title": "Timeout fallback", "description": "Show binary search", "duration_hint": 24}
    code, updated = streaming.generate_scene(
        scene_plan,
        context,
        0,
        max_retries=2,
    )

    assert "class GeneratedScene" in code
    assert "One comparison deletes half the map" in code
    assert scene_plan["_generation_source"] == "deterministic_standard_fallback"
    assert "generation exceeded" in scene_plan["_generation_error"]
    assert updated.scene_history
    print("[OK] streaming fallback - standard timeout uses deterministic scene")


def test_standard_quality_recovery_keeps_usable_original_when_retry_fails(monkeypatch):
    context = streaming.NarrativeContext.from_analysis(
        "Make a standard explainer about binary search",
        {"domain": "computer_science", "video_mode": "standard", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "standard"
    context.domain_state["duration_padding_enabled"] = True
    scene_plan = {"title": "Usable scene", "duration_hint": 30}

    class ValidVideo:
        ok = True

    monkeypatch.setattr(
        streaming,
        "_validate_scene_video",
        lambda *args, **kwargs: (
            False,
            "scene needs mode-aware layout recovery: OCR overlap",
        ),
    )
    monkeypatch.setattr(streaming, "validate_video_file", lambda *args, **kwargs: ValidVideo())
    monkeypatch.setattr(
        streaming,
        "analyze_video_frames",
        lambda *args, **kwargs: {"ok": True, "score": 82, "warnings": []},
    )
    monkeypatch.setattr(
        streaming,
        "_recover_render_failure",
        lambda *args, **kwargs: (None, False, "retry got worse", context),
    )
    monkeypatch.setattr(
        streaming,
        "_pad_scene_to_min_duration",
        lambda path, *args, **kwargs: path + "_padded",
    )

    path, ok, err, _ = streaming._accept_or_recover_scene_render(
        scene_num=2,
        scene_plan=scene_plan,
        context=context,
        video_path="usable_original.mp4",
        success=True,
        error_msg="",
        filename="video_test",
        job_id="job",
        render_resolution=(1280, 720),
        quality_flag="-ql",
        fps=30,
        scene_timeout_seconds=120,
    )

    assert ok is True
    assert err == ""
    assert path == "usable_original.mp4_padded"
    assert "accepted original render" in scene_plan["_render_recovery_note"]
    print("[OK] streaming recovery - standard keeps usable original if retry fails")


def test_lecture_deterministic_fallback_is_valid_academic_manim_code():
    from algorithms.code_digest import validate_manim_code, validate_python_syntax

    plans = [
        {
            "title": "Lemma Proof Step 1",
            "scene_role": "proof",
            "lecture_section": "Section 3 - Proof Machinery",
            "duration_hint": 35,
        },
        {
            "title": "Worked Example Run",
            "scene_role": "example",
            "lecture_section": "Section 5 - Worked Example",
            "duration_hint": 35,
        },
        {
            "title": "Lecture Pause 1",
            "type": "question",
            "description": "Which assumption is doing the most work here?",
            "duration_hint": 10,
        },
    ]
    for scene_index, scene_plan in enumerate(plans):
        context = streaming.NarrativeContext.from_analysis(
            "Make an academic lecture about eigenvalues",
            {"domain": "math", "video_mode": "lecture", "aspect": "16:9"},
        )
        context.domain_state["video_mode"] = "lecture"
        context.scene_index = scene_index
        code = streaming._make_lecture_fallback_scene_code(scene_plan, context)

        syntax_ok, syntax_err = validate_python_syntax(code)
        structure_ok, structure_err = validate_manim_code(code)

        assert syntax_ok, syntax_err
        assert structure_ok, structure_err
        assert streaming._reject_unbounded_long_text_code(code, context, scene_plan) is None
        assert streaming._reject_lecture_academic_code(code, context, scene_plan) is None
    print("[OK] streaming fallback - lecture deterministic variants are valid")


def test_lecture_generation_timeout_uses_deterministic_fallback(monkeypatch):
    context = streaming.NarrativeContext.from_analysis(
        "Make an academic lecture about eigenvalues",
        {"domain": "math", "video_mode": "lecture", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "lecture"

    def fake_stream_generate(_prompt, _context):
        raise TimeoutError("openai generation exceeded 90s")

    monkeypatch.setattr(streaming, "stream_generate", fake_stream_generate)
    scene_plan = {
        "title": "Timeout lecture fallback",
        "scene_role": "proof",
        "lecture_section": "Section 3 - Proof Machinery",
        "duration_hint": 35,
    }
    code, updated = streaming.generate_scene(scene_plan, context, 0, max_retries=2)

    assert "class GeneratedScene" in code
    assert "assumption ledger" in code
    assert scene_plan["_generation_source"] == "deterministic_lecture_fallback"
    assert "generation exceeded" in scene_plan["_generation_error"]
    assert updated.scene_history
    print("[OK] streaming fallback - lecture timeout uses deterministic scene")


def test_course_deterministic_fallback_is_valid_instructional_manim_code():
    from algorithms.code_digest import validate_manim_code, validate_python_syntax

    plans = [
        {
            "title": "Definition In Action",
            "scene_role": "definition",
            "module": "Module 2 - Core Concept",
            "duration_hint": 35,
        },
        {
            "title": "Orientation Map",
            "scene_role": "map",
            "module": "Module 1 - Orientation",
            "duration_hint": 35,
        },
        {
            "title": "Invariant Stress Test",
            "scene_role": "invariant-test",
            "module": "Module 3 - Mechanism",
            "duration_hint": 35,
        },
        {
            "title": "Mistake Clinic",
            "scene_role": "mistake",
            "module": "Module 4 - Mistakes",
            "duration_hint": 35,
        },
        {
            "title": "Worked Example Run",
            "scene_role": "example",
            "module": "Module 3 - Guided Practice",
            "duration_hint": 35,
        },
        {
            "title": "Checkpoint 1",
            "type": "question",
            "description": "Which path matches the idea we just built?",
            "duration_hint": 10,
        },
    ]
    for scene_index, scene_plan in enumerate(plans):
        context = streaming.NarrativeContext.from_analysis(
            "Create a course lesson about binary search",
            {"domain": "computer_science", "video_mode": "course", "aspect": "16:9"},
        )
        context.domain_state["video_mode"] = "course"
        context.scene_index = scene_index
        code = streaming._make_course_fallback_scene_code(scene_plan, context)

        syntax_ok, syntax_err = validate_python_syntax(code)
        structure_ok, structure_err = validate_manim_code(code)

        assert syntax_ok, syntax_err
        assert structure_ok, structure_err
        assert streaming._reject_unbounded_long_text_code(code, context, scene_plan) is None
        assert streaming._reject_course_instructional_code(code, context, scene_plan) is None
    print("[OK] streaming fallback - course deterministic variants are valid")


def test_course_generation_timeout_uses_deterministic_fallback(monkeypatch):
    context = streaming.NarrativeContext.from_analysis(
        "Create a course lesson about binary search",
        {"domain": "computer_science", "video_mode": "course", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "course"

    def fake_stream_generate(_prompt, _context):
        raise TimeoutError("openai generation exceeded 90s")

    monkeypatch.setattr(streaming, "stream_generate", fake_stream_generate)
    scene_plan = {
        "title": "Timeout course fallback",
        "scene_role": "definition",
        "module": "Module 2 - Core Concept",
        "duration_hint": 35,
    }
    code, updated = streaming.generate_scene(scene_plan, context, 0, max_retries=2)

    assert "class GeneratedScene" in code
    assert "attach a name, then test it" in code
    assert scene_plan["_generation_source"] == "deterministic_course_fallback"
    assert "generation exceeded" in scene_plan["_generation_error"]
    assert updated.scene_history
    print("[OK] streaming fallback - course timeout uses deterministic scene")


def test_course_plan_upgrade_replaces_thin_plan_with_modular_lesson():
    class Profile:
        mode = "course"
        target_duration = 900
        min_scenes = 25
        max_scenes = 40
        questions = {"pause_seconds": 10, "min_questions": 8, "max_questions": 14}

    plan = {
        "video_mode": "course",
        "target_duration": 900,
        "segments": [
            {
                "id": "scene_0",
                "type": "content",
                "narration": "Introduce binary search.",
                "visual_description": "Show a title.",
                "estimated_duration": 20,
            },
            {
                "id": "scene_1",
                "type": "question",
                "narration": "What is binary search?",
                "visual_description": "Show a question.",
                "estimated_duration": 10,
            },
        ],
    }

    upgraded = upgrade_course_plan_data(
        plan,
        "Make a course lesson about binary search using sorted boxes.",
        {"topic": "binary search", "domain": "computer_science"},
        Profile(),
    )
    scenes = split_plan_into_scenes(upgraded, max_scenes=40)
    question_count = sum(1 for scene in scenes if scene.get("type") == "question")
    modules = {scene.get("module") for scene in scenes if scene.get("module")}

    assert course_plan_is_thin(plan) is True
    assert upgraded["course_strategy"] == "replaced_thin_plan_with_course_lesson"
    assert len(scenes) == 40
    assert question_count == 8
    assert len(modules) >= 5
    assert all(scene.get("course_directives") for scene in scenes)
    assert max(scene["duration_hint"] for scene in scenes if scene.get("type") != "question") <= 30
    assert scenes[0]["title"] == "Orientation Map"
    print("[OK] streaming course plan - thin plans become modular lessons")


def test_course_plan_upgrade_removes_stale_scene_shapes():
    class Profile:
        mode = "course"
        target_duration = 900
        min_scenes = 25
        max_scenes = 40
        questions = {"pause_seconds": 10, "min_questions": 8, "max_questions": 14}

    plan = {
        "video_mode": "Course lesson",
        "target_duration": 900,
        "scenes": [
            {
                "id": "stale_scene",
                "description": "A generic scene that used to bypass course planning.",
                "animation": ["Show a title", "Explain the concept"],
                "duration": 12,
                "type": "content",
            }
        ],
    }

    upgraded = upgrade_course_plan_data(
        plan,
        "Make a course lesson about binary search",
        {"topic": "binary search", "domain": "computer_science"},
        Profile(),
    )
    scenes = split_plan_into_scenes(upgraded, max_scenes=40)

    assert "scenes" not in upgraded
    assert "beats" not in upgraded
    assert upgraded["video_mode"] == "course"
    assert len(scenes) == 40
    assert scenes[0]["scene_id"] == "scene_0"
    assert scenes[0]["module"].startswith("Module 1")
    print("[OK] streaming course plan - stale scene shapes cannot bypass upgrade")


def test_course_scene_prompt_contains_lesson_contract_and_rag_reference():
    context = streaming.NarrativeContext.from_analysis(
        "Make a course lesson about binary search",
        {
            "domain": "computer_science",
            "duration": 900,
            "video_mode": "course",
            "aspect": "16:9",
        },
    )
    context.domain_state["video_mode"] = "course"
    context.domain_state["total_scenes"] = 40
    prompt = streaming._build_scene_prompt(
        {
            "description": "Explain the invariant.",
            "visual_description": "Pin an invariant strip while the search window moves.",
            "required_motions": ["pin invariant", "move search window"],
            "course_directives": ["Keep the progress rail visible."],
            "forbidden_visuals": ["paragraph wall of text"],
            "objects": ["sorted boxes", "search window", "invariant strip"],
            "module": "Module 3 - Mechanism",
            "learning_objective": "track the invariant",
        },
        context,
        36,
    )

    assert "COURSE CONTENT SCENE CONTRACT" in prompt
    assert "COURSE 16:9 MANIM PATTERN" in prompt
    assert "FOCUS LAYER PATTERN" in prompt
    assert "BackgroundRectangle/focus plate" in prompt
    assert "fit_to_safe_frame" in prompt
    assert "x=-5.7..5.7" in prompt
    assert "Keep the progress rail visible." in prompt
    assert "paragraph wall of text" in prompt
    assert "track the invariant" in prompt
    print("[OK] streaming prompt - course scenes carry lesson contract")


def test_course_checkpoint_prompt_uses_pause_contract():
    context = streaming.NarrativeContext.from_analysis(
        "Make a course lesson",
        {"domain": "general", "video_mode": "course", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "course"
    prompt = streaming._build_scene_prompt(
        {
            "description": "Checkpoint question.",
            "type": "question",
            "narration": "Checkpoint. What changes?",
            "duration_hint": 10,
            "checkpoint_id": "checkpoint_1",
            "course_directives": ["Show one question prompt only."],
        },
        context,
        10,
    )

    assert "COURSE CHECKPOINT CONTRACT" in prompt
    assert "exactly one question prompt" in prompt
    assert "Show one question prompt only." in prompt
    print("[OK] streaming prompt - course checkpoints use pause contract")


def test_static_course_content_code_is_rejected_before_render():
    context = streaming.NarrativeContext.from_analysis(
        "Make a course lesson",
        {"domain": "general", "video_mode": "course", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "course"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        title = Text("Module")
        a = Text("Definition one")
        b = Text("Definition two")
        c = Text("Definition three")
        d = Text("Definition four")
        e = Text("Definition five")
        self.play(Write(title))
        self.play(FadeIn(a))
        self.play(FadeIn(b))
        self.play(FadeIn(c))
        self.play(FadeIn(d))
        self.play(FadeIn(e))
        self.wait(20)
"""

    error = streaming._reject_course_instructional_code(
        code,
        context,
        {"duration_hint": 34, "type": "content"},
    )

    assert error
    assert "text wall" in error
    print("[OK] streaming quality - static course content is rejected pre-render")


def test_course_checkpoint_short_runtime_is_allowed_for_padding():
    context = streaming.NarrativeContext.from_analysis(
        "Make a course lesson",
        {"domain": "general", "video_mode": "course", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "course"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        prompt = Text("What changes next?")
        left = Rectangle()
        right = Rectangle()
        self.play(FadeIn(prompt), FadeIn(left), FadeIn(right), run_time=1.0)
        self.wait(1)
"""

    error = streaming._reject_course_instructional_code(
        code,
        context,
        {"duration_hint": 10, "type": "question"},
    )

    assert error is None
    print("[OK] streaming duration - course checkpoints can rely on pause padding")


def test_lecture_plan_upgrade_replaces_thin_plan_with_academic_scenelets():
    class Profile:
        mode = "lecture"
        target_duration = 900
        duration_range = (900, 900)
        min_scenes = 15
        max_scenes = 30
        questions = {"pause_seconds": 10}

    plan = {
        "video_mode": "lecture",
        "target_duration": 900,
        "segments": [
            {
                "id": "scene_0",
                "type": "content",
                "narration": "Explain eigenvalues.",
                "visual_description": "Show a title.",
                "estimated_duration": 60,
            }
        ],
    }

    upgraded = upgrade_lecture_plan_data(
        plan,
        "Make an academic lecture about eigenvalues using matrices and proofs.",
        {"topic": "eigenvalues", "domain": "math"},
        Profile(),
    )
    scenes = split_plan_into_scenes(upgraded, max_scenes=30)

    assert lecture_plan_is_thin(plan) is True
    assert upgraded["lecture_strategy"] == "replaced_thin_plan_with_academic_lecture"
    assert len(scenes) == 30
    assert sum(1 for scene in scenes if scene.get("type") == "question") == 6
    assert all(
        scene.get("lecture_directives")
        for scene in scenes
        if scene.get("type") != "question"
    )
    print("[OK] streaming lecture plan - thin plans become academic scenelets")


def test_lecture_scene_prompt_contains_academic_contract_and_rag_reference():
    context = streaming.NarrativeContext.from_analysis(
        "Make an academic lecture about eigenvalues",
        {
            "domain": "math",
            "duration": 900,
            "video_mode": "lecture",
            "aspect": "16:9",
        },
    )
    context.domain_state["video_mode"] = "lecture"
    context.domain_state["total_scenes"] = 30
    prompt = streaming._build_scene_prompt(
        {
            "description": "Prove the first lemma.",
            "visual_description": "Show an equation ladder and proof map.",
            "required_motions": ["transform equation line", "route proof map"],
            "lecture_directives": ["Use an assumption ledger."],
            "forbidden_visuals": ["full paragraph proof wall"],
            "objects": ["equation ladder", "proof map", "assumption ledger"],
            "lecture_section": "Section 3 - Proof Machinery",
            "learning_objective": "follow the lemma proof",
        },
        context,
        36,
    )

    assert "LECTURE CONTENT SCENE CONTRACT" in prompt
    assert "LECTURE 16:9 MANIM PATTERN" in prompt
    assert "FOCUS LAYER PATTERN" in prompt
    assert "focus_transition" in prompt
    assert "font_size >= 24" in prompt
    assert "width 10.8 and height 5.3" in prompt
    assert "Use an assumption ledger." in prompt
    assert "full paragraph proof wall" in prompt
    print("[OK] streaming prompt - lecture scenes carry academic contract")


def test_static_lecture_code_is_rejected_before_render():
    context = streaming.NarrativeContext.from_analysis(
        "Make an academic lecture",
        {"domain": "math", "video_mode": "lecture", "aspect": "16:9"},
    )
    context.domain_state["video_mode"] = "lecture"
    code = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        title = Text("Theorem")
        a = Text("Assumption one")
        b = Text("Assumption two")
        c = Text("Proof paragraph")
        d = Text("More proof paragraph")
        e = Text("Another proof paragraph")
        f = Text("Conclusion paragraph")
        self.play(Write(title))
        self.play(FadeIn(a))
        self.play(FadeIn(b))
        self.play(FadeIn(c))
        self.play(FadeIn(d))
        self.play(FadeIn(e))
        self.play(FadeIn(f))
        self.wait(30)
"""

    error = streaming._reject_lecture_academic_code(
        streaming._sanitize_generated_code(code),
        context,
        {"duration_hint": 36},
    )

    assert error
    assert "proof text wall" in error
    print("[OK] streaming quality - static lecture proof walls rejected")


if __name__ == "__main__":
    test_short_mode_truncation_preserves_final_question()
    test_beats_plan_uses_mode_scene_bounds()
    test_malformed_plan_items_fall_back_to_safe_scene()
    test_malformed_numeric_plan_fields_use_safe_defaults()
    test_plan_text_cleanup_drops_dangling_fragments()
    test_plan_text_cleanup_drops_short_trailing_clause_fragments()
    test_dedupe_does_not_violate_min_scene_bound()
    test_short_mode_chooses_high_contrast_template_for_proof_topics()
    test_lecture_mode_prefers_light_academic_template()
    test_sanitize_generated_code_removes_literal_text_prefixes()
    test_sanitize_generated_code_repairs_common_scene_contract_leaks()
    test_sanitize_generated_code_removes_unsupported_dash_array()
    test_sanitize_generated_code_removes_invalid_one_cell_grid_overlay()
    test_sanitize_generated_code_injects_focus_helpers()
    test_lecture_font_size_floor_is_enforced()
    test_sanitize_generated_code_repairs_simple_blur_to_focus_depth()
    test_focus_transition_is_treated_as_real_animation()
    test_injected_focus_helpers_do_not_mask_static_standard_scene()
    test_known_bad_patterns_reject_fragile_blur_filters()
    test_render_validation_sanitizes_after_latex_downgrade()
    test_short_fallback_scene_is_runnable_plain_manim_code()
    test_short_fallback_uses_topic_specific_lines()
    test_short_fallback_final_scene_keeps_question_contract()
    test_stitch_scenes_uses_requested_fps()
    test_find_scene_video_ignores_legacy_global_outputs()
    test_streaming_scene_prompt_includes_rag_patterns()
    test_short_scene_prompt_uses_phone_safe_rag_notes_not_wide_code()
    test_scene_frame_quality_failure_triggers_recovery()
    test_short_scene_non_severe_quality_warning_keeps_creative_scene()
    test_standard_scene_quality_warning_does_not_kill_rendered_scene()
    test_short_plan_upgrade_replaces_static_text_plan_with_motion_beats()
    test_short_scene_prompt_contains_social_motion_contract()
    test_static_short_code_is_rejected_before_render()
    test_short_code_duration_estimator_reads_multiline_run_times()
    test_short_code_under_duration_is_rejected()
    test_short_scene_duration_padding_uses_final_frame_clone()
    test_standard_plan_upgrade_replaces_thin_plan_with_youtube_chapters()
    test_standard_plan_upgrade_removes_stale_scene_shapes()
    test_standard_plan_upgrade_enforces_duration_floor_on_rich_plans()
    test_standard_plan_upgrade_replaces_generic_request_analysis_fallback()
    test_standard_scene_prompt_contains_youtube_contract_and_rag_reference()
    test_static_standard_code_is_rejected_before_render()
    test_standard_code_under_duration_or_full_fadeout_is_rejected()
    test_course_plan_upgrade_replaces_thin_plan_with_modular_lesson()
    test_course_plan_upgrade_removes_stale_scene_shapes()
    test_course_scene_prompt_contains_lesson_contract_and_rag_reference()
    test_course_checkpoint_prompt_uses_pause_contract()
    test_static_course_content_code_is_rejected_before_render()
    test_course_checkpoint_short_runtime_is_allowed_for_padding()
    test_lecture_plan_upgrade_replaces_thin_plan_with_academic_scenelets()
    test_lecture_scene_prompt_contains_academic_contract_and_rag_reference()
    test_static_lecture_code_is_rejected_before_render()
    print("\nALL STREAMING SPLIT CHECKS PASSED")
