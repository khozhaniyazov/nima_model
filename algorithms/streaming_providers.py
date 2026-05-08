"""LLM streaming-provider layer for ``algorithms.streaming`` (#11).

Extracted from ``algorithms/streaming.py``. Owns everything that knows
about external LLM providers: per-provider credentials, cooldown
bookkeeping, provider selection, low-level ``chat.completions.create``
invocation (streaming + non-streaming, in-process + subprocess
variants), and the system-message builder.

Module-load contract:

- This module is a leaf. It MUST NOT import from ``algorithms.streaming``
  at module-load time (streaming imports this module during its own
  load). ``_build_stream_system_msg`` reads
  ``algorithms.code_digest.latex_toolchain_available`` lazily inside its
  body for the same reason.
- ``NarrativeContext`` appears only in string-form type hints, guarded
  by ``from __future__ import annotations`` + ``TYPE_CHECKING``.
- Module-level mutable state (``_PROVIDER_COOLDOWNS``, ``STREAM_PROVIDERS``,
  ``STREAM_PROVIDER``) is intentionally module-public: tests reach it as
  ``streaming.<name>`` via the re-export from ``algorithms.streaming``.

Tests that monkeypatch any of these names via ``streaming.<name>`` keep
working because ``algorithms.streaming`` re-imports every symbol defined
here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, TYPE_CHECKING

from config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_TIMEOUT,
    ZJUBAPI_BASE_URL,
    ZJUBAPI_API_KEY,
    ZJUBAPI_MODEL,
    ZJUBAPI_TIMEOUT,
    WENWEN_BASE_URL,
    WENWEN_API_KEY,
    WENWEN_MODEL,
    WENWEN_TIMEOUT,
    GENERATION_MODEL,
    STREAM_PROVIDER as CONFIG_STREAM_PROVIDER,
    STREAM_PROVIDER_FAILURE_COOLDOWN,
    STREAM_PROVIDER_TOTAL_TIMEOUT,
    STREAM_PROVIDER_USE_SUBPROCESS,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from algorithms.streaming import NarrativeContext


# ─── Provider configuration ─────────────────────────────────────────────────
PROVIDER_PRIORITY = ("zjuapi", "wenwen", "openai")
PROVIDER_FAILURE_COOLDOWN_SECONDS = STREAM_PROVIDER_FAILURE_COOLDOWN
PROVIDER_TOTAL_TIMEOUT_SECONDS = STREAM_PROVIDER_TOTAL_TIMEOUT
_PROVIDER_COOLDOWNS: Dict[str, float] = {}

STREAM_PROVIDERS = {
    "zjuapi": {
        "base_url": ZJUBAPI_BASE_URL,
        "api_key": ZJUBAPI_API_KEY,
        "model": ZJUBAPI_MODEL,
        "timeout": ZJUBAPI_TIMEOUT,
    },
    "wenwen": {
        "base_url": WENWEN_BASE_URL,
        "api_key": WENWEN_API_KEY,
        "model": WENWEN_MODEL,
        "timeout": WENWEN_TIMEOUT,
    },
    "openai": {
        "base_url": OPENAI_BASE_URL,
        "api_key": OPENAI_API_KEY,
        "model": GENERATION_MODEL,
        "timeout": OPENAI_TIMEOUT,
    },
}

# Active provider (auto-select based on availability)
STREAM_PROVIDER = CONFIG_STREAM_PROVIDER

# Scene generation settings


# ─── Provider routing ───────────────────────────────────────────────────────
def _provider_has_credentials(provider_name: str) -> bool:
    cfg = STREAM_PROVIDERS.get(provider_name) or {}
    return bool(cfg.get("api_key"))


def _provider_is_cooled_down(provider_name: str) -> bool:
    until = _PROVIDER_COOLDOWNS.get(provider_name)
    if not until:
        return False
    if until <= time.time():
        _PROVIDER_COOLDOWNS.pop(provider_name, None)
        return False
    return True


def _generation_error_is_timeout(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "timeout" in text
        or "timed out" in text
        or exc.__class__.__name__.lower() in {"timeout", "timeouterror"}
    )


def _mark_provider_failure(provider_name: str, exc: Exception) -> None:
    if provider_name not in STREAM_PROVIDERS:
        return
    if PROVIDER_FAILURE_COOLDOWN_SECONDS <= 0:
        return
    _PROVIDER_COOLDOWNS[provider_name] = (
        time.time() + PROVIDER_FAILURE_COOLDOWN_SECONDS
    )


def _clear_provider_failure(provider_name: str) -> None:
    _PROVIDER_COOLDOWNS.pop(provider_name, None)


def _provider_attempt_order(provider: str = "auto") -> List[str]:
    """Return providers to try, preserving forced-provider behavior."""
    # Read STREAM_PROVIDER via the streaming module so tests that
    # ``monkeypatch.setattr(streaming, "STREAM_PROVIDER", ...)`` take effect.
    from algorithms import streaming as _streaming  # lazy to avoid load cycle
    stream_provider = getattr(_streaming, "STREAM_PROVIDER", STREAM_PROVIDER)
    requested = provider if provider != "auto" else stream_provider
    if requested != "auto":
        return [requested] if requested in STREAM_PROVIDERS else ["openai"]

    configured = [
        name for name in PROVIDER_PRIORITY if _provider_has_credentials(name)
    ]
    if not configured:
        return ["openai"]

    active = [name for name in configured if not _provider_is_cooled_down(name)]
    return active or configured


def _select_provider() -> str:
    """Auto-select the first configured provider that is not in cooldown."""
    order = _provider_attempt_order("auto")
    return order[0] if order else "openai"


# ═══════════════════════════════════════════════════════════════════════════════
# NARRATIVE CONTEXT
# ═══════════════════════════════════════════════════════════════════════════════


# ─── LLM invocation layer ───────────────────────────────────────────────────
def stream_generate(
    prompt: str,
    context: NarrativeContext,
    provider: str = "auto",
) -> Iterator[str]:
    """
    Stream tokens from LLM provider.

    Yields tokens as they arrive for real-time processing.

    Args:
        prompt: The full prompt to send
        context: NarrativeContext for provider routing
        provider: Provider name or "auto"

    Yields:
        str: Tokens as they arrive
    """
    providers = _provider_attempt_order(provider)
    if len(providers) == 1 and providers[0] != "openai":
        yield from _generate_non_streaming(prompt, context, providers=providers)
        return

    stream_failures: List[Tuple[str, Exception]] = []

    for provider_name in providers:
        try:
            content = _generate_with_provider(
                prompt, context, provider_name, stream=True
            )
            if content.strip():
                _clear_provider_failure(provider_name)
                print(
                    f"[STREAM] Provider {provider_name} succeeded "
                    f"({len(content)} chars)"
                )
                yield from _yield_llm_chunks(content)
                return
            raise ValueError("empty provider response")
        except Exception as e:
            _mark_provider_failure(provider_name, e)
            stream_failures.append((provider_name, e))
            print(f"[STREAM] Provider {provider_name} failed: {e}")

    non_streaming_candidates = [
        provider_name
        for provider_name, exc in stream_failures
        if not _generation_error_is_timeout(exc)
    ]
    if not non_streaming_candidates:
        yield ""
        return

    yield from _generate_non_streaming(
        prompt, context, providers=non_streaming_candidates
    )


def _build_llm_messages(prompt: str, context: NarrativeContext) -> List[dict]:
    return [
        {"role": "system", "content": _build_stream_system_msg(context)},
        {"role": "user", "content": prompt},
    ]


def _yield_llm_chunks(content: str, chunk_size: int = 20) -> Iterator[str]:
    for i in range(0, len(content), chunk_size):
        yield content[i : i + chunk_size]


def _provider_request_timeout(cfg: dict) -> int:
    configured = int(cfg.get("timeout") or 60)
    cap = int(PROVIDER_TOTAL_TIMEOUT_SECONDS or 0)
    if cap <= 0:
        return configured
    return max(10, min(configured, cap))


def _provider_max_tokens(context: NarrativeContext, *, stream: bool) -> int:
    mode = str(context.domain_state.get("video_mode") or "").lower()
    if mode == "short":
        return 2200 if stream else 2800
    if mode == "standard":
        return 2200 if stream else 2800
    if mode in {"course", "lecture"}:
        return 2400 if stream else 3200
    return 2600 if stream else 3400


# Some upstream proxies (e.g. third-party gpt-5.x relays) reject the legacy
# `max_tokens` field — and the openai SDK 2.x silently rewrites it to either
# `max_completion_tokens` (chat) or `max_output_tokens` (responses) depending
# on the detected model family. When that rewritten field comes back as a 400
# "Unsupported parameter", we retry once without any token cap.
_MAX_TOKEN_PARAM_HINTS = (
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
)


_MAX_TOKEN_REJECT_PHRASES = (
    "unsupported parameter",
    "unrecognized",
    "is not supported",
    "not allowed",
    "is not allowed",
    "not permitted",
)


def _is_max_tokens_unsupported_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if not any(p in msg for p in _MAX_TOKEN_REJECT_PHRASES):
        return False
    return any(hint in msg for hint in _MAX_TOKEN_PARAM_HINTS)


def _create_chat_completion(client, *, stream: bool, **kwargs):
    """Call chat.completions.create with a retry that drops max_tokens.

    Returns the response object as-is. Raises whatever the SDK raises when
    the retry path is not applicable.
    """
    try:
        return client.chat.completions.create(stream=stream, **kwargs)
    except Exception as exc:
        if "max_tokens" in kwargs and _is_max_tokens_unsupported_error(exc):
            kwargs.pop("max_tokens", None)
            print(
                "[STREAM] Provider rejected max_tokens parameter; "
                "retrying without a token cap"
            )
            return client.chat.completions.create(stream=stream, **kwargs)
        raise


def _partial_scene_content_is_usable(content: str) -> bool:
    lowered = (content or "").lower()
    return (
        len(content or "") >= 1200
        and "from manim import" in lowered
        and "class generatedscene" in lowered
        and "def construct" in lowered
    )


def _generate_with_provider(
    prompt: str,
    context: NarrativeContext,
    provider_name: str,
    *,
    stream: bool,
) -> str:
    # Read the subprocess toggle via the streaming module so tests that
    # ``monkeypatch.setattr(streaming, "STREAM_PROVIDER_USE_SUBPROCESS", ...)``
    # still reach us here.
    from algorithms import streaming as _streaming  # lazy to avoid load cycle
    use_subprocess = getattr(
        _streaming, "STREAM_PROVIDER_USE_SUBPROCESS", STREAM_PROVIDER_USE_SUBPROCESS
    )
    if use_subprocess:
        return _generate_with_provider_subprocess(
            prompt, context, provider_name, stream=stream
        )
    return _generate_with_provider_in_process(
        prompt, context, provider_name, stream=stream
    )


def _generate_with_provider_in_process(
    prompt: str,
    context: NarrativeContext,
    provider_name: str,
    *,
    stream: bool,
) -> str:
    cfg = STREAM_PROVIDERS.get(provider_name, STREAM_PROVIDERS["openai"])
    request_timeout = _provider_request_timeout(cfg)
    started = time.time()
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            timeout=request_timeout,
        )

        messages = _build_llm_messages(prompt, context)

        response = _create_chat_completion(
            client,
            model=cfg["model"],
            messages=messages,
            stream=stream,
            max_tokens=_provider_max_tokens(context, stream=stream),
        )

        if not stream:
            return response.choices[0].message.content or ""

        chunks = []
        for chunk in response:
            if time.time() - started > request_timeout:
                partial = "".join(chunks)
                if _partial_scene_content_is_usable(partial):
                    print(
                        f"[STREAM] Provider {provider_name} hit {request_timeout}s; "
                        f"using partial candidate ({len(partial)} chars)"
                    )
                    return partial
                raise TimeoutError(
                    f"{provider_name} streaming exceeded {request_timeout}s"
                )
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
        return "".join(chunks)

    except Exception as e:
        raise e


def _generate_with_provider_subprocess(
    prompt: str,
    context: NarrativeContext,
    provider_name: str,
    *,
    stream: bool,
) -> str:
    """Run provider generation in a child process so timeout kills are real."""
    cfg = STREAM_PROVIDERS.get(provider_name, STREAM_PROVIDERS["openai"])
    request_timeout = _provider_request_timeout(cfg)
    payload = {
        "api_key": cfg.get("api_key") or "",
        "base_url": cfg.get("base_url"),
        "model": cfg.get("model"),
        "timeout": request_timeout,
        "stream": bool(stream),
        "max_tokens": _provider_max_tokens(context, stream=stream),
        "messages": _build_llm_messages(prompt, context),
    }

    tmp_dir = Path(tempfile.mkdtemp(prefix="nima-llm-"))
    payload_path = tmp_dir / "payload.json"
    output_path = tmp_dir / "output.txt"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    output_path.write_text("", encoding="utf-8")
    # Resolve to the project root (parent of `algorithms/`) so `python -m
    # algorithms._streaming_child` can import the module regardless of the
    # parent process's cwd.
    project_root = Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "algorithms._streaming_child",
                str(payload_path),
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=request_timeout + 5,
            cwd=str(project_root),
        )
        content = output_path.read_text(encoding="utf-8", errors="replace")
        # Surface any [STREAM] telemetry the child emitted to stdout (e.g.,
        # the max_tokens-fallback log line) so it lands in operator logs
        # alongside the parent's [STREAM] lines.
        if result.stdout:
            for line in result.stdout.splitlines():
                if line.startswith("[STREAM]"):
                    print(line)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "provider subprocess failed")[-1200:])
        return content
    except subprocess.TimeoutExpired as exc:
        content = output_path.read_text(encoding="utf-8", errors="replace")
        # Surface child telemetry the kill captured before SIGKILL — e.g. a
        # successful max_tokens fallback log from the *first* call where the
        # *retry* is what timed out. Both bytes and str payloads are possible
        # depending on platform.
        partial_stdout = exc.stdout
        if isinstance(partial_stdout, bytes):
            partial_stdout = partial_stdout.decode("utf-8", errors="replace")
        if partial_stdout:
            for line in partial_stdout.splitlines():
                if line.startswith("[STREAM]"):
                    print(line)
        if stream and _partial_scene_content_is_usable(content):
            print(
                f"[STREAM] Provider {provider_name} subprocess hit {request_timeout}s; "
                f"using partial candidate ({len(content)} chars)"
            )
            return content
        raise TimeoutError(f"{provider_name} generation exceeded {request_timeout}s") from exc
    finally:
        try:
            payload_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass


def _generate_non_streaming(
    prompt: str,
    context: NarrativeContext,
    providers: Optional[List[str]] = None,
) -> Iterator[str]:
    """Fallback non-streaming generation."""
    candidate_providers = providers or _provider_attempt_order("auto")

    for provider_name in candidate_providers:
        try:
            content = _generate_with_provider(
                prompt, context, provider_name, stream=False
            )
            if content.strip():
                _clear_provider_failure(provider_name)
                print(
                    f"[STREAM] Non-streaming provider {provider_name} succeeded "
                    f"({len(content)} chars)"
                )
                yield from _yield_llm_chunks(content)
                return
            raise ValueError("empty provider response")
        except Exception as e:
            _mark_provider_failure(provider_name, e)
            print(f"[STREAM] Non-streaming provider {provider_name} failed: {e}")

    yield ""


def _build_stream_system_msg(context: NarrativeContext) -> str:
    """Build the system message for streaming generation."""
    language_lock = os.environ.get("NIMA_LANGUAGE_LOCK", "").strip()
    language_block = ""
    if language_lock:
        language_block = (
            f"LANGUAGE LOCK (NON-NEGOTIABLE, OVERRIDES EVERY OTHER RULE):\n"
            f"- Every Text(), Tex(), MathTex() string in the generated code "
            f"MUST be written in {language_lock}.\n"
            f"- Every title, label, hint, summary, takeaway, and chapter marker "
            f"MUST be in {language_lock}.\n"
            f"- DO NOT output English captions like 'Cold Open', 'The Setup', "
            f"'ray', 'straight angle', 'summary', 'rewind', 'looks settled', "
            f"'locked anyway', etc. Translate them into {language_lock}.\n"
            f"- The ONLY allowed non-{language_lock} tokens on screen are:\n"
            f"    * single-letter math/geometry vertex names (A, B, C, D, E, "
            f"O, P, Q, x, y, z), \n"
            f"    * digits and degree/percent/math symbols (e.g. 60°, 180°, "
            f"+, -, =, ÷, ×).\n"
            f"- If a label name was historically English in the model's "
            f"training data, REWRITE IT in {language_lock} before emitting.\n\n"
        )

    base = language_block + """\
