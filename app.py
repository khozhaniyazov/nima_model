"""
NIMA — Flask server.
Orchestrates the full pipeline:
  analyze → plan → generate → review → [render → (error→fix→render)×3]

Key improvements vs. original:
  - Single source of truth: all config from config.py
  - Render-error self-healing: up to MAX_RENDER_RETRIES attempts,
    feeding Manim stderr back to fix_render_error() between each attempt
  - ManimDatabase defined ONCE here and passed to algorithm functions
  - Clean separation: code generation is synchronous before the async render
"""

from flask import Flask, render_template, request, send_from_directory, jsonify
from flask_cors import CORS
from openai import OpenAI
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
import time
import json
import os
import subprocess
import re
import uuid
import threading
import random
import psycopg2
from psycopg2.extras import Json, RealDictCursor

from dotenv import load_dotenv
load_dotenv(override=True)

# ── Config ────────────────────────────────────────────────────────────────────
from config import (
    DB_CONNECTION_STRING,
    USE_DATABASE,
    MANIM_SCRIPTS,
    OUTPUTS,
    RENDER_TIMEOUT_SECONDS,
    MAX_RENDER_RETRIES,
    MAX_GENERATION_ATTEMPTS,
    ENABLE_VOICEOVER,
)

# ── Algorithm imports ──────────────────────────────────────────────────────────
from algorithms.request_analysis import (
    analyze_request_type, 
    create_animation_plan,
    create_narrated_plan,
    create_plan_json,
)
from algorithms.tts import generate_voiceover, merge_audio_video
from algorithms.ai_functions import (
    generate_manim_code,
    review_and_fix,
    polish_manim_code,
    fix_render_error,
    evaluate_with_gpt4,
    extract_code,
    inject_helpers,
)
from algorithms.plan.compiler import compile_plan
from algorithms.plan.schema import validate_plan_dict
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

print(f"[STARTUP] Manim scripts: {MANIM_SCRIPTS.absolute()}")
print(f"[STARTUP] Outputs:       {OUTPUTS.absolute()}")

render_status: Dict[str, dict] = {}
job_to_request: Dict[str, dict] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

