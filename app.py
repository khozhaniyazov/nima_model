from flask import Flask, render_template, request, send_from_directory, jsonify
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

from dotenv import load_dotenv
load_dotenv()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

from algorithms.request_analysis import analyze_request_type, create_animation_plan
from algorithms.ai_functions import get_domain_specific_guidance, generate_manim_code, self_critique_and_improve, polish_manim_code, extract_code, ai_fix, overlapping_fix, inject_helpers, retrieve_golden_example, get_error_warnings, evaluate_with_gpt4
from algorithms.code_digest import ensure_scene_class, validate_python_syntax, validate_manim_code, check_code_quality

import psycopg2
from psycopg2.extras import Json, RealDictCursor

DB_CONNECTION_STRING = "postgresql://postgres:Zk201910902!@localhost:5432/manim_db"
USE_DATABASE = True

MANIM_SCRIPTS = Path("C:/temp/manim_scripts")
OUTPUTS = Path("C:/temp/outputs")
MANIM_SCRIPTS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

print(f"[STARTUP] Manim scripts directory: {MANIM_SCRIPTS.absolute()}")
print(f"[STARTUP] Outputs directory: {OUTPUTS.absolute()}")

render_status = {}

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

questions = [
    "Solve log_3(x) = 2 and explain what this means using the idea of 'how many times 3 multiplies itself'.",
    "Explain what a homomorphism is by showing how addition mod 5 maps into addition mod 10.",
    "Explain group theory by using the symmetries of a square (rotations and flips) as an example.",
    "If a box has 3 red and 5 blue balls and you draw **without replacement**, what is the probability the first ball is red? Explain the reasoning step by step.",
    "Explain the Fourier transform by showing how the sound of a tuning fork can be broken into frequencies.",
    "Explain the Laplace transform by demonstrating how it simplifies solving y' + 3y = 2.",
    "Visualize y = x^2 + 3x by locating its vertex, intercepts, and showing how the parabola shifts from y = x^2.",
    "Solve 2x + 5 = 11 and explain it as 'undoing operations' for a 7th-grade student.",
    "Find the derivative of x^3 and explain using the idea of the 'instantaneous speed' of x^3 growing.",
    "Explain what an integral is by describing the area under the curve of y = 2x between x = 0 and x = 3.",
    "Explain what a vector space is using the example of all 2D arrows drawn on graph paper.",
    "Explain what a basis is by showing that the vectors (1,0) and (0,1) can describe any point on a grid.",
    "Explain eigenvalues and eigenvectors using the example of stretching a rubber band only in one direction.",
    "Compute the determinant of a 2×2 matrix and explain how it tells you how area is scaled.",
    "Explain what a matrix is by relating it to transformations like rotating a point on the plane.",
    "Find the inverse of a simple 2×2 matrix and explain why it 'undoes' the transformation.",
    "Explain what a limit is by describing why (x^2 − 1)/(x − 1) approaches 2 as x → 1 even though x = 1 causes a hole.",
    "Compute lim(x→0) sin(x)/x and explain using the unit circle argument.",
    "Explain the chain rule by differentiating (3x^2 + 1)^5 and showing the inner and outer functions.",
    "Explain the product rule by differentiating x^2·sin(x) and describing why 'each part takes turns being differentiated'.",
    "Explain the quotient rule by differentiating (2x+1)/(x^2+3).",
    "Explain partial derivatives using the example of temperature T(x,y) on a metal plate.",
    "Explain the gradient by showing how it points toward the steepest increase on a hill map.",
    "Explain divergence and curl using a diagram of water flow in a river.",
    "Explain the Taylor series by expanding sin(x) around x = 0 and showing the first 3 terms.",
    "Explain the binomial theorem using (a + b)^4 and show the combinatorial coefficients.",
    "Explain the difference between permutation and combination using the example of selecting class leaders from 4 students.",
    "Explain what a probability distribution is using the example of rolling a loaded die.",
    "Explain what a random variable is using the number of heads in 3 coin flips.",
    "Explain the normal distribution using students' test scores as an example.",
    "Compute the expected value of rolling a 6-sided die and explain why it's not necessarily a value the die can show.",
    "Explain variance and standard deviation using 3 test scores: 70, 70, 100.",
    "Explain conditional probability with the example 'probability of drawing a king given that the card is a face card'.",
    "Explain Bayes' theorem with a simple medical test false-positive/false-negative example.",
    "Explain what a function is using a vending machine analogy.",
    "Explain injective, surjective, and bijective functions using arrow diagrams between sets.",
    "Explain what a polynomial is and show examples of degree 0, 1, 2, and 3.",
    "Explain what a root of a polynomial is using x^2−9 and show why ±3 are solutions.",
    "Solve x^2 − 5x + 6 = 0 and explain why factoring works.",
    "Explain the quadratic formula and derive it from completing the square.",
    "Explain an arithmetic sequence using the pattern: 4, 9, 14, 19, …",
    "Explain a geometric sequence using money doubling every day.",
    "Explain what a series is by summing the first 5 terms of 2 + 5 + 8 + 11 + …",
    "Explain convergence using the infinite series 1/2 + 1/4 + 1/8 + …",
    "Explain an infinite geometric series using the idea of repeatedly folding a paper strip.",
    "Explain what a complex number is using the coordinate plane.",
    "Explain the imaginary unit i using the idea that it is the square root of −1 and show why i^2 = −1.",
    "Convert 3 + 4i to polar form and explain the meaning of magnitude and angle.",
    "Explain Euler's formula e^{ix} = cos(x) + i sin(x) using a unit circle rotation example.",
    "Explain what a differential equation is using the example y' = 3y.",
    "Explain first-order linear differential equations using y' + y = e^x.",
    "Explain what a separable differential equation is using dy/dx = xy.",
    "Explain what a boundary value problem is using temperature at both ends of a metal rod.",
    "Explain what a linear transformation is by showing how a matrix rotates points.",
    "Explain the kernel of a linear transformation using a matrix that squashes all points onto a line.",
    "Explain the image of a linear transformation using T(x,y) = (x,0).",
    "Explain what an isomorphism is by showing that R^2 and the set of complex numbers behave the same algebraically.",
    "Explain what a metric space is using the idea of different distance formulas (Manhattan vs Euclidean).",
    "Explain continuity using a graph with no jumps or holes.",
    "Explain uniform continuity using f(x) = x^2 over the interval [0,1].",
    "Explain what a topology is using the example of open intervals on the real line.",
    "Explain what a compact set is using closed intervals like [a, b].",
    "Explain open and closed sets using the real line and simple intervals.",
    "Explain what a prime number is using factor trees.",
    "Explain the Fundamental Theorem of Arithmetic with the example 180 = 2^2·3^2·5.",
    "Explain modular arithmetic using a 12-hour clock.",
    "Explain congruences with the example 17 ≡ 5 (mod 12).",
    "Explain the gcd using gcd(36, 15).",
    "Explain the Euclidean algorithm using the steps for gcd(84, 30).",
    "Explain what a ring is using integers mod 6.",
    "Explain what a field is using rational numbers as an example.",
    "Explain what an ideal is using the multiples of 4 inside the integers.",
    "Explain quotient rings using Z/5Z as an example.",
    "Explain what a subgroup is using the even integers inside all integers.",
    "Explain Lagrange's theorem using subgroups of the group of cube rotations.",
    "Explain what a cyclic group is using the group generated by rotating a triangle.",
    "Explain S_n using the permutations of 3 students’ seating order.",
    "Explain what a normal subgroup is using integers inside rational numbers.",
    "Explain quotient groups using Z/2Z as flipping orientation.",
    "Explain what a group isomorphism is using (Z_6, +) and Z_2 × Z_3.",
    "Explain what a graph is using a map of cities connected by roads.",
    "Explain what a tree is using family tree structure.",
    "Explain what a connected graph is using subway stations and tunnels.",
    "Explain paths and cycles using walking routes around school buildings.",
    "Explain Eulerian vs Hamiltonian paths using examples of visiting hallways vs visiting rooms once.",
    "Explain what a spanning tree is using a network of computers.",
    "Explain adjacency matrices using a 4-node graph example.",
    "Explain what a probability density function is using a triangular distribution.",
    "Explain a cumulative distribution function using heights of students.",
    "Explain the law of large numbers using repeated coin flips.",
    "Explain the central limit theorem using the average of many small measurement errors.",
    "Explain what a Markov chain is using weather transitions (sunny→rainy→sunny…).",
    "Explain a transition matrix using a 3-state Markov chain of mood changes.",
    "Explain entropy using a probability distribution over letters in English.",
    "Explain mutual information using the relation between weather and umbrella usage.",
    "Explain convolution using blurring an image with a 3×3 filter.",
    "Explain convolution for signals using how echo mixes with the original audio.",
    "Explain the Z-transform using a discrete signal like 1, 2, 4, 8, …",
    "Explain the difference between Fourier series and Fourier transform using periodic vs non-periodic signals.",
    "Explain partial fraction decomposition using 1/(x^2 − 1).",
    "Explain orthogonality using dot products of (1,0) and (0,1).",
    "Explain what an inner product space is using the geometry of angles.",
    "Explain Gram–Schmidt by orthogonalizing (1,1) and (1,0).",
    "Explain projecting a vector onto a subspace using projection onto the x-axis.",
    "Explain what an eigenbasis is using diagonalizing a scaling matrix.",
    "Explain diagonalization using a matrix that stretches x but flips y."
]
random_question = random.choice(questions)