You are an expert Manim CE v0.18 code generator producing single scenes.
You generate ONE scene at a time with full narrative context.

CRITICAL RULES:
1. Return ONLY the complete, runnable Manim Python code. No prose, no markdown.
2. class Scene must be named GeneratedScene with def construct(self)
3. All imports: from manim import *
4. NEVER use: start_section(), begin_section(), end_section() — these don't exist in Manim CE
5. NEVER use: SVGMobject, ImageMobject, or emoji
6. Use MathTex for formulas only if LaTeX commands are necessary; otherwise prefer readable Text with plain ASCII math
7. Include adequate self.wait() for pacing
8. Clean up only distracting construction artifacts; keep the final explanatory visual alive when the mode contract asks for a payoff frame.
9. Return code only — no comments, no explanations
10. NEVER repeat prior scenes or re-introduce already explained concepts unless explicitly asked
11. This is part of a continuous video: avoid hard resets, avoid "intro"/"summary" recaps in middle scenes
12. For scene_index > 0, continue from prior context state and focus only on NEW progression
13. ALL scenes in a job must use the SAME visual theme and SAME background color
14. Default to dark mode unless explicitly told otherwise
15. NEVER use self.camera.frame or camera.frame unless the scene explicitly subclasses MovingCameraScene (it does not here)
16. Do not call average_color() with raw string hex values; use explicit Manim colors only
17. Never prefix labels with literal words like "text", "label", or "title". Use Text("Prime pieces"), not Text("textPrime pieces").
18. Keep each scene concise: use loops, VGroups, and transforms instead of huge duplicated object lists; target 90-180 lines of code.
19. Dynamic labels created with always_redraw must position themselves inside the lambda, e.g. Text(...).next_to(anchor, UP); do not position them once afterward in a VGroup.

