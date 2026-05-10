# Security Policy

## Reporting a vulnerability

If you believe you've found a security issue in NIMA, **please do not open a public GitHub issue**.

Instead, email the maintainer directly: **saparbayevskii@gmail.com**

Please include:

- A description of the issue and its potential impact.
- Steps to reproduce (minimal proof-of-concept is ideal).
- The commit SHA or version you tested against.
- Your preferred attribution (name / handle / anonymous) if the issue leads to a fix.

You should expect an acknowledgement within 72 hours. We'll work with you to confirm the issue, ship a fix, and coordinate disclosure. Responsible-disclosure reporters are credited in the changelog unless they ask otherwise.

## In scope

- **Arbitrary code execution** through prompts, uploaded templates, webhook payloads, or LTI launches.
- **Credential / secret exposure** (e.g. logs leaking API keys, session tokens written to disk, `.env` contents exposed via an endpoint).
- **Authentication / authorization bypass** of admin-only endpoints (those guarded by `NIMA_ADMIN_TOKEN`).
- **SSRF / path traversal** through any API that accepts a URL or file path from the user.
- **LTI 1.3 issues** — the integration is feature-flagged off by default (`NIMA_LTI_ENABLED=false`). If you're testing it with the flag on and find a signature / nonce / replay issue, please report.

## Out of scope

- Running untrusted prompt text through the LLM: NIMA is explicitly an **AI code generator**. Generated Manim code is executed in the server process to render videos. This is the project's whole job — it is not a sandbox. Deploy behind authentication and resource limits. Reports of "I asked NIMA to run `rm -rf /` and it tried" will be acknowledged but not treated as vulnerabilities.
- Denial-of-service through expensive renders or infinite-loop scenes. Use `RENDER_TIMEOUT_SECONDS` and rate limits; these are operational concerns, not vulnerabilities.
- Issues in vendored third-party content (`training/3b1b/`, `skills/`) — please report those upstream.
- Issues in external services NIMA calls (OpenAI, edge-tts, etc.) — report to the respective vendor.

## Operational posture

- Secrets (`OPENAI_API_KEY`, `DB_CONNECTION_STRING`, `NIMA_ADMIN_TOKEN`, etc.) are read only from environment variables. `.env` is gitignored and `.env.example` ships with empty values.
- No endpoint returns `.env` contents or raw environment variables.
- Admin endpoints refuse to serve when `NIMA_ADMIN_TOKEN` is unset (return 503 rather than defaulting to open).
- `config.py` fails fast at import time when `USE_DATABASE=true` is set without a `DB_CONNECTION_STRING` — no silent fall-through to an in-memory state when persistence was asked for.

If you're deploying NIMA and want a hardening review, feel free to reach out via the email above.
