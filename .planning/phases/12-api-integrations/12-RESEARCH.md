# Phase 12: API/Integrations - Research

**Phase:** 12  
**Name:** API/Integrations  
**Date:** 2026-04-05

## Domain Analysis

Phase 12 adds external integration capabilities to NIMA: webhooks, LMS integration, API key authentication, and enhanced batch processing.

## Requirements Coverage

| Requirement | Description |
|-------------|-------------|
| M3-API-01 | Webhook notifications - POST callback on render complete, configurable per request, retry logic |
| M3-API-02 | LMS integration API - Canvas LMS, Moodle integration, LTI support |
| M3-API-03 | Public API with key authentication - API key generation/management, rate limiting per key, usage tracking |
| M3-API-04 | Batch processing improvements - Enhanced batch endpoint, status polling, progress notifications |

## Current State Analysis

### Existing API Endpoints (app.py)
- `/api/generate` - POST, returns `{job_id}`, no auth, basic rate limiting by IP
- `/api/batch` - POST, accepts array of prompts, returns `{batch_id, jobs[]}`
- `/status/<job_id>` - GET, returns render status
- `/api/videos` - GET, list/search videos
- `/api/templates` - GET/POST/PUT/DELETE, template management

### Existing Infrastructure
- `check_rate_limit()` function in app.py (IP-based, 10 req/min)
- `render_status` dict (in-memory, per-process)
- `job_to_request` dict (in-memory, per-process)
- Database has `requests`, `render_jobs`, `videos` tables
- No API key system exists
- No webhook system exists
- No LMS integration exists

## Implementation Approach

### M3-API-01: Webhooks

**Design:**
- Add `webhook_url` field to `/api/generate` request body
- On render complete (success or failure), POST to webhook URL with job status
- Webhook payload: `{job_id, status, video_url, error?, timestamp}`
- Retry logic: 3 retries with exponential backoff (1s, 5s, 30s)
- Async delivery (non-blocking to render pipeline)

**Tables needed:**
```sql
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
    webhook_id UUID REFERENCES webhooks(id),
    job_id VARCHAR(50) NOT NULL,
    payload JSONB,
    status VARCHAR(20),
    attempts INTEGER DEFAULT 0,
    last_attempt_at TIMESTAMP,
    response_code INTEGER,
    response_body TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### M3-API-02: LMS Integration (LTI)

**LTI 1.3 Flow:**
1. LMS initiates launch request with OIDC login URL
2. NIMA handles authentication via LTI 1.3 platform
3. User context extracted from LTI claims
4. Embeddable video player URL generated

**Endpoints:**
- `GET /api/lti/login` - LTI login initiation
- `POST /api/lti/launch` - LTI launch handler
- `GET /api/lti/embed/<job_id>` - Get embed URL for LMS

**LTI Configuration stored in database:**
```sql
CREATE TABLE IF NOT EXISTS lti_platforms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100),
    issuer VARCHAR(255) UNIQUE,
    client_id VARCHAR(255),
    deployment_id VARCHAR(255),
    auth_endpoint VARCHAR(500),
    token_endpoint VARCHAR(500),
    jwks_endpoint VARCHAR(500),
    active BOOLEAN DEFAULT true
);
```

### M3-API-03: API Key Authentication

**Design:**
- API keys stored as hashed values in database
- Header: `Authorization: Bearer <api_key>` or `X-API-Key: <api_key>`
- Per-key rate limiting (overrides global IP limit)
- Usage tracking per key (request count, render count, quota)

**Tables:**
```sql
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
```

**Key Generation:**
- Format: `nima_<32-char-random-hex>` (e.g., `nima_a1b2c3d4e5f6789012345678901234ab`)
- Only prefix stored in DB, key shown once at creation

### M3-API-04: Enhanced Batch Processing

**Current batch limitations:**
- Returns immediately after queuing all jobs
- No batch-level status endpoint
- No progress notifications
- No webhook per batch

**Enhanced batch API:**
- `POST /api/batch` accepts `webhook_url` for batch notifications
- `GET /api/batch/<batch_id>` returns batch-level status
- Progress: `{batch_id, total, completed, failed, in_progress, progress_percent}`
- Individual job status via existing `/status/<job_id>`
- Batch webhook: sent when batch completes (all jobs done or first failure)

## Architecture Decisions

1. **Webhook delivery is async** - Uses background thread, non-blocking to render
2. **LTI is stateful** - Requires session storage for OIDC flow
3. **API keys use hashing** - bcrypt or SHA256, never store plain text
4. **Batch status is derived** - Query all jobs with matching `batch_id` from render_status

## Stack Considerations

- Flask already handles CORS
- Existing rate limiting uses in-memory dict (works for single instance)
- For production: Redis would help with cross-instance state
- Existing database already has all necessary connection handling

## Validation Architecture

For each feature, tests should verify:
- Webhook: Successful POST to valid URL, retry on failure, no blocking
- LMS: LTI launch flow completes, user context extracted correctly
- API Keys: Valid key grants access, invalid/revoked keys rejected, rate limits enforced
- Batch: Status reflects actual job states, progress updates correctly
