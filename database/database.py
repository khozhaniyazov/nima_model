import psycopg2
from psycopg2.extras import Json, RealDictCursor
from datetime import datetime
import json
from typing import Optional, Dict, Any
import uuid


DB_CONNECTION_STRING = "postgresql://postgres:Zk201910902!@localhost:5432/manim_db"
USE_DATABASE = True

class ManimDatabase:
    def __init__(self, connection_string: str):
        try:
            self.conn = psycopg2.connect(connection_string)
            self.conn.autocommit = True
            self.available = True
            print("[DB] Connected successfully")
        except Exception as e:
            print(f"[DB] Connection failed: {e}")
            self.conn = None
            self.available = False
    
    def save_request(self, prompt: str, analysis: dict, user_id: str = None) -> str:
        if not self.available:
            return str(uuid.uuid4())
        
        try:
            with self.conn.cursor() as cur:
                request_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO requests (
                        id, prompt, user_id, topic, domain, complexity, 
                        estimated_duration, analysis_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    request_id, prompt, user_id,
                    analysis.get('topic'), analysis.get('domain'),
                    analysis.get('complexity'), analysis.get('duration'),
                    Json(analysis)
                ))
                return request_id
        except Exception as e:
            print(f"[DB] Save request error: {e}")
            return str(uuid.uuid4())
    
    def save_generation_attempt(self, request_id: str, attempt_data: dict) -> str:
        if not self.available:
            return str(uuid.uuid4())
        
        try:
            with self.conn.cursor() as cur:
                attempt_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO generation_attempts (
                        id, request_id, attempt_number, model_version,
                        animation_plan, generated_code, code_length,
                        critique_feedback, improved_code,
                        syntax_valid, syntax_error, structure_valid,
                        quality_warnings, generation_time_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    attempt_id, request_id, attempt_data['attempt_number'],
                    'gpt-4o', attempt_data.get('plan'), attempt_data['code'],
                    len(attempt_data['code']), attempt_data.get('critique'),
                    attempt_data.get('improved_code'), attempt_data.get('syntax_valid', True),
                    attempt_data.get('syntax_error'), attempt_data.get('structure_valid', True),
                    Json(attempt_data.get('warnings', [])), attempt_data.get('generation_time_ms', 0)
                ))
                return attempt_id
        except Exception as e:
            print(f"[DB] Save attempt error: {e}")
            return str(uuid.uuid4())
    
    def save_render_job(self, request_id: str, attempt_id: str, render_data: dict) -> str:
        if not self.available:
            return str(uuid.uuid4())
        
        try:
            with self.conn.cursor() as cur:
                job_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO render_jobs (
                        id, request_id, attempt_id, final_code, script_path,
                        status, started_at, completed_at, render_duration_seconds,
                        manim_stdout, manim_stderr, return_code, video_path,
                        error_type, error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    job_id, request_id, attempt_id, render_data['code'],
                    render_data.get('script_path'), render_data['status'],
                    render_data.get('started_at'), render_data.get('completed_at'),
                    render_data.get('duration'), render_data.get('stdout'),
                    render_data.get('stderr'), render_data.get('return_code'),
                    render_data.get('video_path'), render_data.get('error_type'),
                    render_data.get('error_message')
                ))
                return job_id
        except Exception as e:
            print(f"[DB] Save render error: {e}")
            return str(uuid.uuid4())
    
    def save_ai_evaluation(self, request_id: str, render_job_id: str, evaluation: dict) -> str:
        if not self.available:
            return str(uuid.uuid4())
        
        try:
            with self.conn.cursor() as cur:
                eval_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO ai_evaluations (
                        id, request_id, render_job_id, evaluator_model,
                        visual_quality_score, educational_value_score,
                        technical_accuracy_score, pacing_timing_score,
                        clarity_score, engagement_score, overall_score,
                        strengths, weaknesses, specific_issues, suggestions,
                        predicted_satisfaction, full_evaluation_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    eval_id, request_id, render_job_id, 'gpt-4o',
                    evaluation.get('visual_quality', 0), evaluation.get('educational_value', 0),
                    evaluation.get('technical_accuracy', 0), evaluation.get('pacing_timing', 0),
                    evaluation.get('clarity', 0), evaluation.get('engagement', 0),
                    evaluation.get('overall', 0), evaluation.get('strengths'),
                    evaluation.get('weaknesses'), Json(evaluation.get('issues', [])),
                    evaluation.get('suggestions'), evaluation.get('predicted_satisfaction', 0),
                    Json(evaluation)
                ))
                return eval_id
        except Exception as e:
            print(f"[DB] Save evaluation error: {e}")
            return str(uuid.uuid4())
    
    def get_best_examples(self, domain: str = None, limit: int = 3) -> list:
        if not self.available:
            return []
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT r.prompt, r.domain, r.topic, rj.final_code, ae.overall_score
                    FROM requests r
                    JOIN render_jobs rj ON r.id = rj.request_id
                    JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                    WHERE rj.status = 'done' AND ae.overall_score >= 80
                """
                params = []
                if domain:
                    query += " AND r.domain = %s"
                    params.append(domain)
                query += " ORDER BY ae.overall_score DESC LIMIT %s"
                params.append(limit)
                
                cur.execute(query, params)
                return cur.fetchall()
        except Exception as e:
            print(f"[DB] Get examples error: {e}")
            return []
    
    def get_error_patterns(self, limit: int = 5) -> list:
        if not self.available:
            return []
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT error_category, root_cause, fix_description, occurrence_count
                    FROM error_patterns
                    WHERE NOT resolved
                    ORDER BY occurrence_count DESC
                    LIMIT %s
                """, (limit,))
                return cur.fetchall()
        except Exception as e:
            print(f"[DB] Get errors error: {e}")
            return []
    
    def record_error_pattern(self, error_data: dict):
        if not self.available:
            return
        
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT id, occurrence_count FROM error_patterns
                    WHERE error_signature = %s
                """, (error_data['signature'],))
                result = cur.fetchone()
                
                if result:
                    cur.execute("""
                        UPDATE error_patterns
                        SET occurrence_count = occurrence_count + 1, last_seen = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (result[0],))
                else:
                    cur.execute("""
                        INSERT INTO error_patterns (
                            id, error_category, error_signature, example_error_message,
                            example_code_snippet, root_cause, fix_description
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        str(uuid.uuid4()), error_data['category'], error_data['signature'],
                        error_data['message'], error_data.get('code_snippet'),
                        error_data.get('root_cause', 'Unknown'),
                        error_data.get('fix', 'Check syntax and API usage')
                    ))
        except Exception as e:
            print(f"[DB] Record error error: {e}")

db = ManimDatabase(DB_CONNECTION_STRING) if USE_DATABASE else None
