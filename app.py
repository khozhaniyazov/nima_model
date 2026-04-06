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

import os

# Set defaults before config import
os.environ.setdefault("DRAFT_PIPELINE", "false")
os.environ.setdefault("FAST_PIPELINE", "false")

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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    FAST_PIPELINE,
    DRAFT_PIPELINE,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_TIMEOUT,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW,
    CDN_BASE_URL,
    CDN_ENABLED,
    TTS_VOICE,
    WARMUP_PLANES,
)

# ── Algorithm imports ──────────────────────────────────────────────────────────
from algorithms.request_analysis import (
    analyze_request_type,
    create_animation_plan,
    create_narrated_plan,
    create_plan_json,
    expand_short_prompt,
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
from algorithms.code_digest import (
    ensure_scene_class,
    validate_names_and_imports,
    validate_python_syntax,
    validate_manim_code,
    check_code_quality,
    validate_latex_strings,
)
from algorithms.plan.schema import validate_plan_dict
from algorithms.template_registry import choose_template
from algorithms.overlap_detector import run_all_checks as detect_overlaps

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
client = OpenAI(
    api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL, timeout=OPENAI_TIMEOUT
)

print(f"[STARTUP] Manim scripts: {MANIM_SCRIPTS.absolute()}")
print(f"[STARTUP] Outputs:       {OUTPUTS.absolute()}")

render_status: Dict[str, dict] = {}
job_to_request: Dict[str, dict] = {}
_state_lock = threading.Lock()

# ── Rate Limiting ────────────────────────────────────────────────────────────
_rate_limit_storage: Dict[str, list] = {}
_rate_limit_lock = threading.Lock()


def check_rate_limit(client_id: str) -> tuple:
    """Check if client exceeds rate limit. Returns (allowed, retry_after)."""
    if not RATE_LIMIT_ENABLED:
        return True, 0

    import time

    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW

    with _rate_limit_lock:
        if client_id not in _rate_limit_storage:
            _rate_limit_storage[client_id] = []

        _rate_limit_storage[client_id] = [
            t for t in _rate_limit_storage[client_id] if t > window_start
        ]

        if len(_rate_limit_storage[client_id]) >= RATE_LIMIT_REQUESTS:
            oldest = min(_rate_limit_storage[client_id])
            retry_after = int(oldest - window_start) + 1
            return False, retry_after

        _rate_limit_storage[client_id].append(now)
        return True, 0


def get_job_status(job_id: str) -> Optional[dict]:
    with _state_lock:
        return render_status.get(job_id)


def set_job_status(job_id: str, status: dict) -> None:
    with _state_lock:
        render_status[job_id] = status


def get_job_request(job_id: str) -> Optional[dict]:
    with _state_lock:
        return job_to_request.get(job_id)


def set_job_request(job_id: str, request: dict) -> None:
    with _state_lock:
        job_to_request[job_id] = request


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
            (
                rid,
                prompt,
                user_id,
                analysis.get("topic"),
                analysis.get("domain"),
                analysis.get("complexity"),
                analysis.get("duration"),
                Json(analysis),
            ),
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
            (
                aid,
                request_id,
                attempt_data["attempt_number"],
                "gpt-4o",
                attempt_data.get("plan"),
                attempt_data["code"],
                len(attempt_data["code"]),
                attempt_data.get("critique"),
                attempt_data.get("improved_code"),
                attempt_data.get("syntax_valid", True),
                attempt_data.get("syntax_error"),
                attempt_data.get("structure_valid", True),
                Json(attempt_data.get("warnings", [])),
                attempt_data.get("generation_time_ms", 0),
            ),
        )
        return aid

    def save_render_job(
        self, request_id: str, attempt_id: Optional[str], render_data: dict
    ) -> str:
        jid = str(uuid.uuid4())
        self._exec(
            """INSERT INTO render_jobs
               (id, request_id, attempt_id, final_code, script_path,
                status, started_at, completed_at, render_duration_seconds,
                manim_stdout, manim_stderr, return_code, video_path,
                error_type, error_message)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                jid,
                request_id,
                attempt_id,
                render_data["code"],
                render_data.get("script_path"),
                render_data["status"],
                render_data.get("started_at"),
                render_data.get("completed_at"),
                render_data.get("duration"),
                render_data.get("stdout"),
                render_data.get("stderr"),
                render_data.get("return_code"),
                render_data.get("video_path"),
                render_data.get("error_type"),
                render_data.get("error_message"),
            ),
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
            (
                eid,
                request_id,
                render_job_id,
                "gpt-4o-mini",
                ev.get("visual_quality", 0),
                ev.get("educational_value", 0),
                ev.get("technical_accuracy", 0),
                ev.get("pacing_timing", 0),
                ev.get("clarity", 0),
                ev.get("engagement", 0),
                ev.get("overall", 0),
                ev.get("strengths"),
                ev.get("weaknesses"),
                Json(ev.get("issues", [])),
                ev.get("suggestions"),
                ev.get("predicted_satisfaction", 0),
                Json(ev),
            ),
        )
        return eid

    def get_best_examples(
        self, domain: str = None, topic: str = None, limit: int = 3
    ) -> list:
        q = """SELECT r.prompt, r.domain, r.topic, rj.final_code, ae.overall_score
               FROM requests r
               JOIN render_jobs rj ON r.id = rj.request_id
               JOIN ai_evaluations ae ON rj.id = ae.render_job_id
               WHERE rj.status = 'done' AND ae.overall_score >= 80"""
        params = []
        if domain:
            q += " AND r.domain = %s"
            params.append(domain)
        if topic:
            q += " AND (r.topic ILIKE %s OR r.prompt ILIKE %s)"
            params.extend([f"%{topic}%", f"%{topic}%"])
        q += " ORDER BY ae.overall_score DESC, r.created_at DESC LIMIT %s"
        params.append(limit)
        return self._exec(q, params, fetch="all") or []

    def get_error_patterns(self, limit: int = 5) -> list:
        return (
            self._exec(
                """SELECT error_category, root_cause, fix_description, occurrence_count
               FROM error_patterns
               WHERE NOT resolved
               ORDER BY occurrence_count DESC LIMIT %s""",
                (limit,),
                fetch="all",
            )
            or []
        )

    def record_error_pattern(self, error_data: dict):
        sig = error_data["signature"]
        existing = self._exec(
            "SELECT id, occurrence_count FROM error_patterns WHERE error_signature = %s",
            (sig,),
            fetch="one",
        )
        if existing:
            self._exec(
                "UPDATE error_patterns SET occurrence_count=occurrence_count+1, last_seen=NOW() WHERE id=%s",
                (existing["id"],),
            )
        else:
            self._exec(
                """INSERT INTO error_patterns
                   (id, error_category, error_signature, example_error_message,
                    example_code_snippet, root_cause, fix_description)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(uuid.uuid4()),
                    error_data["category"],
                    sig,
                    error_data["message"],
                    error_data.get("code_snippet"),
                    error_data.get("root_cause", "Unknown"),
                    error_data.get("fix", "Check syntax and API usage"),
                ),
            )

    def save_webhook(
        self, user_id: str, url: str, secret: str = None, events: list = None
    ) -> str:
        wid = str(uuid.uuid4())
        events = events or ["render.complete", "render.error"]
        self._exec(
            """INSERT INTO webhooks (id, user_id, url, secret, events)
               VALUES (%s, %s, %s, %s, %s)""",
            (wid, user_id, url, secret, events),
        )
        return wid

    def get_webhooks_for_event(self, event: str) -> list:
        rows = self._exec(
            """SELECT id, url, secret FROM webhooks
               WHERE active AND %s = ANY(events)""",
            (event,),
            fetch="all",
        )
        return rows or []

    def save_webhook_delivery(
        self,
        webhook_id: str,
        job_id: str,
        payload: dict,
        status: str,
        attempts: int,
        response_code: int = None,
        response_body: str = None,
    ) -> str:
        did = str(uuid.uuid4())
        self._exec(
            """INSERT INTO webhook_deliveries
               (id, webhook_id, job_id, payload, status, attempts,
                response_code, response_body)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                did,
                webhook_id,
                job_id,
                Json(payload),
                status,
                attempts,
                response_code,
                response_body,
            ),
        )
        return did

    def update_webhook_delivery(
        self,
        delivery_id: str,
        status: str,
        attempts: int,
        response_code: int = None,
        response_body: str = None,
    ):
        self._exec(
            """UPDATE webhook_deliveries
               SET status=%s, attempts=%s, response_code=%s,
                   response_body=%s, last_attempt_at=NOW()
               WHERE id=%s""",
            (status, attempts, response_code, response_body, delivery_id),
        )

    def save_api_key(
        self,
        user_id: str,
        key_hash: str,
        key_prefix: str,
        name: str,
        rate_limit: int = 60,
        daily_quota: int = None,
    ) -> str:
        kid = str(uuid.uuid4())
        self._exec(
            """INSERT INTO api_keys
               (id, user_id, key_hash, key_prefix, name, rate_limit, daily_quota)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (kid, user_id, key_hash, key_prefix, name, rate_limit, daily_quota),
        )
        return kid

    def check_api_key(self, key_hash: str) -> dict:
        row = self._exec(
            """SELECT * FROM api_keys
               WHERE key_hash=%s AND revoked_at IS NULL""",
            (key_hash,),
            fetch="one",
        )
        return dict(row) if row else None

    def verify_api_key(self, plain_key: str) -> dict:
        """Verify API key and return key record if valid."""
        if not plain_key or not plain_key.startswith("nima_"):
            return None
        key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
        return self.check_api_key(key_hash)

    def save_lti_platform(
        self,
        name: str,
        issuer: str,
        client_id: str,
        deployment_id: str,
        auth_endpoint: str,
        token_endpoint: str,
        jwks_endpoint: str,
    ) -> str:
        pid = str(uuid.uuid4())
        self._exec(
            """INSERT INTO lti_platforms
               (id, name, issuer, client_id, deployment_id, auth_endpoint,
                token_endpoint, jwks_endpoint)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (issuer) DO UPDATE SET
               name=EXCLUDED.name, client_id=EXCLUDED.client_id,
               deployment_id=EXCLUDED.deployment_id,
               auth_endpoint=EXCLUDED.auth_endpoint,
               token_endpoint=EXCLUDED.token_endpoint,
               jwks_endpoint=EXCLUDED.jwks_endpoint""",
            (
                pid,
                name,
                issuer,
                client_id,
                deployment_id,
                auth_endpoint,
                token_endpoint,
                jwks_endpoint,
            ),
        )
        return pid

    def get_lti_platform_by_issuer(self, issuer: str) -> dict:
        row = self._exec(
            "SELECT * FROM lti_platforms WHERE issuer=%s AND active=true",
            (issuer,),
            fetch="one",
        )
        return dict(row) if row else None

    def increment_api_usage(
        self,
        api_key_id: str,
        endpoint: str,
        method: str,
        status_code: int,
        response_time_ms: int,
    ):
        self._exec(
            """INSERT INTO api_usage
               (api_key_id, endpoint, method, status_code, response_time_ms)
               VALUES (%s,%s,%s,%s,%s)""",
            (api_key_id, endpoint, method, status_code, response_time_ms),
        )
        self._exec(
            """UPDATE api_keys
               SET requests_today = requests_today + 1, last_used_at = NOW()
               WHERE id = %s""",
            (api_key_id,),
        )