def generate_and_validate_code(prompt: str, job_id: str, max_attempts: int = 2) -> Tuple[str, list, str]:
    attempts_log = []
    request_id = None
    
    render_status[job_id]['message'] = 'Analyzing request...'
    analysis = analyze_request_type(prompt)
    attempts_log.append({'stage': 'analysis', 'data': analysis})
    
    if db and db.available:
        request_id = db.save_request(prompt, analysis)
        print(f"[DB] Saved request: {request_id}")
    
    render_status[job_id]['message'] = 'Creating animation plan...'
    plan = create_animation_plan(prompt, analysis)
    attempts_log.append({'stage': 'planning', 'success': True})
    
    for attempt in range(1, max_attempts + 1):
        print(f"\n[{job_id}] {'='*50}")
        print(f"[{job_id}] ATTEMPT {attempt}/{max_attempts}")
        print(f"[{job_id}] {'='*50}\n")
        
        attempt_start = time.time()
        
        render_status[job_id]['message'] = f'Generating code (attempt {attempt})...'
        
        code = generate_manim_code(prompt, analysis, plan, attempt)
        attempts_log.append({'attempt': attempt, 'stage': 'generation', 'success': True})
        
        render_status[job_id]['message'] = 'Self-reviewing...'
        code = self_critique_and_improve(code, prompt, analysis)
        attempts_log.append({'attempt': attempt, 'stage': 'critique', 'success': True})
        
        render_status[job_id]['message'] = 'Validating syntax...'
        syntax_valid, syntax_error = validate_python_syntax(code)
        
        if not syntax_valid:
            print(f"[{job_id}]  Syntax error: {syntax_error}")
            attempts_log.append({'attempt': attempt, 'stage': 'syntax', 'success': False, 'error': syntax_error})
            
            if db and db.available:
                db.record_error_pattern({
                    'category': 'syntax',
                    'signature': str(hash(syntax_error)),
                    'message': syntax_error,
                    'code_snippet': code[:200]
                })
            
            if attempt < max_attempts:
                code = polish_manim_code(code)
                syntax_valid_2, _ = validate_python_syntax(code)
                if syntax_valid_2:
                    print(f"[{job_id}]  Fixed")
                else:
                    continue
            else:
                raise Exception(f"Syntax error: {syntax_error}")
        
        attempts_log.append({'attempt': attempt, 'stage': 'syntax', 'success': True})
        


        render_status[job_id]['message'] = 'Looking for overlap...'
        code = overlapping_fix(code, prompt, analysis)
        attempts_log.append({'attempt': attempt, 'stage': 'overlapping', 'success': True})
        
        render_status[job_id]['message'] = 'Debuggin...'
        code = ai_fix(code, prompt, analysis)
        attempts_log.append({'attempt': attempt, 'stage': 'debugging', 'success': True})


        code = ensure_scene_class(code)
    
        structure_valid, structure_error = validate_manim_code(code)
        if not structure_valid:
            if attempt < max_attempts:
                code = polish_manim_code(code)
                continue
            else:
                raise Exception(f"Structure error: {structure_error}")
        
        attempts_log.append({'attempt': attempt, 'stage': 'structure', 'success': True})
        
        quality_passes, quality_feedback = check_code_quality(code)
        attempts_log.append({'attempt': attempt, 'stage': 'quality', 'success': quality_passes, 'feedback': quality_feedback})
        
        code = polish_manim_code(code)
        
        attempt_time = int((time.time() - attempt_start) * 1000)
        
        attempt_id = None
        if db and db.available and request_id:
            attempt_id = db.save_generation_attempt(request_id, {
                'attempt_number': attempt,
                'plan': plan,
                'code': code,
                'critique': code,
                'improved_code': code,
                'syntax_valid': syntax_valid,
                'syntax_error': syntax_error if not syntax_valid else None,
                'structure_valid': structure_valid,
                'warnings': quality_feedback,
                'generation_time_ms': attempt_time
            })
            print(f"[DB] Saved attempt: {attempt_id}") 

        return code, attempts_log, request_id, attempt_id  

