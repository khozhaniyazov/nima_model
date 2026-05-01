# Pipeline Modes & Rendering — Phase 1 Research

**Project:** NIMA (Manim AI Generator)
**Researched:** 2026-04-04
**Phase:** 1 — Foundation & Stability

---

## Executive Summary

The NIMA pipeline supports three render modes (FULL/FAST/DRAFT) controlled by environment variables. Manim rendering is orchestrated through `_run_manim()` which writes scripts to `MANIM_SCRIPTS/` and outputs to `OUTPUTS/`. Video file detection is the most fragile part of the pipeline — `find_video_file()` uses a fallback chain that works but has edge cases around stale files and non-standard output locations.

**Critical issue for Phase 1:** `find_video_file()` hardcodes `GeneratedScene.mp4` as a candidate path, but the actual manim command specifies `--output_file {filename}.mp4` which produces `video_{job_id}.mp4`. This mismatch is masked by the glob fallback but could cause issues in certain race conditions.

---

## Pipeline Modes

### Mode Configuration

| Mode | Environment Variable | Defined In | Default |
|------|---------------------|-----------|---------|
| **FULL** | Both `FAST_PIPELINE` and `DRAFT_PIPELINE` are `"false"` | `config.py:38-41` | ✓ (default) |
| **FAST** | `FAST_PIPELINE="true"` | `config.py:38` | |
| **DRAFT** | `DRAFT_PIPELINE="true"` | `config.py:39-40` | |

### Mode Detection Pattern

```python
# app.py:322
is_fast = FAST_PIPELINE or DRAFT_PIPELINE
```

Both FAST and DRAFT are treated as "fast modes" for the purpose of skipping validations.

### Mode Differences Summary

| Feature | FULL | FAST | DRAFT |
|---------|------|------|-------|
| **Generation attempts** | `MAX_GENERATION_ATTEMPTS` (2) | 1 | 1 |
| **Render retries** | `MAX_RENDER_RETRIES` (3) | 1 | 1 |
| **Quality validation** | ✓ Full | Skip | Skip |
| **LaTeX validation** | ✓ Full (math domain) | Skip | Skip |
| **Security validation** | ✓ Full | Skip | Skip |
| **Overlap detection** | ✓ Full | Skip | Skip |
| **Code review pass** | ✓ Full | Critical errors only | Critical errors only |
| **GPT-4 evaluation** | ✓ After render | Skip | Skip |
| **Manim warmup** | ✓ On startup | ✓ | Skip |
| **Render quality flag** | `-ql` | `-ql` | `-qk` |
| **Render FPS** | 30 | 15 | 10 |
| **Verbosity** | `--verbose=INFO` | `--verbose=WARNING` | `--verbose=ERROR` |

### config.py Definitions

```python
# config.py:34-41
# ── Render pipeline ───────────────────────────────────────────────────────────
MAX_GENERATION_ATTEMPTS = 2  # AI generation retries
MAX_RENDER_RETRIES = 3  # manim render retries (with LLM error-fix between each)
RENDER_TIMEOUT_SECONDS = 900  # 15 min max per render
FAST_PIPELINE = os.environ.get("FAST_PIPELINE", "false").lower() == "true"
DRAFT_PIPELINE = (
    os.environ.get("DRAFT_PIPELINE", "false").lower() == "true"
)  # Ultra-fast preview mode
```

---

## Manim Rendering (`_run_manim`)

### Location
`app.py:734-779`

### Function Signature

```python
def _run_manim(code: str, filename: str, job_id: str) -> subprocess.CompletedProcess:
    """Write the script and run manim. Returns the CompletedProcess."""
```

### Process Flow

1. **Write script** to `MANIM_SCRIPTS / f"{filename}.py"`
2. **Clean stale files** via `OUTPUTS.rglob(f"{filename}*.mp4")` deletion
3. **Build manim command** based on pipeline mode
4. **Execute** via `subprocess.run()` with `RENDER_TIMEOUT_SECONDS` (900s default)

### Manim Command Construction