db = ManimDatabase(DB_CONNECTION_STRING) if USE_DATABASE else None


# ═══════════════════════════════════════════════════════════════════════════════
# CODE GENERATION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════


def generate_and_validate_code(
    prompt: str,
    job_id: str,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
    voiceover: bool = False,
    voice: str = None,
) -> Tuple[str, list, str, str, dict, list, bool]:
    """
    Full AI pipeline:
      analyze → plan → [voiceover] → generate → combined review → validate → polish
    Returns (code, attempts_log, request_id, attempt_id, audio_segments, segment_order, is_fast, analysis).
    """
    attempts_log = []
    request_id = None
    is_fast = FAST_PIPELINE or DRAFT_PIPELINE
    if is_fast:
        max_attempts = 1
    audio_segments = {}
    segment_order = []

    prompt = expand_short_prompt(prompt)

    # TIMING: Analysis
    t0 = time.time()
    render_status[job_id]["message"] = "Analyzing request..."
    analysis = analyze_request_type(prompt)
    print(f"[TIMING] Analysis: {time.time() - t0:.2f}s")
    attempts_log.append({"stage": "analysis", "data": analysis})

    if db and db.available:
        request_id = db.save_request(prompt, analysis)
        print(f"[DB] [OK] Saved request: {request_id}")

    # TIMING: Planning
    t1 = time.time()
    if voiceover:
        render_status[job_id]["message"] = "Creating narrated timeline..."
        plan = create_narrated_plan(prompt, analysis)
        try:
            parsed = json.loads(plan)
            segments = parsed.get("segments", [])
            segment_order = [s["id"] for s in segments]

            render_status[job_id]["message"] = "Generating narration audio..."
            audio_out_dir = OUTPUTS / "audio" / job_id
            audio_segments = generate_voiceover(
                segments, str(audio_out_dir), voice=voice
            )
        except Exception as e:
            print(
                f"[{job_id}] [ERR] Narration failed: {e}. Falling back to silent plan."
            )
            plan = create_animation_plan(prompt, analysis)
            voiceover = False
    else:
        render_status[job_id]["message"] = "Creating animation storyboard..."
        plan = create_animation_plan(prompt, analysis)

    print(f"[TIMING] Planning: {time.time() - t1:.2f}s")

    if is_fast and (analysis.get("domain") == "math") and (not voiceover):
        try:
            render_status[job_id]["message"] = "Creating plan JSON (deterministic)..."
            template_name = choose_template(prompt, analysis.get("domain"))
            if template_name:
                print(f"[{job_id}] [PLAN] Using template: {template_name}")
            plan_json = create_plan_json(prompt, analysis, template_name=template_name)
            if not plan_json.strip():
                raise ValueError("Empty plan JSON")
            plan_data = json.loads(plan_json)
            issues = validate_plan_dict(plan_data)
            if issues:
                raise ValueError("; ".join(issues))
            plan_compiled_code = compile_plan(plan_data)
            attempts_log.append(
                {
                    "stage": "plan_json",
                    "success": True,
                    "template": template_name,
                    "fast": True,
                }
            )
        except Exception as e:
            print(f"[{job_id}] [PLAN] [ERR] Fast plan compiler fallback: {e}")
            plan_compiled_code = None

    else:
        # ── Plan-first deterministic compilation (hybrid mode) ───────────────────
        plan_compiled_code = None
        use_plan_compiler = (analysis.get("domain") == "math") and (not voiceover)
        if use_plan_compiler:
            try:
                render_status[job_id]["message"] = (
                    "Creating plan JSON (deterministic)..."
                )
                template_name = choose_template(prompt, analysis.get("domain"))
                if template_name:
                    print(f"[{job_id}] [PLAN] Using template: {template_name}")
                plan_json = create_plan_json(
                    prompt, analysis, template_name=template_name
                )
                plan_data = json.loads(plan_json)
                issues = validate_plan_dict(plan_data)
                if issues:
                    raise ValueError("; ".join(issues))
                plan_compiled_code = compile_plan(plan_data)
                attempts_log.append(
                    {"stage": "plan_json", "success": True, "template": template_name}
                )
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
                    attempts_log.append(
                        {
                            "stage": "quality",
                            "success": quality_passes,
                            "feedback": quality_feedback,
                        }
                    )

                    # Block on critical errors (MathTex indexing, forbidden imports, etc.)
                    critical_errors = [
                        w for w in quality_feedback if w.startswith("[ERR]")
                    ]
                    if critical_errors:
                        print(
                            f"[{job_id}] [QUALITY] Critical errors detected, falling back to LLM path:"
                        )
                        for err in critical_errors:
                            print(f"  {err}")
                        # Fall through to LLM generation path which can fix these
                    else:
                        # Overlap / scene-hygiene detection (non-blocking here)
                        render_status[job_id]["message"] = (
                            "Checking for layout overlaps..."
                        )
                        overlap_warnings = detect_overlaps(code)
                        if overlap_warnings:
                            print(
                                f"[{job_id}] [OVERLAP] {len(overlap_warnings)} issues detected in plan code"
                            )
                            for w in overlap_warnings:
                                print(f"  {w}")
                            attempts_log.append(
                                {"stage": "overlap_check", "warnings": overlap_warnings}
                            )

                        return (
                            code,
                            attempts_log,
                            request_id,
                            None,
                            audio_segments,
                            segment_order,
                            is_fast,
                            analysis,
                        )

    for attempt in range(1, max_attempts + 1):
        print(f"\n[{job_id}] {'=' * 50}")
        print(f"[{job_id}] GENERATION ATTEMPT {attempt}/{max_attempts}")
        print(f"[{job_id}] {'=' * 50}\n")
        attempt_start = time.time()

        # TIMING: Code generation
        t_gen = time.time()
        # 1. Generate
        render_status[job_id]["message"] = f"Generating code (attempt {attempt})..."

        # ── Check prompt cache ──────────────────────────────────────────
        try:
            from cache import prompt_cache

            cached_result = prompt_cache.check(
                prompt,
                domain=analysis.get("domain", ""),
                voiceover=bool(voiceover),
                extra={"plan": str(plan)[:500] if plan else ""},
            )
            if cached_result:
                print(f"[CACHE] Prompt cache HIT — skipping AI generation")
                code = cached_result.get("code", "")
                attempts_log.extend(cached_result.get("attempts_log", []))
                print(f"[TIMING] LLM generation: 0.00s (cache hit)")
            else:
                code = generate_manim_code(
                    prompt,
                    analysis,
                    plan,
                    attempt,
                    db=db,
                    segment_durations=audio_segments if voiceover else None,
                )
                # Store in cache
                prompt_cache.store(
                    prompt,
                    {"code": code, "attempts_log": attempts_log.copy()},
                    domain=analysis.get("domain", ""),
                    voiceover=bool(voiceover),
                    extra={"plan": str(plan)[:500] if plan else ""},
                )
        except Exception as e:
            print(f"[CACHE] Prompt cache error: {e}")
            code = generate_manim_code(
                prompt,
                analysis,
                plan,
                attempt,
                db=db,
                segment_durations=audio_segments if voiceover else None,
            )
        print(f"[TIMING] LLM generation: {time.time() - t_gen:.2f}s")
        attempts_log.append(
            {"attempt": attempt, "stage": "generation", "success": True}
        )

        # 2. Combined review - check for critical errors
        # Skip expensive quality checks in FAST/DRAFT_PIPELINE
        is_fast = FAST_PIPELINE or DRAFT_PIPELINE
        if is_fast:
            quality_passes, quality_feedback = True, []
            has_critical_errors = False
        else:
            quality_passes, quality_feedback = check_code_quality(code)
            has_critical_errors = any(w.startswith("[ERR]") for w in quality_feedback)

        # 2b. LaTeX validation for math domain - skip in FAST/DRAFT_PIPELINE
        latex_valid, latex_issues = True, []
        if not is_fast and analysis.get("domain") == "math":
            latex_valid, latex_issues = validate_latex_strings(code)
            if not latex_valid:
                print(f"[{job_id}] [LATEX] LaTeX issues detected: {latex_issues}")
                latex_note = "\n".join(latex_issues)
                code = review_and_fix(
                    code, f"{prompt}\n\n[LATEX ERRORS TO FIX]:\n{latex_note}", analysis
                )
                latex_valid, latex_issues = validate_latex_strings(code)
                if not latex_valid:
                    has_critical_errors = True

        force_review = has_critical_errors

        # In FAST/DRAFT_PIPELINE, skip review entirely unless there are critical errors
        if is_fast:
            if has_critical_errors:
                render_status[job_id]["message"] = "Fixing critical errors..."
                error_note = "\n".join(
                    [w for w in quality_feedback if w.startswith("[ERR]")]
                )
                code = review_and_fix(
                    code,
                    f"{prompt}\n\n[CRITICAL ERRORS TO FIX]:\n{error_note}",
                    analysis,
                )
            else:
                attempts_log.append(
                    {
                        "attempt": attempt,
                        "stage": "review",
                        "skipped": True,
                        "reason": "fast_pipeline",
                    }
                )

        # 3. Security / safety validation - skip in FAST/DRAFT_PIPELINE
        if not is_fast:
            render_status[job_id]["message"] = "Validating code safety..."
            is_safe, safety_issues = validate_names_and_imports(code)
            if not is_safe:
                print(
                    f"[{job_id}] [SECURITY] Unsafe patterns detected: {safety_issues}"
                )
                # Feed safety violations into the review pass to auto-fix them
                safety_note = "\n".join(safety_issues)
                code = review_and_fix(
                    code,
                    f"{prompt}\n\n[SECURITY VIOLATIONS TO FIX]:\n{safety_note}",
                    analysis,
                )
                is_safe, safety_issues = validate_names_and_imports(code)
                if not is_safe and attempt < max_attempts:
                    continue
        else:
            is_safe, safety_issues = True, []

        # 4. Syntax validation
        render_status[job_id]["message"] = "Validating syntax..."
        syntax_valid, syntax_error = validate_python_syntax(code)
        if not syntax_valid:
            print(f"[{job_id}] [ERR] Syntax error: {syntax_error}")
            attempts_log.append(
                {
                    "attempt": attempt,
                    "stage": "syntax",
                    "success": False,
                    "error": syntax_error,
                }
            )
            if db and db.available:
                db.record_error_pattern(
                    {
                        "category": "syntax",
                        "signature": str(hash(syntax_error)),
                        "message": syntax_error,
                        "code_snippet": code[:200],
                    }
                )
            if not is_fast:
                code = polish_manim_code(code)
                syntax_valid, syntax_error = validate_python_syntax(code)
                if not syntax_valid:
                    if attempt < max_attempts:
                        continue
                    raise Exception(f"Syntax error could not be fixed: {syntax_error}")
            else:
                if attempt < max_attempts:
                    continue
                raise Exception(f"Syntax error: {syntax_error}")

        attempts_log.append({"attempt": attempt, "stage": "syntax", "success": True})

        # 4. Scene class / structure
        code = ensure_scene_class(code)
        structure_valid, structure_error = validate_manim_code(code)
        if not structure_valid:
            if attempt < max_attempts:
                if not is_fast:
                    code = polish_manim_code(code)
                continue
            raise Exception(f"Structure error: {structure_error}")

        attempts_log.append({"attempt": attempt, "stage": "structure", "success": True})

        # 5. Quality warnings (non-blocking) - skip in FAST/DRAFT_PIPELINE
        if not is_fast:
            quality_passes, quality_feedback = check_code_quality(code)
            attempts_log.append(
                {
                    "attempt": attempt,
                    "stage": "quality",
                    "success": quality_passes,
                    "feedback": quality_feedback,
                }
            )
        else:
            quality_passes, quality_feedback = True, []

        # 6. Overlap detection - skip in FAST/DRAFT_PIPELINE
        if not is_fast:
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
                    analysis,
                )
                code = ensure_scene_class(code)
                # Re-check (don't loop — one repair pass is enough)
                remaining = detect_overlaps(code)
                if remaining:
                    print(
                        f"[{job_id}] [OVERLAP] {len(remaining)} issues remain after fix attempt"
                    )
                    quality_feedback.extend(remaining)
                else:
                    print(f"[{job_id}] [OVERLAP] All issues resolved")

            attempts_log.append(
                {
                    "attempt": attempt,
                    "stage": "overlap_fix",
                    "warnings": overlap_warnings,
                    "remaining": len(overlap_warnings) if overlap_warnings else 0,
                }
            )
        else:
            # FAST/DRAFT_PIPELINE: skip overlap detection
            overlap_warnings = []
            attempts_log.append(
                {"attempt": attempt, "stage": "overlap_fix", "skipped": True}
            )

        attempt_time = int((time.time() - attempt_start) * 1000)
        attempt_id = None
        if db and db.available and request_id:
            attempt_id = db.save_generation_attempt(
                request_id,
                {
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
                },
            )
            print(f"[DB] [OK] Saved attempt: {attempt_id}")

        print(f"[TIMING] Total code generation: {time.time() - t0:.2f}s")
        return (
            code,
            attempts_log,
            request_id,
            attempt_id,
            audio_segments,
            segment_order,
            is_fast,
            analysis,
        )

    raise Exception("All generation attempts failed.")


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMING GENERATION PIPELINE (Phase 13)
# ═══════════════════════════════════════════════════════════════════════════════