def save_and_render(code: str, filename: str, job_id: str, request_id: str = None, prompt: str = "", attempt_id: str = None):
    print(f"\n[{job_id}] === RENDER STARTED ===")
    print(f"[{job_id}] request_id = {request_id}")
    print(f"[{job_id}] attempt_id = {attempt_id}")
    
    render_data = {
        'code': code,
        'status': 'pending',
        'started_at': datetime.now()
    }
    
    try:
        render_status[job_id]['status'] = 'rendering'
        render_status[job_id]['message'] = 'Rendering video...'
        
        script_path = MANIM_SCRIPTS / f"{filename}.py"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)
        
        render_data['script_path'] = str(script_path)
        print(f"[{job_id}] Script saved")
        
        cmd = [
            "manim",
            str(script_path),
            "GeneratedScene",
            "-pqh",
            "--media_dir", str(OUTPUTS),
            "--output_file", f"{filename}.mp4"
        ]
        
        start_render = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        render_duration = int(time.time() - start_render)
        
        render_data['return_code'] = result.returncode
        render_data['stdout'] = result.stdout
        render_data['stderr'] = result.stderr
        render_data['duration'] = render_duration
        render_data['completed_at'] = datetime.now()
        
        if result.returncode != 0:
            render_data['status'] = 'error'
            render_data['error_type'] = 'runtime'
            render_data['error_message'] = result.stderr[:2000]
            
            print(f"[{job_id}]  Render failed")
            print(f"[{job_id}] Attempting to save render job to DB...")  

            if db and db.available and request_id:
                print(f"[{job_id}] DB available: {db.available}, request_id: {request_id}")  
                try:
                    render_job_id = db.save_render_job(request_id, None, render_data)
                    print(f"[DB]  Saved FAILED render job: {render_job_id}")
                except Exception as e:
                    print(f"[DB]  Failed to save render job: {e}")
            else:
                print(f"[{job_id}] Skipping DB save - db={db}, available={db.available if db else None}, request_id={request_id}")  
            
            return
        
        video_path = find_video_file(filename)
        
        if video_path:
            render_status[job_id]['status'] = 'done'
            render_status[job_id]['video_file'] = video_path.name
            render_status[job_id]['message'] = 'Video ready!'
            render_data['status'] = 'done'
            render_data['video_path'] = str(video_path)
            
            print(f"[{job_id}]  SUCCESS - Video: {video_path}")
            
            render_job_id = None
            if db and db.available and request_id:
                render_job_id = db.save_render_job(request_id, attempt_id, render_data)  
                print(f"[DB] Saved render job: {render_job_id}")

            render_status[job_id]['message'] = 'Evaluating quality...'
            evaluation = evaluate_with_gpt4(code, str(video_path), prompt, {
                'status': 'done',
                'duration': render_duration,
                'error': None
            })
            
            if db and db.available and request_id and render_job_id:
                db.save_ai_evaluation(request_id, render_job_id, evaluation)
                print(f"[DB] Saved evaluation (score: {evaluation.get('overall', 0)})")
                
                if evaluation.get('overall', 0) >= 80:
                    print(f"[TRAINING] High-quality example candidate!")
            
        else:
            render_status[job_id]['status'] = 'error'
            render_status[job_id]['message'] = 'Video file not found'
            render_data['status'] = 'error'
            render_data['error_type'] = 'file_not_found'
            
    except subprocess.TimeoutExpired:
        render_status[job_id]['status'] = 'error'
        render_status[job_id]['message'] = 'Rendering timeout'
        render_data['status'] = 'timeout'
        render_data['error_type'] = 'timeout'
        print(f"[{job_id}]  TIMEOUT")
    except Exception as e:
        render_status[job_id]['status'] = 'error'
        render_status[job_id]['message'] = f'Error: {str(e)}'
        render_data['status'] = 'error'
        render_data['error_type'] = 'exception'
        render_data['error_message'] = str(e)
        print(f"[{job_id}]  Exception: {str(e)}")