```python
# app.py:747-776
if DRAFT_PIPELINE:
    quality_flag = "-qk"  # Keep edges (lowest)
    fps = "10"
    verbosity = "--verbose=ERROR"
elif is_fast:
    quality_flag = "-ql"  # Low quality
    fps = "15"
    verbosity = "--verbose=WARNING"
else:
    quality_flag = "-ql"  # Default to low for speed
    fps = "30"
    verbosity = "--verbose=INFO"

cmd = [
    "manim",
    str(script_path),
    "GeneratedScene",        # Scene class name
    quality_flag,
    "--format=mp4",
    "--media_dir",
    str(OUTPUTS),
    "--output_file",
    f"{filename}.mp4",
    "--disable_caching",
    "--fps",
    fps,
    verbosity,
]
```

**Key observation:** The scene class is hardcoded as `GeneratedScene` in the manim command, not the actual class name in the code. The `ensure_scene_class()` function in `code_digest.py` wraps generated code to ensure it has a `GeneratedScene` class.

### Quality Flags Explained

| Flag | Meaning | Resolution | Use Case |
|------|---------|------------|----------|
| `-qk` | "Keep edges" draft | ~854x480 | Fastest preview, visible edges |
| `-ql` | Low quality | 1920x1080 | Quick iterations |
| `-qm` | Medium quality | 1920x1080 | Balanced |
| `-qh` | High quality | 1920x1080 | Final output |
| `-qp` | Production quality | 2560x1440 | Maximum quality |

**Current issue:** FULL mode uses `-ql` (low quality) not `-qm` or `-qh`. This appears intentional for speed, but means FULL is not actually "full quality" — it's "standard speed/medium quality."

---

## Video File Detection (`find_video_file`)

### Location
`app.py:712-731`

### Function

```python
def find_video_file(filename: str) -> Optional[Path]:
    """Search for the rendered video file in common output locations."""
    direct = OUTPUTS / f"{filename}.mp4"
    if direct.exists():
        return direct

    candidates = [
        OUTPUTS / "videos" / filename / "1080p60" / "GeneratedScene.mp4",
        OUTPUTS / "videos" / "1080p60" / "GeneratedScene.mp4",
        OUTPUTS / filename / "GeneratedScene.mp4",
        OUTPUTS / "GeneratedScene.mp4",
    ]
    for p in candidates:
        if p.exists():
            return p

    # Glob fallback - exact match prefix to avoid stale files
    for mp4 in OUTPUTS.rglob(f"{filename}*.mp4"):
        return mp4
    return None
```

### Detection Chain

1. **Direct path**: `C:/temp/outputs/video_{job_id}.mp4` (where filename = `video_{job_id}`)
2. **Manim standard structure** (incorrectly looking for `GeneratedScene.mp4`):
   - `C:/temp/outputs/videos/{filename}/1080p60/GeneratedScene.mp4`
   - `C:/temp/outputs/videos/1080p60/GeneratedScene.mp4`
   - `C:/temp/outputs/{filename}/GeneratedScene.mp4`
   - `C:/temp/outputs/GeneratedScene.mp4`
3. **Glob fallback**: Any file matching `{filename}*.mp4` in OUTPUTS tree

### Actual Manim Output Structure

Based on filesystem inspection of `C:/temp/outputs/`:

```
C:/temp/outputs/
├── videos/
│   ├── video_08c42758/
│   │   ├── 480p15/
│   │   │   ├── partial_movie_files/
│   │   │   └── video_08c42758.mp4  ← actual output
│   │   └── 1080p60/
│   │       ├── partial_movie_files/
│   │       └── video_08c42758.mp4
│   └── video_19e37ee3/
│       └── 480p15/
│           └── video_19e37ee3.mp4
├── audio/
│   └── {job_id}/
│       └── *.mp3
└── *_narrated.mp4  ← post-processed with audio
```

**The `GeneratedScene.mp4` paths in `find_video_file` never match actual output.** The glob fallback (`rglob`) is what actually finds the file.

---

## Rendering Flow (`save_and_render`)

### Location
`app.py:782-947`

### Key Flow