def stream_generate_and_render(
    prompt: str,
    job_id: str,
    analysis: dict = None,
    voiceover: bool = False,
    voice: str = None,
    visual_template: str = None,
) -> Tuple[str, List[dict], dict]:
    """
    Streaming scene-by-scene generation with parallel render-while-generate.

    This replaces bulk generation (which times out on 10K+ chars) with:
      1. Split plan into individual scenes
      2. Generate scene N with narrative context
      3. Render scene N while generating scene N+1 (parallel)
      4. Scene-level retry on failure (not full pipeline restart)
      5. Stitch rendered scenes into final video

    Args:
        prompt: User's animation request
        job_id: Job identifier
        analysis: Optional pre-computed analysis dict
        voiceover: Whether to include voiceover
        voice: TTS voice preset

    Returns:
        Tuple of (final_video_path, scene_results, final_context)
        scene_results: List of {scene_num, status, video_path, error}
        final_context: NarrativeContext after all scenes
    """
    from algorithms.streaming import (
        NarrativeContext,
        apply_visual_template,
        choose_visual_template,
        split_plan_into_scenes,
        stream_render_scenes,
        stitch_scenes,
        STREAM_SCENE_TIMEOUT,
        STREAM_MAX_SCENES,
        STREAM_SCENE_RETRIES,
    )
    from algorithms.tts import generate_voiceover, merge_audio_video
    from algorithms.request_analysis import analyze_request_type
    from algorithms.plan.schema import validate_plan_dict
    import json

    print(f"\n[{job_id}] === STREAMING PIPELINE STARTED ===")

    # ── Step 1: Analyze request (if not provided) ────────────────────────
    if analysis is None:
        render_status[job_id]["message"] = "Analyzing request (streaming)..."
        analysis = analyze_request_type(prompt)
        print(
            f"[STREAM] Domain: {analysis.get('domain')}, Duration: {analysis.get('duration')}s"
        )

    # ── Step 2: Create animation plan ─────────────────────────────────
    render_status[job_id]["message"] = "Creating animation plan..."
    from algorithms.request_analysis import create_narrated_plan

    plan = create_narrated_plan(prompt, analysis)
    print(f"[STREAM] Plan created ({len(plan)} chars)")

    # ── Step 3: Parse plan into scenes ─────────────────────────────────
    render_status[job_id]["message"] = "Splitting into scenes..."
    try:
        plan_data = json.loads(plan)
    except (json.JSONDecodeError, TypeError):
        # Fallback: treat as single scene
        plan_data = {
            "description": plan,
            "scenes": [{"id": "scene_0", "description": plan}],
        }

    scenes = split_plan_into_scenes(plan_data, max_scenes=STREAM_MAX_SCENES)
    print(f"[STREAM] Split into {len(scenes)} scenes")

    if not scenes:
        raise ValueError("Could not split plan into scenes — empty scene list")

    # ── Step 4: Initialize narrative context ───────────────────────────
    narrative_context = NarrativeContext.from_analysis(prompt, analysis)
    visual_template = choose_visual_template(prompt, analysis, visual_template)
    narrative_context = apply_visual_template(narrative_context, visual_template)
    print(f"[STREAM] Visual template: {visual_template}")
    print(
        f"[STREAM] NarrativeContext initialized for {narrative_context.domain} domain"
    )

    # ── Step 5: Generate and render scenes in streaming pipeline ───────
    render_status[job_id]["message"] = f"Generating {len(scenes)} scenes..."
    filename = f"video_{job_id}"

    video_paths, final_context, errors, completed_renders = stream_render_scenes(
        scenes=scenes,
        job_id=job_id,
        narrative_context=narrative_context,
        filename=filename,
        max_scene_retries=STREAM_SCENE_RETRIES,
    )

    print(
        f"[STREAM] Render results: {len(video_paths)} successful, {len(errors)} failed"
    )

    # ── Optional: Scene-level TTS generation and mux ───────────────────
    scene_tts = {}  # scene_num -> {path, duration, error}
    print(f"[STREAM] Voiceover={voiceover}")
    if voiceover:
        render_status[job_id]["message"] = "Generating scene voiceovers..."
        tts_segments = []
        for i, seg in enumerate(plan_data.get("segments", [])):
            tts_segments.append(
                {
                    "id": f"scene_{i}",
                    "narration": seg.get("narration", "").strip(),
                    "estimated_duration": seg.get("estimated_duration", 8),
                }
            )
        tts_dir = str(OUTPUTS / f"tts_{job_id}")
        try:
            tts_results = generate_voiceover(tts_segments, tts_dir, voice=voice)
            scene_tts = {
                int(k.split("_")[-1]): v for k, v in tts_results.items() if "_" in k
            }
        except Exception as e:
            print(f"[STREAM] [WARN] Scene TTS generation failed: {e}")
            scene_tts = {}

        # Mux per-scene audio where available
        for scene_num, payload in list(completed_renders.items()):
            video_path, success, err = payload
            if not success or not video_path:
                continue
            tts_payload = scene_tts.get(scene_num)
            if not tts_payload or not tts_payload.get("path"):
                continue
            narrated_scene = str(
                Path(video_path).with_name(f"{Path(video_path).stem}_tts.mp4")
            )
            merged = merge_audio_video(
                video_path,
                {f"scene_{scene_num}": tts_payload},
                [f"scene_{scene_num}"],
                narrated_scene,
            )
            if merged and Path(merged).exists():
                completed_renders[scene_num] = (merged, True, "")

        # Rebuild ordered video_paths from completed_renders after mux
        video_paths = []
        for scene_num in sorted(completed_renders.keys()):
            vp, success, _ = completed_renders[scene_num]
            if success and vp:
                video_paths.append(vp)

    # ── Step 6: Stitch scenes into final video ─────────────────────────
    if len(video_paths) == 0:
        raise RuntimeError(f"All scenes failed to render: {errors}")

    render_status[job_id]["message"] = "Stitching scenes..."
    final_output = str(OUTPUTS / f"{filename}_stream.mp4")

    if len(video_paths) == 1:
        # Single scene — use directly
        import shutil

        shutil.copy2(video_paths[0], final_output)
        print(f"[STREAM] Single scene output: {final_output}")
    else:
        # Multiple scenes — stitch with ffmpeg
        try:
            final_output = stitch_scenes(video_paths, final_output)
            print(f"[STREAM] Stitched output: {final_output}")
        except RuntimeError as e:
            print(f"[STREAM] Stitch failed: {e} — using first scene")
            final_output = video_paths[0]

    # ── Step 7: Build scene results summary + repetition analysis ──────
    repetition_pairs = []
    if plan_data.get("segments"):
        texts = [s.get("narration", "") for s in plan_data.get("segments", [])]

        def _tok(t):
            import re

            stop = {
                "the",
                "a",
                "an",
                "and",
                "or",
                "to",
                "of",
                "in",
                "on",
                "for",
                "with",
                "this",
                "that",
                "is",
                "are",
            }
            ws = re.findall(r"[a-zA-Z0-9]+", (t or "").lower())
            return {w for w in ws if w not in stop and len(w) > 2}

        def _jac(a, b):
            if not a or not b:
                return 0.0
            return len(a & b) / max(1, len(a | b))

        toks = [_tok(t) for t in texts]
        for i in range(len(toks)):
            for j in range(i + 1, len(toks)):
                score = _jac(toks[i], toks[j])
                if score >= 0.75:
                    repetition_pairs.append(
                        {"scene_i": i, "scene_j": j, "score": round(score, 3)}
                    )

    scene_results = []
    for i, scene in enumerate(scenes):
        status = "done" if i < len(video_paths) else "failed"
        error_info = None
        if i >= len(video_paths) and i < len(errors):
            error_info = errors[i].get("error", "Unknown error")

        scene_results.append(
            {
                "scene_num": i,
                "scene_id": scene.get("scene_id", f"scene_{i}"),
                "description": scene.get("description", "")[:100],
                "status": status,
                "video_path": video_paths[i] if i < len(video_paths) else None,
                "error": error_info,
            }
        )

    # ── Step 8: Update job status ──────────────────────────────────────
    failed_count = sum(1 for r in scene_results if r["status"] == "failed")
    if failed_count > 0:
        render_status[job_id]["status"] = (
            "done"  # Pipeline completed, but some scenes failed
        )
        render_status[job_id]["message"] = (
            f"Done ({len(video_paths)}/{len(scenes)} scenes)"
        )
        render_status[job_id]["partial"] = True
    else:
        render_status[job_id]["status"] = "done"
        render_status[job_id]["message"] = "Video ready!"
        render_status[job_id]["partial"] = False

    render_status[job_id]["video_file"] = Path(final_output).name
    render_status[job_id]["scene_results"] = scene_results
    render_status[job_id]["repetition_pairs"] = repetition_pairs

    # Persist per-job scene stats for later analysis
    try:
        reports_dir = OUTPUTS / "stream_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / f"{job_id}.json"
        report = {
            "job_id": job_id,
            "prompt": prompt,
            "domain": analysis.get("domain"),
            "duration_target": analysis.get("duration"),
            "voiceover": voiceover,
            "visual_template": visual_template,
            "planned_scenes": len(scenes),
            "rendered_scenes": len(video_paths),
            "failed_scenes": failed_count,
            "errors": errors,
            "scene_results": scene_results,
            "repetition_pairs": repetition_pairs,
            "video_file": str(final_output),
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        render_status[job_id]["report_file"] = str(report_path)
    except Exception as e:
        print(f"[{job_id}] [WARN] Could not persist stream report: {e}")

    print(f"[{job_id}] === STREAMING PIPELINE COMPLETE ===")
    print(f"[{job_id}] Output: {final_output}")
    print(f"[{job_id}] Scenes: {len(scene_results)}, Failed: {failed_count}")
    if repetition_pairs:
        print(
            f"[{job_id}] [REPEAT] potential repeated narration pairs: {repetition_pairs}"
        )

    return final_output, scene_results, final_context


def stream_render_async(
    prompt: str,
    job_id: str,
    analysis: dict = None,
    voiceover: bool = False,
    voice: str = None,
    visual_template: str = None,
):
    """Non-blocking wrapper for stream_generate_and_render."""
    t = threading.Thread(
        target=stream_generate_and_render,
        args=(prompt, job_id, analysis, voiceover, voice, visual_template),
        daemon=True,
    )
    t.start()


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
    now = time.time()
    for mp4 in OUTPUTS.rglob(f"{filename}*.mp4"):
        # Reject files older than 5 minutes as stale
        if now - mp4.stat().st_mtime < 300:
            return mp4
    return None


class VideoStorage:
    """Organized video storage with metadata tracking."""

    def __init__(self, outputs_dir: Path):
        self.outputs_dir = outputs_dir

    def _get_date_dir(self) -> str:
        """Return YYYY-MM-DD format for today's date."""
        return datetime.now().strftime("%Y-%m-%d")

    def _get_domain_dir(self, domain: str) -> str:
        """Return sanitized domain directory name."""
        return domain.lower().replace(" ", "_").replace("/", "_")

    def get_organized_path(self, job_id: str, domain: str = "general") -> Path:
        """
        Get organized storage path: outputs/{date}/{domain}/{job_id}.mp4
        Example: outputs/2026-04-05/math/sj8k2d.mp4
        """
        date_dir = self._get_date_dir()
        domain_dir = self._get_domain_dir(domain)
        return self.outputs_dir / date_dir / domain_dir / f"{job_id}.mp4"

    def organize_video(
        self, source_path: Path, job_id: str, domain: str = "general"
    ) -> Path:
        """
        Move/copy video to organized location.
        Creates directories as needed.
        """
        dest = self.get_organized_path(job_id, domain)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if source_path.resolve() != dest.resolve():
            import shutil

            shutil.copy2(source_path, dest)

        return dest

    def get_video_info(self, job_id: str, domain: str = "general") -> dict:
        """Return video metadata dict for a given job_id."""
        organized_path = self.get_organized_path(job_id, domain)

        if not organized_path.exists():
            return None

        stat = organized_path.stat()
        return {
            "job_id": job_id,
            "organized_path": str(organized_path),
            "file_size_bytes": stat.st_size,
            "exists": True,
        }


# Initialize global VideoStorage instance
video_storage = VideoStorage(OUTPUTS)


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOK DELIVERY
# ═══════════════════════════════════════════════════════════════════════════════


def deliver_webhook_background(
    webhook_id: str,
    url: str,
    secret: str,
    job_id: str,
    payload: dict,
    max_retries: int = 3,
):
    """Non-blocking webhook delivery with exponential backoff retry."""
    import requests
    import hmac
    import hashlib
    import time
    import json as _json

    headers = {"Content-Type": "application/json"}
    if secret:
        signature = hmac.new(
            secret.encode(), _json.dumps(payload).encode(), hashlib.sha256
        ).hexdigest()
        headers["X-Webhook-Signature"] = signature

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code in (200, 201, 204):
                if db and db.available:
                    try:
                        db.save_webhook_delivery(
                            webhook_id,
                            job_id,
                            payload,
                            "delivered",
                            attempt,
                            response.status_code,
                            response.text[:500],
                        )
                    except Exception:
                        pass
                print(f"[WEBHOOK] Delivered to {url} for job {job_id}")
                return

            if attempt < max_retries:
                wait_times = [1, 5, 30]
                time.sleep(wait_times[attempt - 1])
        except Exception as e:
            if attempt < max_retries:
                wait_times = [1, 5, 30]
                time.sleep(wait_times[attempt - 1])
            print(f"[WEBHOOK] Failed: {e}")

    if db and db.available:
        try:
            db.save_webhook_delivery(
                webhook_id, job_id, payload, "failed", max_retries, None, str(e)
            )
        except Exception:
            pass
    print(f"[WEBHOOK] All retries exhausted for job {job_id}")


def trigger_webhooks(job_id: str, event: str, payload: dict):
    """Trigger all webhooks subscribed to event for job."""
    if not db or not db.available:
        return
    try:
        webhooks = db.get_webhooks_for_event(event)
        for wh in webhooks:
            if wh.get("active"):
                import threading

                t = threading.Thread(
                    target=deliver_webhook_background,
                    args=(
                        str(wh["id"]),
                        wh["url"],
                        wh.get("secret", ""),
                        job_id,
                        payload,
                    ),
                    daemon=True,
                )
                t.start()
    except Exception as e:
        print(f"[WEBHOOK] Trigger error: {e}")


def check_batch_completion(batch_id: str):
    """Check if all jobs in a batch are done/failed and trigger batch webhook."""
    if not batch_id:
        return

    batch_jobs = [
        (jid, status)
        for jid, status in render_status.items()
        if status.get("batch_id") == batch_id
    ]

    if not batch_jobs:
        return

    total = len(batch_jobs)
    completed = sum(1 for _, s in batch_jobs if s.get("status") == "done")
    failed = sum(1 for _, s in batch_jobs if s.get("status") == "error")

    if (completed + failed) >= total:
        status = "completed_with_errors" if failed > 0 else "completed"
        payload = {
            "event": "batch.complete",
            "batch_id": batch_id,
            "total": total,
            "completed": completed,
            "failed": failed,
            "status": status,
            "timestamp": datetime.now().isoformat(),
        }

        if db and db.available:
            batch = db._exec(
                "SELECT webhook_url FROM batches WHERE id=%s", (batch_id,), fetch="one"
            )
            if batch and batch.get("webhook_url"):
                deliver_webhook_background(
                    None, batch["webhook_url"], None, batch_id, payload
                )


def validate_in_parallel(code: str, job_id: str) -> list:
    """Run validation checks in parallel threads."""
    from algorithms.code_digest import (
        validate_python_syntax,
        validate_names_and_imports,
        validate_no_forbidden_calls,
    )
    from algorithms.ai_functions import validate_latex_strings

    warnings = []

    def run_check(name: str, fn, *args, **kwargs):
        try:
            result = fn(*args, **kwargs)
            if result and result is not True:
                return (name, result)
            return (name, None)
        except Exception as e:
            return (name, [f"{name} check error: {e}"])

    checks = [
        ("syntax", validate_python_syntax, code),
        ("imports", validate_names_and_imports, code),
        ("forbidden", validate_no_forbidden_calls, code),
    ]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fn, *args): name for name, fn, *args in checks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                if result and result[1]:
                    warnings.extend(result[1])
            except Exception as e:
                print(f"[{job_id}] [VALIDATION] {name} error: {e}")

    return warnings


