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

CREATE TABLE IF NOT EXISTS user_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    domain VARCHAR(50) NOT NULL,
    slots JSONB NOT NULL,
    beats INTEGER NOT NULL,
    notes TEXT,
    code_pattern TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    submitted_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_user_template_domain ON user_templates(domain);
CREATE INDEX idx_user_template_status ON user_templates(status);

CREATE TABLE IF NOT EXISTS fine_tune_candidates (
    id SERIAL PRIMARY KEY,
    prompt TEXT NOT NULL,
    code TEXT NOT NULL,
    score INTEGER,
    domain VARCHAR(50),
    used_in_finetune BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_finetune_score ON fine_tune_candidates(score);
CREATE INDEX idx_finetune_domain ON fine_tune_candidates(domain);

CREATE TABLE IF NOT EXISTS videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    render_job_id UUID REFERENCES render_jobs(id) ON DELETE CASCADE,
    request_id UUID REFERENCES requests(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    original_path VARCHAR(500) NOT NULL,
    organized_path VARCHAR(500) NOT NULL,
    file_size_bytes BIGINT,
    duration_seconds FLOAT,
    resolution VARCHAR(20),
    domain VARCHAR(50),
    prompt TEXT,
    cdn_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP
);
CREATE INDEX idx_videos_domain ON videos(domain);
CREATE INDEX idx_videos_created ON videos(created_at);
CREATE INDEX idx_videos_render_job ON videos(render_job_id);

CREATE TABLE IF NOT EXISTS webhooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255),
    url VARCHAR(500) NOT NULL,
    secret VARCHAR(255),
    events TEXT[] DEFAULT ARRAY['render.complete', 'render.error'],
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    webhook_id UUID REFERENCES webhooks(id) ON DELETE CASCADE,
    job_id VARCHAR(50) NOT NULL,
    payload JSONB,
    status VARCHAR(20),
    attempts INTEGER DEFAULT 0,
    last_attempt_at TIMESTAMP,
    response_code INTEGER,
    response_body TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255),
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    key_prefix VARCHAR(8),
    name VARCHAR(100),
    rate_limit INTEGER DEFAULT 60,
    daily_quota INTEGER,
    requests_today INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key_id UUID REFERENCES api_keys(id),
    endpoint VARCHAR(100),
    method VARCHAR(10),
    status_code INTEGER,
    response_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lti_platforms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100),
    issuer VARCHAR(255) UNIQUE NOT NULL,
    client_id VARCHAR(255),
    deployment_id VARCHAR(255),
    auth_endpoint VARCHAR(500),
    token_endpoint VARCHAR(500),
    jwks_endpoint VARCHAR(500),
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS batches (
    id VARCHAR(50) PRIMARY KEY,
    total_jobs INTEGER DEFAULT 0,
    completed_jobs INTEGER DEFAULT 0,
    failed_jobs INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'in_progress',
    webhook_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_webhook_deliveries_job ON webhook_deliveries(job_id);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_prefix ON api_keys(key_prefix);
CREATE INDEX idx_api_usage_key ON api_usage(api_key_id);
CREATE INDEX idx_lti_issuer ON lti_platforms(issuer);