class ManimDatabase:
    def __init__(self, connection_string: str):
        try:
            self.conn = psycopg2.connect(connection_string)
            self.conn.autocommit = True
            self.available = True
            print("[DB] [OK] Connected")
        except Exception as e:
            print(f"[DB] [ERR] Connection failed: {e}")
            self.conn = None
            self.available = False

    def _exec(self, sql, params=(), fetch=None):
        """Safe helper — returns None on error."""
        if not self.available:
            return None
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                if fetch == "one":
                    return cur.fetchone()
                if fetch == "all":
                    return cur.fetchall()
                return True
        except Exception as e:
            print(f"[DB] [ERR] {e}")
            return None

    def save_request(self, prompt: str, analysis: dict, user_id: str = None) -> str:
        rid = str(uuid.uuid4())
        self._exec(
            """INSERT INTO requests (id, prompt, user_id, topic, domain, complexity,
               estimated_duration, analysis_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (rid, prompt, user_id,
             analysis.get("topic"), analysis.get("domain"),
             analysis.get("complexity"), analysis.get("duration"),
             Json(analysis)),
        )
        return rid

    def save_generation_attempt(self, request_id: str, attempt_data: dict) -> str:
        aid = str(uuid.uuid4())
        self._exec(
            """INSERT INTO generation_attempts
               (id, request_id, attempt_number, model_version,
                animation_plan, generated_code, code_length,
                critique_feedback, improved_code,
                syntax_valid, syntax_error, structure_valid,
                quality_warnings, generation_time_ms)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (aid, request_id, attempt_data["attempt_number"],
             "gpt-4o", attempt_data.get("plan"), attempt_data["code"],
             len(attempt_data["code"]), attempt_data.get("critique"),
             attempt_data.get("improved_code"),
             attempt_data.get("syntax_valid", True),
             attempt_data.get("syntax_error"),
             attempt_data.get("structure_valid", True),
             Json(attempt_data.get("warnings", [])),
             attempt_data.get("generation_time_ms", 0)),
        )
        return aid

    def save_render_job(self, request_id: str, attempt_id: Optional[str], render_data: dict) -> str:
        jid = str(uuid.uuid4())
        self._exec(
            """INSERT INTO render_jobs
               (id, request_id, attempt_id, final_code, script_path,
                status, started_at, completed_at, render_duration_seconds,
                manim_stdout, manim_stderr, return_code, video_path,
                error_type, error_message)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (jid, request_id, attempt_id, render_data["code"],
             render_data.get("script_path"), render_data["status"],
             render_data.get("started_at"), render_data.get("completed_at"),
             render_data.get("duration"), render_data.get("stdout"),
             render_data.get("stderr"), render_data.get("return_code"),
             render_data.get("video_path"), render_data.get("error_type"),
             render_data.get("error_message")),
        )
        return jid

    def save_ai_evaluation(self, request_id: str, render_job_id: str, ev: dict) -> str:
        eid = str(uuid.uuid4())
        self._exec(
            """INSERT INTO ai_evaluations
               (id, request_id, render_job_id, evaluator_model,
                visual_quality_score, educational_value_score,
                technical_accuracy_score, pacing_timing_score,
                clarity_score, engagement_score, overall_score,
                strengths, weaknesses, specific_issues, suggestions,
                predicted_satisfaction, full_evaluation_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (eid, request_id, render_job_id, "gpt-4o-mini",
             ev.get("visual_quality", 0), ev.get("educational_value", 0),
             ev.get("technical_accuracy", 0), ev.get("pacing_timing", 0),
             ev.get("clarity", 0), ev.get("engagement", 0),
             ev.get("overall", 0), ev.get("strengths"),
             ev.get("weaknesses"), Json(ev.get("issues", [])),
             ev.get("suggestions"), ev.get("predicted_satisfaction", 0),
             Json(ev)),
        )
        return eid

    def get_best_examples(self, domain: str = None, limit: int = 3) -> list:
        q = """SELECT r.prompt, r.domain, r.topic, rj.final_code, ae.overall_score
               FROM requests r
               JOIN render_jobs rj ON r.id = rj.request_id
               JOIN ai_evaluations ae ON rj.id = ae.render_job_id
               WHERE rj.status = 'done' AND ae.overall_score >= 80"""
        params = []
        if domain:
            q += " AND r.domain = %s"
            params.append(domain)
        q += " ORDER BY ae.overall_score DESC LIMIT %s"
        params.append(limit)
        return self._exec(q, params, fetch="all") or []

    def get_error_patterns(self, limit: int = 5) -> list:
        return self._exec(
            """SELECT error_category, root_cause, fix_description, occurrence_count
               FROM error_patterns
               WHERE NOT resolved
               ORDER BY occurrence_count DESC LIMIT %s""",
            (limit,), fetch="all"
        ) or []

    def record_error_pattern(self, error_data: dict):
        sig = error_data["signature"]
        existing = self._exec(
            "SELECT id, occurrence_count FROM error_patterns WHERE error_signature = %s",
            (sig,), fetch="one"
        )
        if existing:
            self._exec(
                "UPDATE error_patterns SET occurrence_count=occurrence_count+1, last_seen=NOW() WHERE id=%s",
                (existing["id"],)
            )
        else:
            self._exec(
                """INSERT INTO error_patterns
                   (id, error_category, error_signature, example_error_message,
                    example_code_snippet, root_cause, fix_description)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (str(uuid.uuid4()), error_data["category"], sig,
                 error_data["message"], error_data.get("code_snippet"),
                 error_data.get("root_cause", "Unknown"),
                 error_data.get("fix", "Check syntax and API usage")),
            )


db = ManimDatabase(DB_CONNECTION_STRING) if USE_DATABASE else None


# ═══════════════════════════════════════════════════════════════════════════════
# CODE GENERATION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def generate_and_validate_code(
    prompt: str, job_id: str, max_attempts: int = MAX_GENERATION_ATTEMPTS,
    voiceover: bool = False
) -> Tuple[str, list, str, str, dict, list]:
    """
    Full AI pipeline:
      analyze → plan → [voiceover] → generate → combined review → validate → polish
    Returns (code, attempts_log, request_id, attempt_id, audio_segments, segment_order).
    """
    attempts_log = []
    request_id = None
    audio_segments = {}
    segment_order = []

    render_status[job_id]["message"] = "Analyzing request..."
    analysis = analyze_request_type(prompt)
    attempts_log.append({"stage": "analysis", "data": analysis})

    if db and db.available:
        request_id = db.save_request(prompt, analysis)
        print(f"[DB] [OK] Saved request: {request_id}")

    if voiceover:
        render_status[job_id]["message"] = "Creating narrated timeline..."
        plan = create_narrated_plan(prompt, analysis)
        try:
            parsed = json.loads(plan)
            segments = parsed.get("segments", [])
            segment_order = [s["id"] for s in segments]
            
            render_status[job_id]["message"] = "Generating narration audio..."
            audio_out_dir = OUTPUTS / "audio" / job_id
            audio_segments = generate_voiceover(segments, str(audio_out_dir))
        except Exception as e:
            print(f"[{job_id}] [ERR] Narration failed: {e}. Falling back to silent plan.")
            plan = create_animation_plan(prompt, analysis)
            voiceover = False
    else:
        render_status[job_id]["message"] = "Creating animation storyboard..."
        plan = create_animation_plan(prompt, analysis)
    
    attempts_log.append({"stage": "planning", "success": True})

    # ── Plan-first deterministic compilation (hybrid mode) ───────────────────
    plan_compiled_code = None
    use_plan_compiler = (analysis.get("domain") == "math") and (not voiceover)
    if use_plan_compiler:
        try:
            render_status[job_id]["message"] = "Creating plan JSON (deterministic)..."
            plan_json = create_plan_json(prompt, analysis)
            plan_data = json.loads(plan_json)
            issues = validate_plan_dict(plan_data)
            if issues:
                raise ValueError("; ".join(issues))
            plan_compiled_code = compile_plan(plan_data)
            attempts_log.append({"stage": "plan_json", "success": True})
        except Exception as e:
            print(f"[{job_id}] [PLAN] [ERR] Plan compiler fallback: {e}")
            plan_compiled_code = None

    if plan_compiled_code:
        code = ensure_scene_class(plan_compiled_code)

        # Safety validation
        render_status[job_id]["message"] = "Validating code safety..."
        is_safe, safety_issues = validate_names_and_imports(code)
        if not is_safe:
            print(f"[{job_id}] [SECURITY] Plan code unsafe: {safety_issues}")
            # Fallback to LLM path
        else:
            # Syntax validation
            render_status[job_id]["message"] = "Validating syntax..."
            syntax_valid, syntax_error = validate_python_syntax(code)
            if not syntax_valid:
                print(f"[{job_id}] [ERR] Plan syntax error: {syntax_error}")
            else:
                # Structure validation
                structure_valid, structure_error = validate_manim_code(code)
                if not structure_valid:
                    print(f"[{job_id}] [ERR] Plan structure error: {structure_error}")
                else:
                    # Quality warnings (non-blocking)
                    quality_passes, quality_feedback = check_code_quality(code)
                    attempts_log.append({"stage": "quality", "success": quality_passes, "feedback": quality_feedback})

                    # Overlap / scene-hygiene detection (non-blocking here)
                    render_status[job_id]["message"] = "Checking for layout overlaps..."
                    overlap_warnings = detect_overlaps(code)
                    if overlap_warnings:
                        print(f"[{job_id}] [OVERLAP] {len(overlap_warnings)} issues detected in plan code")
                        for w in overlap_warnings:
                            print(f"  {w}")
                        attempts_log.append({"stage": "overlap_check", "warnings": overlap_warnings})

                    return code, attempts_log, request_id, None, audio_segments, segment_order

    for attempt in range(1, max_attempts + 1):
        print(f"\n[{job_id}] {'='*50}")
        print(f"[{job_id}] GENERATION ATTEMPT {attempt}/{max_attempts}")
        print(f"[{job_id}] {'='*50}\n")
        attempt_start = time.time()

        # 1. Generate
        render_status[job_id]["message"] = f"Generating code (attempt {attempt})..."
        code = generate_manim_code(
            prompt, analysis, plan, attempt, db=db, 
            segment_durations=audio_segments if voiceover else None
        )
        attempts_log.append({"attempt": attempt, "stage": "generation", "success": True})

        # 2. Combined review (replaces self_critique + overlapping_fix + ai_fix)
        render_status[job_id]["message"] = "Reviewing and fixing layout..."
        code = review_and_fix(code, prompt, analysis)
        attempts_log.append({"attempt": attempt, "stage": "review", "success": True})

        # 3. Security / safety validation (AST-based — runs before syntax check)
        render_status[job_id]["message"] = "Validating code safety..."
        is_safe, safety_issues = validate_names_and_imports(code)
        if not is_safe:
            print(f"[{job_id}] [SECURITY] Unsafe patterns detected: {safety_issues}")
            # Feed safety violations into the review pass to auto-fix them
            safety_note = "\n".join(safety_issues)
            code = review_and_fix(
                code,
                f"{prompt}\n\n[SECURITY VIOLATIONS TO FIX]:\n{safety_note}",
                analysis
            )
            is_safe, safety_issues = validate_names_and_imports(code)
            if not is_safe and attempt < max_attempts:
                continue

        # 4. Syntax validation
        render_status[job_id]["message"] = "Validating syntax..."
        syntax_valid, syntax_error = validate_python_syntax(code)
        if not syntax_valid:
            print(f"[{job_id}] [ERR] Syntax error: {syntax_error}")
            attempts_log.append({"attempt": attempt, "stage": "syntax", "success": False, "error": syntax_error})
            if db and db.available:
                db.record_error_pattern({
                    "category": "syntax",
                    "signature": str(hash(syntax_error)),
                    "message": syntax_error,
                    "code_snippet": code[:200],
                })
            code = polish_manim_code(code)
            syntax_valid, syntax_error = validate_python_syntax(code)
            if not syntax_valid:
                if attempt < max_attempts:
                    continue
                raise Exception(f"Syntax error could not be fixed: {syntax_error}")

        attempts_log.append({"attempt": attempt, "stage": "syntax", "success": True})

        # 4. Scene class / structure
        code = ensure_scene_class(code)
        structure_valid, structure_error = validate_manim_code(code)
        if not structure_valid:
            if attempt < max_attempts:
                code = polish_manim_code(code)
                continue
            raise Exception(f"Structure error: {structure_error}")

        attempts_log.append({"attempt": attempt, "stage": "structure", "success": True})

        # 5. Quality warnings (non-blocking)
        quality_passes, quality_feedback = check_code_quality(code)
        attempts_log.append({"attempt": attempt, "stage": "quality", "success": quality_passes, "feedback": quality_feedback})

        # 6. Overlap / scene-hygiene detection
        render_status[job_id]["message"] = "Checking for layout overlaps..."
        overlap_warnings = detect_overlaps(code)
        if overlap_warnings:
            print(f"[{job_id}] [OVERLAP] {len(overlap_warnings)} issues detected")
            for w in overlap_warnings:
                print(f"  {w}")
            # Feed overlap warnings back to review for a targeted fix
            overlap_note = "\n".join(overlap_warnings)
            code = review_and_fix(
                code,
                f"{prompt}\n\n[LAYOUT OVERLAP ISSUES TO FIX]:\n{overlap_note}",
                analysis
            )
            code = ensure_scene_class(code)
            # Re-check (don't loop — one repair pass is enough)
            remaining = detect_overlaps(code)
            if remaining:
                print(f"[{job_id}] [OVERLAP] {len(remaining)} issues remain after fix attempt")
                quality_feedback.extend(remaining)
            else:
                print(f"[{job_id}] [OVERLAP] All issues resolved")
            attempts_log.append({"attempt": attempt, "stage": "overlap_fix", "warnings": overlap_warnings, "remaining": len(remaining) if remaining else 0})

        attempt_time = int((time.time() - attempt_start) * 1000)
        attempt_id = None
        if db and db.available and request_id:
            attempt_id = db.save_generation_attempt(request_id, {
                "attempt_number": attempt,
                "plan": plan,
                "code": code,
                "critique": "",
                "improved_code": code,
                "syntax_valid": syntax_valid,
                "syntax_error": None,
                "structure_valid": structure_valid,
                "warnings": quality_feedback,
                "generation_time_ms": attempt_time,
            })
            print(f"[DB] [OK] Saved attempt: {attempt_id}")

        return code, attempts_log, request_id, attempt_id, audio_segments, segment_order

    raise Exception("All generation attempts failed.")


# ═══════════════════════════════════════════════════════════════════════════════
# RENDER WITH SELF-HEALING RETRY LOOP
# ═══════════════════════════════════════════════════════════════════════════════

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


def _run_manim(code: str, filename: str, job_id: str) -> subprocess.CompletedProcess:
    """Write the script and run manim. Returns the CompletedProcess."""
    script_path = MANIM_SCRIPTS / f"{filename}.py"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)

    # Clean up old exact matches first so we don't return stale files
    for old_file in OUTPUTS.rglob(f"{filename}*.mp4"):
        try:
            old_file.unlink()
        except OSError:
            pass

    cmd = [
        "manim", str(script_path), "GeneratedScene",
        "-ql", "--format=mp4",
        "--media_dir", str(OUTPUTS),
        "--output_file", f"{filename}.mp4",
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS)


def save_and_render(
    code: str, filename: str, job_id: str,
    request_id: str = None, prompt: str = "", attempt_id: str = None,
    audio_segments: dict = None, segment_order: list = None,
):
    """
    Render pipeline with self-healing retry loop.
    On failure: parse stderr → feed to LLM → get fixed code → retry.
    Up to MAX_RENDER_RETRIES total render attempts.
    """
    print(f"\n[{job_id}] === RENDER STARTED ===")
    render_status[job_id]["status"] = "rendering"
    render_status[job_id]["message"] = "Rendering video..."

    current_code = code
    render_job_id = None

    for render_attempt in range(1, MAX_RENDER_RETRIES + 1):
        print(f"[{job_id}] Render attempt {render_attempt}/{MAX_RENDER_RETRIES}")
        started_at = datetime.now()

        try:
            result = _run_manim(current_code, filename, job_id)
            render_duration = int((datetime.now() - started_at).total_seconds())

            render_data = {
                "code": current_code,
                "script_path": str(MANIM_SCRIPTS / f"{filename}.py"),
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration": render_duration,
                "started_at": started_at,
                "completed_at": datetime.now(),
            }

            # Check for video file FIRST — Manim may return exit code 1
            # for non-error warnings (e.g. cache full) even on success.
            video_path = find_video_file(filename)

            if video_path:
                # ── SUCCESS (video produced) ─────────────────────────────────
                if result.returncode != 0:
                    print(f"[{job_id}] [WARN] Manim exited with code {result.returncode} but video was produced — treating as success")
                
                final_video_path = str(video_path)
                
                if audio_segments and segment_order:
                    render_status[job_id]["message"] = "Merging audio and video..."
                    print(f"[{job_id}] Merging audio + video...")
                    narrated_output = str(OUTPUTS / f"{filename}_narrated.mp4")
                    final_video_path = merge_audio_video(
                        str(video_path), audio_segments, segment_order, narrated_output
                    )

                render_data["status"] = "done"
                render_data["video_path"] = final_video_path
                render_status[job_id]["status"] = "done"
                render_status[job_id]["video_file"] = Path(final_video_path).name
                render_status[job_id]["message"] = "Video ready!"
                print(f"[{job_id}] [OK] SUCCESS — {final_video_path}")

                if db and db.available and request_id:
                    render_job_id = db.save_render_job(request_id, attempt_id, render_data)
                    print(f"[DB] [OK] Saved render job: {render_job_id}")

                # Evaluate quality
                render_status[job_id]["message"] = "Evaluating quality..."
                evaluation = evaluate_with_gpt4(current_code, str(video_path), prompt, {
                    "status": "done",
                    "duration": render_duration,
                    "error": None,
                })
                if db and db.available and request_id and render_job_id:
                    db.save_ai_evaluation(request_id, render_job_id, evaluation)
                    score = evaluation.get("overall", 0)
                    print(f"[DB] [OK] Saved evaluation (score: {score}/100)")
                    if score >= 80:
                        print("[TRAINING] High-quality example candidate!")
                return  # done

            elif result.returncode == 0:
                # ── returncode=0 but file not found ──────────────────────────
                render_data["status"] = "error"
                render_data["error_type"] = "file_not_found"
                render_data["error_message"] = "Video file not found after render"
                render_status[job_id]["status"] = "error"
                render_status[job_id]["message"] = "Video file not found"
                if db and db.available and request_id:
                    db.save_render_job(request_id, None, render_data)
                return

            else:
                # ── RENDER FAILED (non-zero exit AND no video file) ──────────
                stderr = result.stderr
                print(f"[{job_id}] [ERR] Render failed (attempt {render_attempt})")
                print(f"[{job_id}] stderr (last 800 chars): {stderr[-800:]}")

                if db and db.available:
                    db.record_error_pattern({
                        "category": "runtime",
                        "signature": str(hash(stderr[-500:])),
                        "message": stderr[-500:],
                        "code_snippet": current_code[:200],
                        "root_cause": "Manim runtime error",
                        "fix": "Feed error back to LLM for targeted fix",
                    })

                if render_attempt < MAX_RENDER_RETRIES:
                    render_status[job_id]["message"] = f"Fixing render error (attempt {render_attempt})..."
                    print(f"[{job_id}] → Feeding error to LLM for fix...")
                    current_code = fix_render_error(current_code, stderr, prompt)
                    # Re-validate syntax before retrying
                    syn_ok, _ = validate_python_syntax(current_code)
                    if not syn_ok:
                        from algorithms.ai_functions import polish_manim_code as _polish
                        current_code = _polish(current_code)
                    current_code = ensure_scene_class(current_code)
                else:
                    # All retries used up
                    render_data["status"] = "error"
                    render_data["error_type"] = "runtime"
                    render_data["error_message"] = stderr[-2000:]
                    render_status[job_id]["status"] = "error"
                    render_status[job_id]["message"] = "Render failed after all retries"
                    if db and db.available and request_id:
                        db.save_render_job(request_id, None, render_data)

        except subprocess.TimeoutExpired:
            render_status[job_id]["status"] = "error"
            render_status[job_id]["message"] = "Rendering timed out"
            print(f"[{job_id}] [ERR] TIMEOUT")
            return

        except Exception as e:
            render_status[job_id]["status"] = "error"
            render_status[job_id]["message"] = f"Error: {str(e)}"
            print(f"[{job_id}] [ERR] Exception: {e}")
            return


def render_async(
    code: str, filename: str, job_id: str,
    request_id: str = None, prompt: str = "", attempt_id: str = None,
    audio_segments: dict = None, segment_order: list = None,
):
    t = threading.Thread(
        target=save_and_render,
        args=(code, filename, job_id, request_id, prompt, attempt_id, audio_segments, segment_order),
        daemon=True,
    )
    t.start()


# ═══════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
CORS(app)


@app.route("/", methods=["GET", "POST"])
def index():
    job_id = None
    error = None

    if request.method == "POST":
        prompt = request.form.get("prompt", "").strip()
        if not prompt:
            error = "Please enter a prompt."
            return render_template("index.html", error=error)

        try:
            job_id = str(uuid.uuid4())[:8]
            filename = f"video_{job_id}"

            safe_prompt = prompt.encode("ascii", "ignore").decode()
            print(f"\n{'#'*60}")
            print(f"[{job_id}] NEW REQUEST: {safe_prompt}")
            print(f"{'#'*60}\n")

            render_status[job_id] = {
                "status": "generating",
                "message": "Analyzing and planning...",
                "video_file": "",
            }

            code, attempts_log, request_id, attempt_id, a_segs, a_order = generate_and_validate_code(
                prompt, job_id, max_attempts=MAX_GENERATION_ATTEMPTS, voiceover=ENABLE_VOICEOVER
            )

            job_to_request[job_id] = {"request_id": request_id, "prompt": prompt}
            render_async(code, filename, job_id, request_id, prompt, attempt_id, a_segs, a_order)

        except Exception as e:
            error = f"Error: {str(e)}"
            print(f"[{job_id}] [ERR] ERROR: {error}")
            if job_id:
                render_status[job_id] = {"status": "error", "message": error, "video_file": ""}
            time.sleep(2)

    return render_template("index.html", job_id=job_id, error=error)


@app.route("/status/<job_id>")
def check_status(job_id):
    status = render_status.get(job_id, {"status": "unknown", "message": "Job not found"})
    return jsonify(status)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """JSON API for the Next.js frontend."""
    data = request.get_json(force=True)
    prompt = (data.get("prompt") or "").strip()
    use_voiceover = data.get("voiceover", ENABLE_VOICEOVER)

    if not prompt:
        return jsonify({"error": "Please enter a prompt."}), 400

    try:
        job_id = str(uuid.uuid4())[:8]
        filename = f"video_{job_id}"

        safe_prompt = prompt.encode("ascii", "ignore").decode()
        print(f"\n{'#'*60}")
        print(f"[{job_id}] NEW REQUEST (API) Voiceover={use_voiceover}: {safe_prompt}")
        print(f"{'#'*60}\n")

        render_status[job_id] = {
            "status": "generating",
            "message": "Analyzing and planning...",
            "video_file": "",
        }

        def background_generate():
            try:
                code, attempts_log, req_id, att_id, a_segs, a_order = generate_and_validate_code(
                    prompt, job_id, max_attempts=MAX_GENERATION_ATTEMPTS, voiceover=use_voiceover
                )
                job_to_request[job_id] = {"request_id": req_id, "prompt": prompt}
                render_async(code, filename, job_id, req_id, prompt, att_id, a_segs, a_order)
            except Exception as e:
                print(f"[{job_id}] [ERR] ERROR in background generation: {e}")
                render_status[job_id] = {"status": "error", "message": str(e), "video_file": ""}

        t = threading.Thread(target=background_generate, daemon=True)
        t.start()

        return jsonify({"job_id": job_id})
    except Exception as e:
        print(f"[API_ERR] Error initializing generate: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/prompts", methods=["GET"])
def api_prompts():
    """Returns random example prompts."""
    try:
        from training.questions import questions
        n = request.args.get('n', 4, type=int)
        
        # Don't fail if we request more than available
        k = min(n, len(questions))
        selected = random.sample(questions, k=k)
        return jsonify({"prompts": selected})
    except Exception as e:
        print(f"[API_ERR] Error fetching prompts: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/outputs/<path:filename>")
def download_file(filename):
    base = filename.replace(".mp4", "")
    video_path = find_video_file(base)
    if video_path and video_path.exists():
        return send_from_directory(video_path.parent, video_path.name)
    return "Video not found", 404


@app.route("/stats")
def stats():
    if not db or not db.available:
        return jsonify({"error": "Database not available"})
    try:
        with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(DISTINCT r.id) as total_requests,
                    COUNT(DISTINCT CASE WHEN rj.status = 'done' THEN rj.id END) as successful_renders,
                    ROUND(CAST(AVG(CASE WHEN rj.status='done' THEN ae.overall_score END) AS numeric), 1) as avg_quality_score,
                    COUNT(DISTINCT ep.id) as unique_error_patterns
                FROM requests r
                LEFT JOIN render_jobs rj ON r.id = rj.request_id
                LEFT JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                LEFT JOIN error_patterns ep ON true
            """)
            stats_data = dict(cur.fetchone())

            cur.execute("""
                SELECT domain, COUNT(*) as count
                FROM requests GROUP BY domain ORDER BY count DESC LIMIT 5
            """)
            domains = [dict(r) for r in cur.fetchall()]

        return jsonify({"stats": stats_data, "top_domains": domains, "database_enabled": True})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "database": db.available if db else False,
        "active_jobs": len([s for s in render_status.values() if s.get("status") in ("generating", "rendering")]),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("NIMA — Manim AI Generator")
    print("=" * 60)
    print(f"[OK] Model: {__import__('config').GENERATION_MODEL}")
    print(f"[OK] Fast model: {__import__('config').FAST_MODEL}")
    print(f"[OK] Database: {'ENABLED' if USE_DATABASE else 'DISABLED'}")
    print(f"[OK] Render retries: {MAX_RENDER_RETRIES} (with LLM error-fix between each)")
    print(f"[OK] RAG corpus: 25+ curated patterns")
    print(f"[OK] Review pass: consolidated (layout + API + pacing)")
    print("=" * 60)
    print("http://localhost:5000")
    print("Stats: http://localhost:5000/stats")
    print("=" * 60 + "\n")

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True, use_reloader=False)
