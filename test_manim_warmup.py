"""Manim warmup infrastructure checks."""

from types import SimpleNamespace

from algorithms.manim_warmup import prewarm_manim


def test_warmup_skips_in_draft_mode():
    calls = []

    prewarm_manim(
        draft_pipeline=True,
        warmup_planes=True,
        manim_command=lambda: ["manim"],
        run_command=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert calls == []
    print("[OK] warmup — draft mode skips Manim process")


def test_warmup_runs_scene_and_plane_commands():
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    prewarm_manim(
        draft_pipeline=False,
        warmup_planes=True,
        manim_command=lambda: ["manim"],
        run_command=fake_run,
    )

    assert len(calls) == 2
    assert calls[0][0][0] == "manim"
    assert calls[0][0][2] == "WarmupScene"
    assert calls[1][0][2] == "PlaneWarmup"
    print("[OK] warmup — schedules scene and plane preloads")


if __name__ == "__main__":
    test_warmup_skips_in_draft_mode()
    test_warmup_runs_scene_and_plane_commands()
    print("\nALL WARMUP CHECKS PASSED")
