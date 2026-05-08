"""
Admin authentication for privileged `/api/*` endpoints.

Admin auth uses a single shared token supplied via the ``NIMA_ADMIN_TOKEN``
environment variable. Requests must send the same value in an
``X-Admin-Token`` header (``Authorization: Bearer <token>`` is also accepted
for curl/CI convenience).

Rationale for the single-shared-token approach:

- NIMA is a closed-source internal deployment, not a multi-tenant product.
- The existing ``api_keys`` table is per-user and already has a
  chicken-and-egg problem (``POST /api/keys`` is itself an admin endpoint),
  so bootstrapping without an env-var token is impossible anyway.
- Rotation is a single env change + redeploy.

If ``NIMA_ADMIN_TOKEN`` is unset or empty, every admin endpoint returns 503
``{"error": "Admin auth not configured"}``. This is intentional: a missing
token must not silently open the endpoints, and it must not crash the app on
import either.

See issue #42 and ``.planning/codebase/CONCERNS.md`` for context.
"""

from __future__ import annotations

import hmac
import os
from functools import wraps

from flask import jsonify, request


_ENV_VAR = "NIMA_ADMIN_TOKEN"


def _configured_token() -> str:
    """Return the configured admin token, or empty string if unset."""
    return (os.environ.get(_ENV_VAR) or "").strip()


def _presented_token() -> str:
    """Extract the admin token from request headers."""
    header = request.headers.get("X-Admin-Token")
    if header:
        return header.strip()
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()
    return ""


def require_admin(f):
    """Gate a Flask view behind ``NIMA_ADMIN_TOKEN``.

    Responses:
    - 503 ``Admin auth not configured`` when the env var is missing/empty.
    - 401 ``Admin authentication required`` when the header is missing.
    - 403 ``Invalid admin token`` when the header value does not match.

    The constant-time comparison guards against timing oracles.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        expected = _configured_token()
        if not expected:
            return jsonify({"error": "Admin auth not configured"}), 503

        presented = _presented_token()
        if not presented:
            return jsonify({"error": "Admin authentication required"}), 401

        if not hmac.compare_digest(expected, presented):
            return jsonify({"error": "Invalid admin token"}), 403

        return f(*args, **kwargs)

    return decorated


__all__ = ["require_admin"]
