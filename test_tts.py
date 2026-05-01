"""TTS pipeline checks that avoid network calls."""

from __future__ import annotations

import tempfile
from pathlib import Path

import algorithms.tts as tts


def test_generate_voiceover_uses_default_edge_voice_when_voice_missing() -> None:
    original_generate_segment_audio = tts.generate_segment_audio
    calls = []
    try:
        def fake_generate_segment_audio(text, output_path, voice=None):
            calls.append({"text": text, "output_path": output_path, "voice": voice})
            Path(output_path).write_bytes(b"fake-audio")
            return 1.25

        tts.generate_segment_audio = fake_generate_segment_audio
        with tempfile.TemporaryDirectory() as tmp:
            result = tts.generate_voiceover(
                [{"id": "scene_0", "narration": "Narrate this"}],
                tmp,
                voice=None,
            )
    finally:
        tts.generate_segment_audio = original_generate_segment_audio

    assert result["scene_0"]["duration"] == 1.25, result
    assert calls and calls[0]["voice"] == tts.EDGE_TTS_VOICE, calls
    assert Path(calls[0]["output_path"]).name == "scene_0.mp3", calls
    print("[OK] TTS - missing voice falls back to configured Edge voice")


if __name__ == "__main__":
    test_generate_voiceover_uses_default_edge_voice_when_voice_missing()
    print("\nALL TTS CHECKS PASSED")