def _run_manim(
    code: str, filename: str, job_id: str, is_fast: bool = False
) -> subprocess.CompletedProcess:
    """Write the script and run manim. Returns the CompletedProcess."""
    script_path = MANIM_SCRIPTS / f"{filename}.py"
    with open(script_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(code)

    # Clean up old exact matches first so we don't return stale files
    for old_file in OUTPUTS.rglob(f"{filename}*.mp4"):
        try:
            old_file.unlink()
        except OSError:
            pass

    # Build render command based on pipeline mode
    if DRAFT_PIPELINE:
        # Ultra-fast draft mode: lowest quality, smallest output
        quality_flag = "-qk"  # Keep edges (lowest)
        fps = "10"
    elif is_fast:
        quality_flag = "-ql"  # Low quality
        fps = "15"
    else:
        quality_flag = "-ql"  # Default to low for speed
        fps = "30"

    cmd = [
        "manim",
        str(script_path),
        "GeneratedScene",
        quality_flag,
        "--format=mp4",
        "--media_dir",
        str(OUTPUTS),
        "--output_file",
        f"{filename}.mp4",
        "--disable_caching",
        "--fps",
        fps,
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS
    )


def save_and_render(
    code: str,
    filename: str,
    job_id: str,
    request_id: str = None,
    prompt: str = "",
    attempt_id: str = None,
    audio_segments: dict = None,
    segment_order: list = None,
    is_fast: bool = False,
    analysis: dict = None,
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

    # ── Check render cache ──────────────────────────────────────────────
    try:
        from cache import render_cache

        cached_video = render_cache.check(code)
        if cached_video and cached_video.exists():
            print(f"[CACHE] Render cache HIT — skipping manim")
            video_path = cached_video
            final_video_path = str(video_path)
            render_status[job_id]["status"] = "done"
            render_status[job_id]["video_file"] = video_path.name
            render_status[job_id]["message"] = "Video ready (cached)!"
            print(f"[{job_id}] [CACHE] [OK] SUCCESS — {final_video_path}")

            batch_id = render_status[job_id].get("batch_id")
            trigger_webhooks(
                job_id,
                "render.complete",
                {
                    "event": "render.complete",
                    "job_id": job_id,
                    "batch_id": batch_id,
                    "status": "done",
                    "video_url": f"/outputs/{video_path.name}",
                    "timestamp": datetime.now().isoformat(),
                },
            )
            return
    except Exception as e:
        print(f"[CACHE] Render cache check failed: {e}")

    render_retries = 1 if is_fast else MAX_RENDER_RETRIES

    for render_attempt in range(1, render_retries + 1):
        print(f"[{job_id}] Render attempt {render_attempt}/{MAX_RENDER_RETRIES}")
        started_at = datetime.now()

        # TIMING: Manim render
        t_render = time.time()
        try:
            result = _run_manim(current_code, filename, job_id, is_fast=is_fast)
            render_duration = int((datetime.now() - started_at).total_seconds())
            print(f"[TIMING] Manim render: {time.time() - t_render:.2f}s")

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

            # Race condition fix: poll if returncode=0 but file not found yet
            if not video_path and result.returncode == 0:
                for poll_attempt in range(3):
                    time.sleep(1)
                    video_path = find_video_file(filename)
                    if video_path:
                        break

            if video_path:
                # ── SUCCESS (video produced) ─────────────────────────────────
                if result.returncode != 0:
                    print(
                        f"[{job_id}] [WARN] Manim exited with code {result.returncode} but video was produced — treating as success"
                    )

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
                    render_job_id = db.save_render_job(
                        request_id, attempt_id, render_data
                    )
                    print(f"[DB] [OK] Saved render job: {render_job_id}")

                # ── Store in render cache ──────────────────────────────────
                try:
                    from cache import render_cache

                    render_cache.store(current_code, Path(final_video_path))
                    print(f"[CACHE] Stored render in cache")
                except Exception as e:
                    print(f"[CACHE] Store failed: {e}")

                # Evaluate quality
                render_status[job_id]["message"] = "Evaluating quality..."
                evaluation = evaluate_with_gpt4(
                    current_code,
                    str(video_path),
                    prompt,
                    {
                        "status": "done",
                        "duration": render_duration,
                        "error": None,
                    },
                )
                if db and db.available and request_id and render_job_id:
                    db.save_ai_evaluation(request_id, render_job_id, evaluation)
                    score = evaluation.get("overall", 0)
                    print(f"[DB] [OK] Saved evaluation (score: {score}/100)")
                    if score >= 80:
                        print("[TRAINING] High-quality example candidate!")

                # Trigger webhooks on success
                batch_id = render_status[job_id].get("batch_id")
                trigger_webhooks(
                    job_id,
                    "render.complete",
                    {
                        "event": "render.complete",
                        "job_id": job_id,
                        "batch_id": batch_id,
                        "status": "done",
                        "video_url": f"/outputs/{Path(final_video_path).name}",
                        "timestamp": datetime.now().isoformat(),
                    },
                )
                return  # done

            elif result.returncode == 0 and not video_path:
                # ── returncode=0 but file not found (after polling) ───────────
                render_data["status"] = "error"
                render_data["error_type"] = "file_not_found_after_retry"
                render_data["error_message"] = (
                    "Video file not found after render and poll retry"
                )
                render_status[job_id]["status"] = "error"
                render_status[job_id]["message"] = "Video file not found"
                if db and db.available and request_id:
                    db.save_render_job(request_id, None, render_data)

                batch_id = render_status[job_id].get("batch_id")
                trigger_webhooks(
                    job_id,
                    "render.error",
                    {
                        "event": "render.error",
                        "job_id": job_id,
                        "batch_id": batch_id,
                        "status": "error",
                        "error": "Video file not found after render",
                        "timestamp": datetime.now().isoformat(),
                    },
                )
                return

            else:
                # ── RENDER FAILED (non-zero exit AND no video file) ──────────
                stderr = result.stderr
                print(f"[{job_id}] [ERR] Render failed (attempt {render_attempt})")
                print(f"[{job_id}] stderr (last 800 chars): {stderr[-800:]}")

                if db and db.available:
                    try:
                        db.record_error_pattern(
                            {
                                "category": "runtime",
                                "signature": str(hash(stderr[-500:])),
                                "message": stderr[-500:],
                                "code_snippet": current_code[:200],
                                "root_cause": "Manim runtime error",
                                "fix": "Feed error back to LLM for targeted fix",
                            }
                        )
                    except Exception as e:
                        print(
                            f"[{job_id}] [DB] [ERR] Failed to record error pattern: {e}",
                            flush=True,
                        )
                else:
                    print(
                        f"[{job_id}] [DB] [WARN] Database unavailable — error pattern not recorded",
                        flush=True,
                    )

                if render_attempt < render_retries:
                    render_status[job_id]["message"] = (
                        f"Fixing render error (attempt {render_attempt})..."
                    )
                    print(f"[{job_id}] → Feeding error to LLM for fix...")
                    current_code = fix_render_error(current_code, stderr, prompt)

                    # Post-fix validation: ensure the LLM fix didn't break safety or structure
                    is_safe, safety_issues = validate_names_and_imports(current_code)
                    if not is_safe:
                        print(
                            f"[{job_id}] [WARN] Post-fix safety check failed: {safety_issues}"
                        )
                        from algorithms.ai_functions import polish_manim_code as _polish

                        current_code = _polish(current_code)
                        is_safe, safety_issues = validate_names_and_imports(
                            current_code
                        )
                        if not is_safe:
                            print(
                                f"[{job_id}] [ERR] Safety issues persist after polish: {safety_issues}"
                            )

                    structure_valid, structure_error = validate_manim_code(current_code)
                    if not structure_valid:
                        print(
                            f"[{job_id}] [WARN] Post-fix structure check failed: {structure_error}"
                        )
                        current_code = ensure_scene_class(current_code)

                    # Math domain: re-validate LaTeX after fix
                    if analysis and analysis.get("domain") == "math" and not is_fast:
                        latex_valid, latex_issues = validate_latex_strings(current_code)
                        if not latex_valid:
                            print(
                                f"[{job_id}] [WARN] Post-fix LaTeX check failed: {latex_issues}"
                            )

                    # Syntax check (existing)
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

                    batch_id = render_status[job_id].get("batch_id")
                    trigger_webhooks(
                        job_id,
                        "render.error",
                        {
                            "event": "render.error",
                            "job_id": job_id,
                            "batch_id": batch_id,
                            "status": "error",
                            "error": "Render failed after all retries",
                            "timestamp": datetime.now().isoformat(),
                        },
                    )

        except subprocess.TimeoutExpired:
            render_status[job_id]["status"] = "error"
            render_status[job_id]["message"] = "Rendering timed out"
            print(f"[{job_id}] [ERR] TIMEOUT")

            batch_id = render_status[job_id].get("batch_id")
            trigger_webhooks(
                job_id,
                "render.error",
                {
                    "event": "render.error",
                    "job_id": job_id,
                    "batch_id": batch_id,
                    "status": "error",
                    "error": "Rendering timed out",
                    "timestamp": datetime.now().isoformat(),
                },
            )
            return

        except Exception as e:
            render_status[job_id]["status"] = "error"
            render_status[job_id]["message"] = f"Error: {str(e)}"
            print(f"[{job_id}] [ERR] Exception: {e}")

            batch_id = render_status[job_id].get("batch_id")
            trigger_webhooks(
                job_id,
                "render.error",
                {
                    "event": "render.error",
                    "job_id": job_id,
                    "batch_id": batch_id,
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                },
            )
            return


def render_async(
    code: str,
    filename: str,
    job_id: str,
    request_id: str = None,
    prompt: str = "",
    attempt_id: str = None,
    audio_segments: dict = None,
    segment_order: list = None,
    is_fast: bool = False,
    analysis: dict = None,
):
    t = threading.Thread(
        target=save_and_render,
        args=(
            code,
            filename,
            job_id,
            request_id,
            prompt,
            attempt_id,
            audio_segments,
            segment_order,
            is_fast,
            analysis,
        ),
        daemon=True,
    )
    t.start()


# ═══════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
CORS(
    app,
    origins=["http://localhost:3000"],
    methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


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
            print(f"\n{'#' * 60}")
            print(f"[{job_id}] NEW REQUEST: {safe_prompt}")
            print(f"{'#' * 60}\n")

            set_job_status(
                job_id,
                {
                    "status": "generating",
                    "message": "Analyzing and planning...",
                    "video_file": "",
                },
            )

            (
                code,
                attempts_log,
                request_id,
                attempt_id,
                a_segs,
                a_order,
                is_fast,
                analysis,
            ) = generate_and_validate_code(
                prompt,
                job_id,
                max_attempts=MAX_GENERATION_ATTEMPTS,
                voiceover=ENABLE_VOICEOVER,
            )

            set_job_request(job_id, {"request_id": request_id, "prompt": prompt})
            render_async(
                code,
                filename,
                job_id,
                request_id,
                prompt,
                attempt_id,
                a_segs,
                a_order,
                is_fast,
                analysis,
            )

        except Exception as e:
            error = f"Error: {str(e)}"
            print(f"[{job_id}] [ERR] ERROR: {error}")
            if job_id:
                render_status[job_id] = {
                    "status": "error",
                    "message": error,
                    "video_file": "",
                }
            time.sleep(2)

    return render_template("index.html", job_id=job_id, error=error)


@app.route("/status/<job_id>")
def check_status(job_id):
    status = render_status.get(
        job_id, {"status": "unknown", "message": "Job not found"}
    )
    return jsonify(status)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """JSON API for the Next.js frontend."""
    data = request.get_json(force=True)
    prompt = (data.get("prompt") or "").strip()
    use_voiceover = data.get("voiceover", ENABLE_VOICEOVER)
    use_voice = data.get("voice", TTS_VOICE)
    render_template = data.get("render_template")
    watermark_settings = data.get("watermark", {})
    intro_outro_settings = data.get("intro_outro", {})

    client_id = request.remote_addr or "unknown"
    allowed, retry_after = check_rate_limit(client_id)
    if not allowed:
        return jsonify(
            {"error": "Rate limit exceeded", "retry_after": retry_after}
        ), 429

    if not prompt:
        return jsonify({"error": "Please enter a prompt."}), 400

    use_streaming = data.get("streaming", True)

    try:
        job_id = str(uuid.uuid4())[:8]
        filename = f"video_{job_id}"

        safe_prompt = prompt.encode("ascii", "ignore").decode()
        print(f"\n{'#' * 60}")
        print(f"[{job_id}] NEW REQUEST (API) Voiceover={use_voiceover}: {safe_prompt}")
        print(f"[{job_id}] PIPELINE: {'STREAMING' if use_streaming else 'BULK'}")
        print(f"{'#' * 60}\n")

        render_status[job_id] = {
            "status": "generating",
            "message": "Analyzing and planning...",
            "video_file": "",
        }

        def background_generate():
            try:
                if use_streaming:
                    final_video, scene_results, final_context = (
                        stream_generate_and_render(
                            prompt,
                            job_id,
                            analysis=None,
                            voiceover=use_voiceover,
                            voice=use_voice,
                            visual_template=render_template,
                        )
                    )
                    job_to_request[job_id] = {"request_id": None, "prompt": prompt}
                else:
                    (
                        code,
                        attempts_log,
                        req_id,
                        att_id,
                        a_segs,
                        a_order,
                        is_fast,
                        analysis,
                    ) = generate_and_validate_code(
                        prompt,
                        job_id,
                        max_attempts=MAX_GENERATION_ATTEMPTS,
                        voiceover=use_voiceover,
                        voice=use_voice,
                    )
                    job_to_request[job_id] = {"request_id": req_id, "prompt": prompt}
                    render_async(
                        code,
                        filename,
                        job_id,
                        req_id,
                        prompt,
                        att_id,
                        a_segs,
                        a_order,
                        is_fast,
                        analysis,
                    )
            except Exception as e:
                print(f"[{job_id}] [ERR] ERROR in background generation: {e}")
                render_status[job_id] = {
                    "status": "error",
                    "message": str(e),
                    "video_file": "",
                }

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

        n = request.args.get("n", 4, type=int)

        # Don't fail if we request more than available
        k = min(n, len(questions))
        selected = random.sample(questions, k=k)
        return jsonify({"prompts": selected})
    except Exception as e:
        print(f"[API_ERR] Error fetching prompts: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/batch", methods=["POST"])
def api_batch():
    """Batch API for multiple animation requests."""
    data = request.get_json(force=True)
    prompts_data = data.get("prompts", [])
    use_voiceover = data.get("voiceover", False)
    use_voice = data.get("voice", TTS_VOICE)

    if not prompts_data or not isinstance(prompts_data, list):
        return jsonify({"error": "prompts must be a non-empty array"}), 400

    if len(prompts_data) > 20:
        return jsonify({"error": "Maximum 20 prompts per batch"}), 400

    batch_id = str(uuid.uuid4())[:8]
    jobs = []

    for i, item in enumerate(prompts_data):
        if isinstance(item, dict):
            prompt = (item.get("prompt") or "").strip()
        else:
            prompt = str(item).strip()

        if not prompt:
            continue

        job_id = str(uuid.uuid4())[:8]
        filename = f"video_{job_id}"

        safe_prompt = prompt.encode("ascii", "ignore").decode()
        print(f"\n[{job_id}] BATCH [{batch_id}] ITEM {i + 1}: {safe_prompt[:50]}...")

        with _state_lock:
            render_status[job_id] = {
                "status": "queued",
                "message": "Queued for processing...",
                "video_file": "",
                "batch_id": batch_id,
            }

        def background_generate():
            try:
                from algorithms.request_analysis import expand_short_prompt

                prompt = expand_short_prompt(prompt)
                (
                    code,
                    attempts_log,
                    req_id,
                    att_id,
                    a_segs,
                    a_order,
                    is_fast,
                    analysis,
                ) = generate_and_validate_code(
                    prompt,
                    job_id,
                    max_attempts=MAX_GENERATION_ATTEMPTS,
                    voiceover=use_voiceover,
                    voice=use_voice,
                )
                job_to_request[job_id] = {"request_id": req_id, "prompt": prompt}
                render_async(
                    code,
                    filename,
                    job_id,
                    req_id,
                    prompt,
                    att_id,
                    a_segs,
                    a_order,
                    is_fast,
                )
            except Exception as e:
                print(f"[{job_id}] [ERR] Batch item error: {e}")
                with _state_lock:
                    render_status[job_id] = {
                        "status": "error",
                        "message": str(e),
                        "video_file": "",
                    }

        t = threading.Thread(target=background_generate, daemon=True)
        t.start()

        jobs.append({"prompt": prompt, "job_id": job_id})

    return jsonify({"batch_id": batch_id, "jobs": jobs})


@app.route("/api/templates", methods=["GET"])
def api_list_templates():
    """List approved user templates."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"})
    try:
        with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, domain, slots, beats, notes, code_pattern, created_at
                FROM user_templates
                WHERE status = 'approved'
                ORDER BY created_at DESC
            """)
            templates = [dict(r) for r in cur.fetchall()]
        return jsonify({"templates": templates})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/render-templates", methods=["GET"])
def api_list_render_templates():
    """List curated backend render templates for streaming pipeline."""
    try:
        from algorithms.streaming import VISUAL_TEMPLATES

        return jsonify(
            {"templates": [{"id": k, **v} for k, v in VISUAL_TEMPLATES.items()]}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/templates", methods=["POST"])
def api_submit_template():
    """Submit a new user template."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"})
    try:
        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        domain = data.get("domain", "").strip()
        slots = data.get("slots", [])
        beats = data.get("beats", 5)
        notes = data.get("notes", "")
        code_pattern = data.get("code_pattern", "")
        submitted_by = data.get("submitted_by", "anonymous")

        if not name or not domain:
            return jsonify({"error": "name and domain are required"}), 400

        with db.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_templates (name, domain, slots, beats, notes, code_pattern, status, submitted_by)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)
                RETURNING id
            """,
                (name, domain, Json(slots), beats, notes, code_pattern, submitted_by),
            )
            template_id = cur.fetchone()[0]
            db.conn.commit()

        return jsonify(
            {
                "id": template_id,
                "status": "pending",
                "message": "Template submitted for review",
            }
        ), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/templates/pending", methods=["GET"])
def api_pending_templates():
    """List pending templates (admin)."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"})
    try:
        with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, domain, slots, beats, notes, submitted_by, created_at
                FROM user_templates
                WHERE status = 'pending'
                ORDER BY created_at DESC
            """)
            templates = [dict(r) for r in cur.fetchall()]
        return jsonify({"templates": templates})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/templates/<int:template_id>/approve", methods=["PUT"])
def api_approve_template(template_id):
    """Approve a user template (admin)."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"})
    try:
        with db.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_templates SET status = 'approved'
                WHERE id = %s AND status = 'pending'
                RETURNING id
            """,
                (template_id,),
            )
            result = cur.fetchone()
            db.conn.commit()

        if result:
            return jsonify({"id": template_id, "status": "approved"})
        else:
            return jsonify({"error": "Template not found or already approved"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/templates/<int:template_id>", methods=["DELETE"])
def api_delete_template(template_id):
    """Delete a user template (admin)."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"})
    try:
        with db.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_templates WHERE id = %s RETURNING id", (template_id,)
            )
            result = cur.fetchone()
            db.conn.commit()

        if result:
            return jsonify({"id": template_id, "deleted": True})
        else:
            return jsonify({"error": "Template not found"}), 404
    except Exception as e:
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
                    COUNT(DISTINCT ep.id) as unique_error_patterns,
                    COUNT(DISTINCT CASE WHEN rj.status='done' THEN rj.id END) * 100.0 / NULLIF(COUNT(DISTINCT r.id), 0) as success_rate
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

            cur.execute("""
                SELECT
                    ROUND(CAST(AVG(ae.layout_quality) AS numeric), 1) as avg_layout,
                    ROUND(CAST(AVG(ae.educational_value) AS numeric), 1) as avg_educational,
                    ROUND(CAST(AVG(ae.technical_accuracy) AS numeric), 1) as avg_technical,
                    ROUND(CAST(AVG(ae.pacing) AS numeric), 1) as avg_pacing,
                    ROUND(CAST(AVG(ae.manim_quality) AS numeric), 1) as avg_manim
                FROM ai_evaluations ae
                WHERE ae.overall_score IS NOT NULL
            """)
            quality_dims = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT
                    COUNT(CASE WHEN overall_score >= 80 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) as pct_80_plus,
                    COUNT(CASE WHEN overall_score >= 70 AND overall_score < 80 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) as pct_70_79,
                    COUNT(CASE WHEN overall_score >= 60 AND overall_score < 70 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) as pct_60_69,
                    COUNT(CASE WHEN overall_score < 60 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) as pct_below_60
                FROM ai_evaluations
            """)
            quality_dist = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT error_category, root_cause, fix_description, occurrence_count
                FROM error_patterns
                WHERE NOT resolved
                ORDER BY occurrence_count DESC LIMIT 5
            """)
            error_patterns = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT MAX(rj.completed_at) as last_render_at,
                       COUNT(CASE WHEN DATE(rj.completed_at) = CURRENT_DATE THEN 1 END) as renders_today,
                       ROUND(AVG(rj.render_duration_seconds), 1) as avg_render_duration
                FROM render_jobs rj
                WHERE rj.status = 'done'
            """)
            render_meta = dict(cur.fetchone() or {})

        return jsonify(
            {
                "stats": stats_data,
                "quality_dims": quality_dims,
                "quality_tiers": quality_dist,
                "top_domains": domains,
                "top_errors": error_patterns,
                "last_render_at": render_meta.get("last_render_at"),
                "renders_today": render_meta.get("renders_today", 0),
                "avg_render_duration": render_meta.get("avg_render_duration"),
                "database_enabled": True,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/stats/top-examples")
def stats_top_examples():
    """Get highest scoring examples for showcase."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"})
    try:
        with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT r.prompt, r.domain, r.topic,
                       ae.overall_score, ae.visual_quality_score,
                       ae.educational_value_score, ae.pacing,
                       rj.video_path, rj.created_at
                FROM requests r
                JOIN render_jobs rj ON r.id = rj.request_id
                JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                WHERE rj.status = 'done' AND ae.overall_score >= 80
                ORDER BY ae.overall_score DESC
                LIMIT 10
            """)
            examples = [dict(r) for r in cur.fetchall()]
        return jsonify({"top_examples": examples})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/videos", methods=["GET"])
def list_videos():
    """List videos with pagination and filtering."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    domain = request.args.get("domain")
    search = request.args.get("search")
    sort_by = request.args.get("sort_by", "created_at")
    sort_order = request.args.get("sort_order", "desc")

    offset = (page - 1) * per_page

    try:
        with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
            base_query = """
                SELECT v.id, v.filename, v.organized_path, v.file_size_bytes,
                       v.duration_seconds, v.resolution, v.domain, v.cdn_url,
                       v.created_at, r.prompt, r.topic,
                       rj.status as render_status, ae.overall_score
                FROM videos v
                JOIN render_jobs rj ON v.render_job_id = rj.id
                JOIN requests r ON v.request_id = r.id
                LEFT JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                WHERE v.id IS NOT NULL
            """
            params = []

            if domain:
                base_query += " AND v.domain = %s"
                params.append(domain)

            if search:
                base_query += " AND r.prompt ILIKE %s"
                params.append(f"%{search}%")

            count_query = f"SELECT COUNT(*) FROM ({base_query}) sub"
            cur.execute(count_query, params)
            total = cur.fetchone()["count"]

            order_col = "v.created_at" if sort_by == "created_at" else f"v.{sort_by}"
            sort_dir = "DESC" if sort_order == "desc" else "ASC"
            base_query += f" ORDER BY {order_col} {sort_dir}"
            base_query += " LIMIT %s OFFSET %s"
            params.extend([per_page, offset])

            cur.execute(base_query, params)
            videos = [dict(r) for r in cur.fetchall()]

        return jsonify(
            {
                "videos": videos,
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/videos/<video_id>", methods=["GET"])
def get_video(video_id):
    """Get single video details."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    try:
        with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT v.*, r.prompt, r.topic, r.domain,
                       rj.status as render_status, ae.overall_score
                FROM videos v
                JOIN render_jobs rj ON v.render_job_id = rj.id
                JOIN requests r ON v.request_id = r.id
                LEFT JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                WHERE v.id = %s
            """,
                (video_id,),
            )
            video = cur.fetchone()

        if not video:
            return jsonify({"error": "Video not found"}), 404

        return jsonify(dict(video))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/videos/search", methods=["GET"])
def search_videos():
    """Search videos by prompt text."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    limit = request.args.get("limit", 10, type=int)

    try:
        with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT v.id, v.filename, v.organized_path, v.domain,
                       v.created_at, r.prompt, ae.overall_score
                FROM videos v
                JOIN requests r ON v.request_id = r.id
                LEFT JOIN ai_evaluations ae ON v.render_job_id = ae.render_job_id
                WHERE r.prompt ILIKE %s
                ORDER BY v.created_at DESC
                LIMIT %s
            """,
                (f"%{query}%", limit),
            )
            results = [dict(r) for r in cur.fetchall()]

        return jsonify({"results": results, "query": query})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/videos/cdn-url/<video_id>", methods=["GET"])
def get_video_cdn_url(video_id):
    """
    Get CDN URL for a video.
    If CDN is not configured, returns the local /outputs URL.
    """
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    try:
        with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, organized_path, cdn_url
                FROM videos
                WHERE id = %s
            """,
                (video_id,),
            )

            video = cur.fetchone()
            if not video:
                return jsonify({"error": "Video not found"}), 404

            if video.get("cdn_url"):
                return jsonify(
                    {"video_id": video_id, "url": video["cdn_url"], "source": "stored"}
                )

            if CDN_ENABLED and video.get("organized_path"):
                rel_path = Path(video["organized_path"]).relative_to(OUTPUTS)
                cdn_url = f"{CDN_BASE_URL.rstrip('/')}/{rel_path}"

                cur.execute(
                    "UPDATE videos SET cdn_url = %s WHERE id = %s", (cdn_url, video_id)
                )

                return jsonify(
                    {"video_id": video_id, "url": cdn_url, "source": "generated"}
                )

            local_url = f"/outputs/{Path(video['organized_path']).name}"
            return jsonify({"video_id": video_id, "url": local_url, "source": "local"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/videos/cdn-url", methods=["POST"])
def set_video_cdn_url():
    """
    Manually set CDN URL for a video (admin endpoint).
    """
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    data = request.get_json()
    video_id = data.get("video_id")
    cdn_url = data.get("cdn_url")

    if not video_id or not cdn_url:
        return jsonify({"error": "video_id and cdn_url required"}), 400

    try:
        with db.conn.cursor() as cur:
            cur.execute(
                "UPDATE videos SET cdn_url = %s WHERE id = %s", (cdn_url, video_id)
            )
            if cur.rowcount == 0:
                return jsonify({"error": "Video not found"}), 404

            return jsonify({"success": True, "video_id": video_id, "cdn_url": cdn_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "database": db.available if db else False,
            "active_jobs": len(
                [
                    s
                    for s in render_status.values()
                    if s.get("status") in ("generating", "rendering")
                ]
            ),
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# API KEY AUTHENTICATION
# ═══════════════════════════════════════════════════════════════════════════════

import hashlib
import secrets


def require_api_key(f):
    """Decorator to require API key authentication."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("X-API-Key") or request.headers.get(
            "Authorization", ""
        ).replace("Bearer ", "")

        if not api_key:
            return jsonify({"error": "API key required"}), 401

        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        key_record = db.verify_api_key(api_key)
        if not key_record:
            return jsonify({"error": "Invalid API key"}), 401

        if key_record.get("daily_quota"):
            if key_record.get("requests_today", 0) >= key_record["daily_quota"]:
                return jsonify({"error": "Daily quota exceeded"}), 429

        key_id = key_record["id"]
        allowed, retry_after = check_rate_limit(f"apikey:{key_id}")
        if not allowed:
            return jsonify(
                {"error": "Rate limit exceeded", "retry_after": retry_after}
            ), 429

        db.increment_api_usage(key_id, request.path, request.method, 200, 0)
        request.api_key = key_record
        return f(*args, **kwargs)

    return decorated


@app.route("/api/keys", methods=["POST"])
def api_create_api_key():
    """Create a new API key (admin)."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    data = request.get_json(force=True) if request.is_json else {}
    name = data.get("name", "").strip() or "Default Key"
    rate_limit = data.get("rate_limit", 60)
    daily_quota = data.get("daily_quota")

    try:
        plain_key = "nima_" + secrets.token_hex(16)
        key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
        key_prefix = plain_key[:12]

        kid = db.save_api_key(
            user_id=None,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
            rate_limit=rate_limit,
            daily_quota=daily_quota,
        )
        return jsonify(
            {
                "api_key": plain_key,
                "key_id": kid,
                "key_prefix": key_prefix,
                "message": "Store this key securely - it will not be shown again",
            }
        ), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/keys", methods=["GET"])
@require_api_key
def api_list_api_keys():
    """List API keys (masked)."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    try:
        keys = (
            db._exec(
                """SELECT id, key_prefix, name, rate_limit, daily_quota,
                          requests_today, last_used_at, created_at
                   FROM api_keys WHERE revoked_at IS NULL""",
                fetch="all",
            )
            or []
        )
        return jsonify({"keys": [dict(k) for k in keys]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/keys/<key_id>", methods=["DELETE"])
@require_api_key
def api_revoke_api_key(key_id):
    """Revoke an API key."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    try:
        db._exec("UPDATE api_keys SET revoked_at=NOW() WHERE id=%s", (key_id,))
        return jsonify({"revoked": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


@app.route("/api/webhooks", methods=["POST"])
def api_create_webhook():
    """Register a new webhook."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    data = request.get_json(force=True) if request.is_json else {}
    url = data.get("url", "").strip()
    secret = data.get("secret")
    events = data.get("events", ["render.complete", "render.error"])

    if not url or not url.startswith(("http://", "https://")):
        return jsonify({"error": "Valid URL required"}), 400

    try:
        wid = db.save_webhook(user_id=None, url=url, secret=secret, events=events)
        return jsonify({"webhook_id": wid, "message": "Webhook registered"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/webhooks", methods=["GET"])
def api_list_webhooks():
    """List registered webhooks."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    try:
        webhooks = (
            db._exec(
                "SELECT id, url, events, active, created_at FROM webhooks", fetch="all"
            )
            or []
        )
        return jsonify({"webhooks": [dict(w) for w in webhooks]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/webhooks/<webhook_id>", methods=["DELETE"])
def api_delete_webhook(webhook_id):
    """Delete a webhook."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    try:
        db._exec("UPDATE webhooks SET active=false WHERE id=%s", (webhook_id,))
        return jsonify({"deleted": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH STATUS ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════


@app.route("/api/batch/<batch_id>", methods=["GET"])
def api_batch_status(batch_id):
    """Get batch status and progress."""
    batch_jobs = [
        (jid, status)
        for jid, status in render_status.items()
        if status.get("batch_id") == batch_id
    ]

    total = len(batch_jobs)
    completed = sum(1 for _, s in batch_jobs if s.get("status") == "done")
    failed = sum(1 for _, s in batch_jobs if s.get("status") == "error")
    in_progress = sum(
        1
        for _, s in batch_jobs
        if s.get("status") in ("generating", "rendering", "queued")
    )

    progress_percent = int((completed + failed) / total * 100) if total > 0 else 0

    status = "completed" if (completed + failed) >= total else "in_progress"
    if failed > 0 and (completed + failed) >= total:
        status = "completed_with_errors"

    return jsonify(
        {
            "batch_id": batch_id,
            "total": total,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "progress_percent": progress_percent,
            "status": status,
        }
    )


@app.route("/api/batch/<batch_id>/jobs", methods=["GET"])
def api_batch_jobs(batch_id):
    """Get all jobs in a batch with their status."""
    batch_jobs = [
        {"job_id": jid, **status}
        for jid, status in render_status.items()
        if status.get("batch_id") == batch_id
    ]
    return jsonify({"batch_id": batch_id, "jobs": batch_jobs})


# ═══════════════════════════════════════════════════════════════════════════════
# LTI 1.3 ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

_lti_sessions: Dict[str, dict] = {}


@app.route("/api/lti/login", methods=["GET", "POST"])
def lti_login():
    """
    LTI 1.3 login initiation.
    Query params: iss (issuer), client_id, login_hint, target_link_uri
    """
    issuer = request.args.get("iss", "").strip()
    client_id = request.args.get("client_id", "").strip()
    login_hint = request.args.get("login_hint", "").strip()
    target_link_uri = request.args.get("target_link_uri", "").strip()

    if not all([issuer, client_id, login_hint, target_link_uri]):
        return jsonify({"error": "Missing required LTI parameters"}), 400

    if not db or not db.available:
        return jsonify({"error": "LTI not configured"}), 503

    platform = db.get_lti_platform_by_issuer(issuer)
    if not platform:
        return jsonify({"error": "Unknown LTI platform"}), 400

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    _lti_sessions[state] = {
        "issuer": issuer,
        "client_id": client_id,
        "platform": platform,
        "login_hint": login_hint,
        "target_link_uri": target_link_uri,
        "nonce": nonce,
    }

    auth_url = platform["auth_endpoint"]
    params = {
        "response_type": "id_token",
        "response_mode": "form_post",
        "scope": "openid",
        "login_hint": login_hint,
        "nonce": nonce,
        "state": state,
        "redirect_uri": f"{request.url_root}api/lti/launch",
    }

    from urllib.parse import urlencode

    full_url = f"{auth_url}?{urlencode(params)}"

    return jsonify({"auth_url": full_url, "state": state})


@app.route("/api/lti/launch", methods=["POST"])
def lti_launch():
    """LTI 1.3 launch handler."""
    id_token = request.form.get("id_token", "").strip()
    state = request.form.get("state", "").strip()

    if not id_token or not state:
        return jsonify({"error": "Missing id_token or state"}), 400

    session = _lti_sessions.pop(state, None)
    if not session:
        return jsonify({"error": "Invalid state"}), 400

    try:
        import jwt

        claims = jwt.decode(id_token, options={"verify_signature": False})

        user_id = claims.get("sub", "")
        email = claims.get("email", "")
        name = claims.get("name", "")
        roles = claims.get("roles", [])

        is_instructor = "Instructor" in roles or "ContentDeveloper" in roles

        return jsonify(
            {
                "lti_user_id": str(uuid.uuid4()),
                "user_id": user_id,
                "email": email,
                "name": name,
                "roles": roles,
                "is_instructor": is_instructor,
                "message": "LTI launch successful",
            }
        )

    except Exception as e:
        return jsonify({"error": f"LTI launch failed: {str(e)}"}), 400


@app.route("/api/lti/embed/<job_id>", methods=["GET"])
def lti_embed_video(job_id):
    """Get embed URL for a video in LMS."""
    status = render_status.get(job_id)
    if not status:
        return jsonify({"error": "Job not found"}), 404

    if status.get("status") != "done":
        return jsonify(
            {"error": "Video not ready", "status": status.get("status")}
        ), 400

    video_file = status.get("video_file", "")
    if not video_file:
        return jsonify({"error": "Video not found"}), 404

    embed_url = f"/outputs/{video_file}"

    return jsonify(
        {
            "job_id": job_id,
            "embed_url": embed_url,
            "player_url": f"/player/{job_id}",
            "status": "ready",
        }
    )


@app.route("/api/lti/config", methods=["GET"])
def lti_config():
    """Returns LTI configuration for platform setup."""
    return jsonify(
        {
            "issuer": request.url_root.rstrip("/"),
            "client_id": "nima-lti",
            "auth_endpoint": f"{request.url_root}api/lti/login",
            "token_endpoint": f"{request.url_root}api/lti/token",
            "jwks_endpoint": f"{request.url_root}api/lti/jwks",
            "deployment_id": "1",
        }
    )


@app.route("/api/lti/platforms", methods=["POST"])
def api_register_lti_platform():
    """Register a new LTI platform (admin)."""
    if not db or not db.available:
        return jsonify({"error": "Database not available"}), 503

    data = request.get_json(force=True) if request.is_json else {}
    required = [
        "name",
        "issuer",
        "client_id",
        "auth_endpoint",
        "token_endpoint",
        "jwks_endpoint",
    ]

    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} required"}), 400

    try:
        pid = db.save_lti_platform(
            name=data["name"],
            issuer=data["issuer"],
            client_id=data["client_id"],
            deployment_id=data.get("deployment_id", "1"),
            auth_endpoint=data["auth_endpoint"],
            token_endpoint=data["token_endpoint"],
            jwks_endpoint=data["jwks_endpoint"],
        )
        return jsonify({"platform_id": pid, "message": "Platform registered"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/lti/jwks", methods=["GET"])
def lti_jwks():
    """Returns NIMA's public keys for JWT verification."""
    return jsonify(
        {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": "nima-lti-key-1",
                    "n": "-placeholder",
                    "e": "AQAB",
                }
            ]
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════


def prewarm_manim():
    """Warm up Manim by rendering a minimal scene and preloading common assets."""
    try:
        if DRAFT_PIPELINE:
            print("[WARMUP] Skipping manim warmup in DRAFT mode")
            return

        import tempfile

        warmup_code = """from manim import *
class WarmupScene(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(warmup_code)
            warmup_path = f.name

        print("[WARMUP] Pre-warming Manim (first render is slow)...")
        result = subprocess.run(
            ["manim", warmup_path, "WarmupScene", "-ql", "--disable_caching"],
            capture_output=True,
            timeout=120,
        )
        print(f"[WARMUP] {'OK' if result.returncode == 0 else 'FAILED'}")

        # Preload common assets
        if WARMUP_PLANES:
            print("[WARMUP] Preloading planes and axes...")
            plane_code = """from manim import *
class PlaneWarmup(Scene):
    def construct(self):
        plane = NumberPlane(x_range=[-4,4], y_range=[-3,3])
        self.add(plane)
"""
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(plane_code)
                plane_path = f.name
            subprocess.run(
                ["manim", plane_path, "PlaneWarmup", "-ql", "--disable_caching"],
                capture_output=True,
                timeout=60,
            )

    except Exception as e:
        print(f"[WARMUP] [ERR] Manim warmup failed: {e}", flush=True)


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("NIMA — Manim AI Generator")
    print("=" * 60)
    print(f"[OK] Model: {__import__('config').GENERATION_MODEL}")
    print(f"[OK] Fast model: {__import__('config').FAST_MODEL}")
    print(f"[OK] Database: {'ENABLED' if USE_DATABASE else 'DISABLED'}")
    print(
        f"[OK] Render retries: {MAX_RENDER_RETRIES} (with LLM error-fix between each)"
    )
    print(
        f"[OK] Pipeline: {'DRAFT' if DRAFT_PIPELINE else ('FAST' if FAST_PIPELINE else 'FULL')}"
    )
    print(f"[OK] RAG corpus: 25+ curated patterns")
    print(f"[OK] Review pass: consolidated (layout + API + pacing)")

    # Pre-warm in background
    import threading

    warmup_thread = threading.Thread(target=prewarm_manim, daemon=True)
    warmup_thread.start()

    def _check_warmup():
        warmup_thread.join(timeout=30)
        if warmup_thread.is_alive():
            print(
                "[WARMUP] [WARN] Manim warmup did not complete within 30s — first render will pay cold-start cost",
                flush=True,
            )
        else:
            print("[WARMUP] [OK] Manim warmup completed", flush=True)

    threading.Thread(target=_check_warmup, daemon=True).start()

    print("=" * 60)
    print("http://localhost:5000")
    print("Stats: http://localhost:5000/stats")
    print("=" * 60 + "\n")

    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, use_reloader=False)