def render_async(code: str, filename: str, job_id: str, request_id: str = None, prompt: str = "", attempt_id: str = None):
    thread = threading.Thread(
        target=save_and_render, 
        args=(code, filename, job_id, request_id, prompt, attempt_id)  # 6 arguments
    )
    thread.daemon = True
    thread.start()


def find_video_file(filename: str) -> Path:
    direct_path = OUTPUTS / f"{filename}.mp4"
    if direct_path.exists():
        return direct_path
    
    possible_paths = [
        OUTPUTS / "videos" / f"{filename}" / "1080p60" / "GeneratedScene.mp4",
        OUTPUTS / "videos" / "1080p60" / "GeneratedScene.mp4",
        OUTPUTS / f"{filename}" / "GeneratedScene.mp4",
        OUTPUTS / "GeneratedScene.mp4",
    ]
    
    for path in possible_paths:
        if path.exists():
            return path
    
    for mp4_file in OUTPUTS.rglob("*.mp4"):
        if filename in str(mp4_file) or "GeneratedScene" in str(mp4_file):
            return mp4_file
    
    return None

app = Flask(__name__)

job_to_request = {}


@app.route("/", methods=["GET", "POST"])
def index():
    job_id = None
    error = None
    
    if request.method == "POST":
        prompt = request.form.get("prompt")
        #while True:    
        if not prompt or not prompt.strip():
            error = "Please enter a prompt"
            return render_template("index.html", error=error)
        
        try:
            #random_question = random.choice(questions)
            #prompt = random_question
            job_id = str(uuid.uuid4())[:8]
            filename = f"video_{job_id}"
            
            print(f"\n{'#'*60}")
            print(f"[{job_id}] NEW REQUEST: {prompt}")
            print(f"{'#'*60}\n")
            
            render_status[job_id] = {
                'status': 'generating',
                'message': 'Analyzing and planning with RAG...',
                'video_file': ''
            }
            
            code, attempts_log, request_id, attempt_id = generate_and_validate_code(prompt, job_id, max_attempts=2)
            
            print(f"[{job_id}]  Got request_id: {request_id}")
            print(f"[{job_id}]  Got attempt_id: {attempt_id}")
            
            job_to_request[job_id] = {'request_id': request_id, 'prompt': prompt}
            
            render_async(code, filename, job_id, request_id, prompt, attempt_id)
            
        except Exception as e:
            error = f"Error: {str(e)}"
            print(f"[{job_id}]  ERROR: {error}")
            if job_id:
                render_status[job_id] = {
                    'status': 'error',
                    'message': error,
                    'video_file': ''
                }
            time.sleep(3)
    return render_template("index.html", job_id=job_id, error=error)