"""

    try:
        from algorithms.code_digest import latex_toolchain_available

        latex_available = latex_toolchain_available()
    except Exception:
        latex_available = False
    if not latex_available:
        base += """\
LOCAL RENDERER NOTE:
- LaTeX is not available in this environment. Do not use MathTex or Tex unless absolutely unavoidable.
- Use Text with plain ASCII math instead: =>, <=, >=, x, ^, and simple parentheses.
- Do not use LaTeX-only symbols such as \\Rightarrow, \\checkmark, \\cdots, or \\text{...}.

"""

    if context.domain_state.get("video_mode") == "short" or context.domain_state.get(
        "aspect"
    ) == "9:16":
        base += """\
SHORT VERTICAL QUALITY RULES:
- Design for a 9:16 phone screen: big central objects, high contrast, minimal text.
- Use font_size >= 34 for labels and >= 44 for titles; never use .scale() to shrink text below readability.
- Keep all important objects within x = -3.2..3.2 and y = -6.5..6.5.
- Avoid wide side-by-side layouts; stack vertically or use one central diagram.
- Fill the center of the screen: the main visual group should span at least half the phone width or height.
- Use at most 4 short text labels on screen at once.
- Keep each Text string under 28 visible characters per line; use "\\n" line breaks for anything longer.
- For probability, tables, tests, or comparisons, animate one stacked table/card at a time; do not place two dense tables side by side on a phone screen.
- Keep labels outside cell borders and dividers with visible padding; never draw text across a line or rectangle edge.
- Prefer dark high-contrast background with bright foreground text.

