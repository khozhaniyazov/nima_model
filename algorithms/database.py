"""PostgreSQL persistence adapter for NIMA render metadata."""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

import psycopg2
from psycopg2.extras import Json, RealDictCursor


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
        """Safe helper, returns None on error."""
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
        query = """SELECT r.prompt, r.domain, r.topic, rj.final_code, ae.overall_score
               FROM requests r
               JOIN render_jobs rj ON r.id = rj.request_id
               JOIN ai_evaluations ae ON rj.id = ae.render_job_id
               WHERE rj.status = 'done' AND ae.overall_score >= 80"""
        params = []
        if domain:
            query += " AND r.domain = %s"
            params.append(domain)
        if topic:
            query += " AND (r.topic ILIKE %s OR r.prompt ILIKE %s)"
            params.extend([f"%{topic}%", f"%{topic}%"])
        query += " ORDER BY ae.overall_score DESC, r.created_at DESC LIMIT %s"
        params.append(limit)
        return self._exec(query, params, fetch="all") or []

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

