"""Deterministic generation-service smoke without LLM calls."""

import os
import json

os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["USE_DATABASE"] = "false"

import algorithms.generation_service as generation_service
from algorithms.generation_service import (
    GenerationServiceDeps,
    generate_and_validate_code_job,
)


CODE = """
from manim import *


class GeneratedScene(Scene):
    def construct(self):
        self.play(Create(Circle()))
        self.wait(0.1)
"""


def main() -> int:
    status = {}
    messages = []

    def update_status(_job_id: str, **updates):
        status.update(updates)
        if "message" in updates:
            messages.append(updates["message"])
        return dict(status)

    generation_service.expand_short_prompt = lambda prompt: prompt
    generation_service.analyze_request_type = lambda prompt: {
        "domain": "general",
        "duration": 120,
        "topic": "stub",
    }
    generation_service.create_animation_plan = lambda prompt, analysis: "stub plan"
    generation_service.generate_manim_code = (
        lambda prompt, analysis, plan, attempt, db=None, segment_durations=None: CODE
    )
    generation_service.check_code_quality = lambda code: (True, [])
    generation_service.validate_latex_strings = lambda code: (True, [])
    generation_service.validate_names_and_imports = lambda code: (True, [])
    generation_service.validate_python_syntax = lambda code: (True, None)
    generation_service.validate_manim_code = lambda code: (True, None)
    generation_service.detect_overlaps = lambda code: []
    generation_service.ensure_scene_class = lambda code: code

    (
        code,
        attempts,
        request_id,
        attempt_id,
        audio_segments,
        segment_order,
        is_fast,
        analysis,
    ) = generate_and_validate_code_job(
        "Draw a circle",
        "gensvc001",
        max_attempts=1,
        voiceover=False,
        deps=GenerationServiceDeps(update_status=update_status),
    )

    if "GeneratedScene" not in code:
        print("ERROR: generated code missing scene class")
        return 1
    if not attempts or attempts[0].get("stage") != "analysis":
        print(f"ERROR: attempts log missing analysis stage: {attempts}")
        return 1
    if request_id is not None or attempt_id is not None:
        print("ERROR: service should not create DB IDs without DB dependency")
        return 1
    if audio_segments or segment_order:
        print("ERROR: silent generation should not produce audio segments")
        return 1
    if analysis.get("video_mode") != "standard":
        print(f"ERROR: expected normalized standard mode, got {analysis}")
        return 1
    if "Validating syntax..." not in messages:
        print(f"ERROR: status callback was not used as expected: {messages}")
        return 1
    print("[OK] generation service smoke")

    generation_service.create_narrated_plan = lambda prompt, analysis: json.dumps(
        {
            "segments": [
                {
                    "id": "scene_0",
                    "narration": "Narrate this",
                    "estimated_duration": 1,
                }
            ]
        }
    )
    generation_service.generate_voiceover = lambda segments, output_dir, voice=None: {
        "scene_0": {
            "path": None,
            "duration": 5.0,
            "error": "TTS provider unavailable",
        }
    }
    try:
        generate_and_validate_code_job(
            "Draw a narrated circle",
            "gensvc002",
            max_attempts=1,
            voiceover=True,
            deps=GenerationServiceDeps(update_status=update_status),
        )
        print("ERROR: voiceover generation without audio should fail")
        return 1
    except RuntimeError as exc:
        if "no narration audio was generated" not in str(exc):
            print(f"ERROR: unexpected voiceover failure: {exc}")
            return 1
    print("[OK] generation service - requested voiceover requires audio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