SHORT SOCIAL CREATIVE CONTRACT:
- This is a high-retention 55-60 second social short, not a compressed lecture.
- Never make a static title card, static bullet list, or text-only explainer scene.
- Every scene must have a moving central object within the first 0.5 seconds.
- Every scene must contain at least three distinct visual events: move, pulse, transform, trace, collide, overwrite, reveal, or highlight.
- Text is a HUD layer only: short hook, one live label, or one challenge. The concept must be carried by motion.
- Prefer concrete domain objects: graph nodes and edge weights, molecules and bonds, cars and velocity arrows, arrays and search windows, curves and moving points.
- Use fast beat pacing: many short animations with brief waits, not one slow Write followed by a long wait.
- Override the normal cleanup habit for shorts: do not FadeOut every object before the last wait.
- End by holding the final graph/object/challenge frame on screen; scene stitching can cut from that living frame.

"""

    if context.domain_state.get("video_mode") == "standard":
        base += """\
STANDARD YOUTUBE EXPLAINER RULES:
- This is a 16:9, 2-5 minute YouTube explainer chapter, not a classroom lecture.
- Use a cold-open/setup/tension/mechanism/example/misconception/payoff/takeaway arc across the full video.
- Keep one recurring anchor visual that evolves; do not rebuild unrelated title cards scene after scene.
- No quizzes, question pauses, comment CTAs, or static bullet/title cards.
- Every scene needs concrete objects, visible state changes, and at least one pattern interrupt: compare, zoom, transform, reveal, simulate, or show a mistake.
- Text is for labels, equations, and short chapter markers. Motion and object state must carry the explanation.
- When adding a new dense label, panel, or branch over existing material, dim the older layer and put a translucent focus plate behind the new layer. Do not use literal blur filters; do not let crisp text overlap crisp old text.
- Scale the main visual group into a safe inner frame when labels, arrows, or panels approach the edge.
- End each chapter on a living visual payoff or open loop; do not FadeOut every object before the final wait.