```
save_and_render()
├── Loop: render_attempt in 1..render_retries
│   ├── _run_manim(current_code, filename, job_id)
│   ├── find_video_file(filename)  ← Check FIRST
│   │   ├── If video found AND returncode != 0:
│   │   │   └── Warning logged but treated as success
│   │   ├── If video found AND returncode == 0:
│   │   │   └── SUCCESS - merge audio if segments exist
│   │   ├── If returncode == 0 but no video:
│   │   │   └── Error: "file_not_found"
│   │   └── If returncode != 0 AND no video:
│   │       └── Parse stderr → fix_render_error() → retry
│   └── On final failure: save to database, set error status
├── After success: GPT-4 evaluation (FULL mode only)
└── Return
```

### Audio Merge

If `audio_segments` and `segment_order` are provided (voiceover enabled):

```python
# app.py:841-847
if audio_segments and segment_order:
    narrated_output = str(OUTPUTS / f"{filename}_narrated.mp4")
    final_video_path = merge_audio_video(
        str(video_path), audio_segments, segment_order, narrated_output
    )
```

---

## Output Directory Structure

### Configuration

```python
# config.py:22-26
# ── Filesystem ───────────────────────────────────────────────────────────────
MANIM_SCRIPTS = Path("C:/temp/manim_scripts")
OUTPUTS = Path("C:/temp/outputs")
MANIM_SCRIPTS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)
```

### Directory Layout

| Path | Purpose | Created By |
|------|---------|------------|
| `C:/temp/manim_scripts/` | Temporary Python scripts | `config.py` (ensured exists) |
| `C:/temp/outputs/` | All render outputs | `config.py` (ensured exists) |
| `C:/temp/outputs/videos/{filename}/` | Per-job videos | Manim |
| `C:/temp/outputs/audio/{job_id}/` | TTS audio segments | `tts.py` |
| `C:/temp/outputs/images/` | Static images | Manim |
| `C:/temp/outputs/texts/` | Text renders | Manim |
| `C:/temp/outputs/Tex/` | LaTeX renders | Manim |

### File Naming

| Pattern | Example | Source |
|---------|---------|--------|
| Job ID | `08c42758` | `str(uuid.uuid4())[:8]` |
| Filename | `video_08c42758` | `f"video_{job_id}"` |
| Script | `video_08c42758.py` | `_run_manim()` |
| Video (low quality) | `video_08c42758.mp4` in `480p15/` | Manim via `--output_file` |
| Video (high quality) | `video_08c42758.mp4` in `1080p60/` | Manim |
| Narrated | `video_08c42758_narrated.mp4` | `merge_audio_video()` |
| Audio segment | `seg_0.mp3`, `seg_1.mp3` | `tts.py` |

---

## Edge Cases & Issues

### Issue 1: `GeneratedScene.mp4` Path Never Exists

**Severity:** Low (works due to glob fallback)

The `find_video_file()` function checks for `GeneratedScene.mp4` in multiple locations, but manim actually outputs `{filename}.mp4` as specified by `--output_file`. The hardcoded `GeneratedScene` paths never match.

**Evidence:**
- `find_video_file()` candidate: `OUTPUTS / "videos" / filename / "1080p60" / "GeneratedScene.mp4"`
- Actual output: `OUTPUTS / "videos" / filename / "1080p60" / "video_{job_id}.mp4"`

**Workaround:** The glob fallback `OUTPUTS.rglob(f"{filename}*.mp4")` finds the actual file.

### Issue 2: Race Condition in File Detection

**Severity:** Medium

Between `_run_manim()` returning and `find_video_file()` being called, the file should exist. However, if multiple renders are running simultaneously or if the glob finds a stale file from a previous render with the same `job_id`, incorrect file could be returned.

**Evidence:** The glob fallback doesn't verify the file is from the current render.

### Issue 3: Stale File Cleanup Only on Exact Match Prefix

**Severity:** Low

```python
# app.py:741-745
for old_file in OUTPUTS.rglob(f"{filename}*.mp4"):
    try:
        old_file.unlink()
```

