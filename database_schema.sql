CREATE TABLE IF NOT EXISTS requests (
    id UUID PRIMARY KEY,
    prompt TEXT NOT NULL,
    user_id VARCHAR(255),
    topic VARCHAR(255),
    domain VARCHAR(50),
    complexity VARCHAR(20),
    estimated_duration INTEGER,
    analysis_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_requests_domain ON requests(domain);
CREATE INDEX idx_requests_created ON requests(created_at);

CREATE TABLE IF NOT EXISTS generation_attempts (
    id UUID PRIMARY KEY,
    request_id UUID REFERENCES requests(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    model_version VARCHAR(50) DEFAULT 'gpt-4o',
    animation_plan TEXT,
    generated_code TEXT NOT NULL,
    code_length INTEGER,
    critique_feedback TEXT,
    improved_code TEXT,
    syntax_valid BOOLEAN,
    syntax_error TEXT,
    structure_valid BOOLEAN,
    quality_warnings JSONB,
    generation_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_attempts_request ON generation_attempts(request_id);

CREATE TABLE IF NOT EXISTS render_jobs (
    id UUID PRIMARY KEY,
    request_id UUID REFERENCES requests(id) ON DELETE CASCADE,
    attempt_id UUID REFERENCES generation_attempts(id),
    final_code TEXT NOT NULL,
    script_path VARCHAR(500),
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    render_duration_seconds INTEGER,
    manim_stdout TEXT,
    manim_stderr TEXT,
    return_code INTEGER,
    video_path VARCHAR(500),
    error_type VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_render_request ON render_jobs(request_id);
CREATE INDEX idx_render_status ON render_jobs(status);

CREATE TABLE IF NOT EXISTS ai_evaluations (
    id UUID PRIMARY KEY,
    request_id UUID REFERENCES requests(id) ON DELETE CASCADE,
    render_job_id UUID REFERENCES render_jobs(id) ON DELETE CASCADE,
    evaluator_model VARCHAR(50) DEFAULT 'gpt-4o',
    visual_quality_score FLOAT,
    educational_value_score FLOAT,
    technical_accuracy_score FLOAT,
    pacing_timing_score FLOAT,
    clarity_score FLOAT,
    engagement_score FLOAT,
    overall_score FLOAT,
    strengths TEXT,
    weaknesses TEXT,
    specific_issues JSONB,
    suggestions TEXT,
    predicted_satisfaction FLOAT,
    full_evaluation_json JSONB,
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_eval_overall ON ai_evaluations(overall_score);
CREATE INDEX idx_eval_request ON ai_evaluations(request_id);

CREATE TABLE IF NOT EXISTS error_patterns (
    id UUID PRIMARY KEY,
    error_category VARCHAR(100),
    error_signature TEXT UNIQUE,
    example_error_message TEXT,
    example_code_snippet TEXT,
    root_cause TEXT,
    fix_description TEXT,
    occurrence_count INTEGER DEFAULT 1,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved BOOLEAN DEFAULT FALSE
);
CREATE INDEX idx_error_category ON error_patterns(error_category);
CREATE INDEX idx_error_count ON error_patterns(occurrence_count);

CREATE TABLE IF NOT EXISTS training_examples (
    id UUID PRIMARY KEY,
    request_id UUID REFERENCES requests(id),
    render_job_id UUID REFERENCES render_jobs(id),
    is_positive_example BOOLEAN NOT NULL,
    quality_tier VARCHAR(20),
    combined_score FLOAT,
    used_in_training BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_training_quality ON training_examples(quality_tier);
CREATE INDEX idx_training_score ON training_examples(combined_score);