"""

    if context.domain_state.get("video_mode") == "course":
        base += """\
COURSE LESSON RULES:
- This is a 16:9 modular course lesson, not a viral short or a fast YouTube explainer.
- Structure matters: show chapter/module labels, progress rail, learning objectives, worked examples, checkpoints, recap maps, and transfer examples.
- A course is made from short scenelets inside chapters. Keep each scene focused on one 10-30 second teaching move instead of one long board that accumulates objects.
- Question scenes are intentional thinking pauses. Keep each question to one prompt, a faint prior anchor visual, and a subtle timer or progress pulse.
- Content scenes must teach with diagrams, state changes, examples, and reusable visual vocabulary, not paragraph boards.
- Keep text readable and sparse: short labels, definitions, checklist rows, and one-sentence takeaways only.
- Return to the same course map or anchor visual between modules so the learner sees progress.
- Use slower deliberate pacing than standard mode, but every scene still needs visible visual progress.
- Keep important text and objects inside x=-5.7..5.7 and y=-2.9..2.9; scale the main visual group into a safe inner frame before animations.
- Use focus layering instead of accidental overlap: do not use literal blur filters; dim older groups to about 20-30 percent opacity, add a translucent focus plate behind the new label/panel, and raise the active layer with z-index.

"""

    if context.domain_state.get("video_mode") == "lecture":
        base += """\