@app.route("/status/<job_id>")
def check_status(job_id):
    status = render_status.get(job_id, {'status': 'unknown', 'message': 'Job not found'})
    
    if status.get('status') == 'done' and db and db.available:
        pass
    
    return jsonify(status)

@app.route("/outputs/<path:filename>")
def download_file(filename):
    file_path = find_video_file(filename.replace('.mp4', ''))
    if file_path and file_path.exists():
        return send_from_directory(file_path.parent, file_path.name)
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
                    ROUND(CAST(AVG(CASE WHEN rj.status = 'done' THEN ae.overall_score END) AS numeric), 1) as avg_quality_score,
                    COUNT(DISTINCT ep.id) as unique_errors
                FROM requests r
                LEFT JOIN render_jobs rj ON r.id = rj.request_id
                LEFT JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                LEFT JOIN error_patterns ep ON true
            """)
            stats_data = cur.fetchone()
            
            cur.execute("""
                SELECT domain, COUNT(*) as count
                FROM requests
                GROUP BY domain
                ORDER BY count DESC
                LIMIT 5
            """)
            domains = cur.fetchall()
            
            return jsonify({
                "stats": stats_data,
                "top_domains": domains,
                "database_enabled": True
            })
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    print("\n" + "="*60)
    print("Manim AI Generator - PRODUCTION MODE")
    print("="*60)
    print("✓ GPT-4o with RAG (Golden Corpus)")
    print("✓ Layout safety helpers (auto-inject)")
    print("✓ Self-critique improvement loop")
    print("✓ AI evaluation (quality scoring)")
    print(f"✓ Database tracking: {'ENABLED' if USE_DATABASE else 'DISABLED'}")
    print("✓ Error pattern learning")
    print("✓ Scene management (no overlaps)")
    print("✓ Domain-specific guidance")
    print("="*60)
    print(f"Stats endpoint: http://localhost:5000/stats")
    print("="*60 + "\n")
    
    app.run(host='127.0.0.1', port=5000, debug=True, threaded=True, use_reloader=False)