This deletes `{filename}*.mp4` before rendering, which should prevent stale file issues for the current job. However, `*_narrated.mp4` files are not cleaned up.

### Issue 4: Non-Zero Exit Code With Video Production

**Severity:** Low (handled)

```python
# app.py:833-837
if video_path:
    if result.returncode != 0:
        print(f"[{job_id}] [WARN] Manim exited with code {result.returncode} but video was produced — treating as success")
```

Manim can exit with code 1 for non-fatal issues (e.g., cache full) even when video is successfully produced. This is correctly handled.

### Issue 5: `is_fast` Variable Scope Issue

**Severity:** Low

The variable `is_fast` is calculated inside `generate_and_validate_code()` at line 322:

```python
is_fast = FAST_PIPELINE or DRAFT_PIPELINE
```

But in `_run_manim()` at line 753, there's a reference to `is_fast` that may not be in scope if called from a different context:

```python
elif is_fast:
    quality_flag = "-ql"
```

This works because `is_fast` is module-level (defined at 322 before being used in `_run_manim`), but it's confusing and fragile.

### Issue 6: DRAFT Pipeline Skips Warmup

**Severity:** Low

```python
# app.py:1185-1187
if DRAFT_PIPELINE:
    print("[WARMUP] Skipping manim warmup in DRAFT mode")
    return
```

DRAFT mode skips the `prewarm_manim()` call at startup. For DRAFT this is fine (you're accepting lowest quality), but it means the first DRAFT render pays the full startup cost.

---

## Phase 1 Recommendations

### MODE-01, MODE-02, MODE-03 Implementation Status

| Requirement | Status | Notes |
|-------------|--------|-------|
| FULL/FAST/DRAFT modes via env vars | ✓ Implemented | `config.py:38-41` |
| Mode affects render quality/FPS | ✓ Implemented | `_run_manim()` lines 748-760 |
| Mode skips expensive validations | ✓ Implemented | `generate_and_validate_code()` lines 510-679 |
| Mode reduces retries | ✓ Implemented | `save_and_render()` line 804 |
| Mode skips GPT-4 evaluation | ✓ Implemented | `save_and_render()` lines 863-882 |
| Mode skips manim warmup | ✓ Implemented | `app.py:1185-1187` |

### GEN-01-05 (Submit → Render → Download) Status

| Requirement | Status | Notes |
|-------------|--------|-------|
| GEN-01: Submit prompt | ✓ | `/api/generate` endpoint |
| GEN-02: Generate code | ✓ | `generate_and_validate_code()` |
| GEN-03: Render video | ✓ | `save_and_render()` + `_run_manim()` |
| GEN-04: Detect video file | ⚠️ Fragile | `find_video_file()` works but has issues |
| GEN-05: Download video | ✓ | `/outputs/<path>` endpoint |

### Phase 1 Tasks

1. **Fix `find_video_file()`** — Remove the `GeneratedScene.mp4` hardcoded paths that never match. The glob fallback is what's actually used; make it the primary search.

2. **Clarify FULL mode quality** — FULL uses `-ql` (low quality) not higher. Either rename to STANDARD or add HIGH_QUALITY mode with `-qh`.

3. **Add `is_fast` parameter to `_run_manim()`** — Don't rely on module-level variable; pass it explicitly.

4. **Clean up narrated files** — Add cleanup for `*_narrated.mp4` in the stale file deletion pass.

5. **Add video file verification** — After finding a video via glob, verify it's from the current render (e.g., check timestamp is recent).

---

## Sources

| Source | Confidence | What It Tells Us |
|--------|------------|------------------|
| `config.py` | HIGH | Pipeline mode configuration |
| `app.py:712-779` | HIGH | `_run_manim()` and `find_video_file()` implementation |
| `app.py:782-947` | HIGH | `save_and_render()` self-healing loop |
| `test_optimizations.py` | MEDIUM | Expected behavior of pipeline modes |
| Filesystem inspection | HIGH | Actual output structure |

---

*Research for Phase 1: Foundation & Stability — 2026-04-04*