ACADEMIC LECTURE RULES:
- This is a formal 16:9 academic lecture, not a viral short and not a YouTube retention chapter.
- Build definitions, theorem statements, lemmas, proof steps, worked examples, pitfalls, and recap maps as separate scenelets.
- Keep each scene focused on one derivation or proof move. Do not create a giant board that carries stale text for minutes.
- Use a small section label, proof map, equation ladder, or assumption ledger so the viewer knows where they are in the argument.
- Use focus layering for derivation steps: dim older proof context, put a translucent plate behind the active line, and raise active z-index.
- Use font_size >= 24 for every label, justification, and equation line. Do not use tiny 18-23px labels.
- Keep important notation inside x=-5.4..5.4 and y=-2.65..2.65; scale the main board into width 10.8 and height 5.3.
- Keep at most five active proof lines visible at once; dim older material into a proof map instead of stacking a proof wall.
- Questions are quiet thinking pauses, not quizzes or social CTAs. Do not reveal the answer inside a question scene.

"""

    ctx_str = context.to_context_string()
    return base + "\n" + ctx_str


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE GENERATION
# ═══════════════════════════════════════════════════════════════════════════════


# Retry-prompt helpers were extracted to algorithms.streaming_prompts in
# the issue-#11 split. Re-imported here so existing call sites and tests that
# patch e.g. `streaming._classify_retry_error` continue to work unchanged.
