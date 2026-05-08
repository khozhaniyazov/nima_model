import hashlib
import secrets
from functools import wraps

from flask import Blueprint, jsonify, request

from api_routes.admin_auth import require_admin


def create_api_keys_blueprint(*, db, check_rate_limit, request_json_object):
    bp = Blueprint("api_keys", __name__)

    def require_api_key(f):
        """Decorator to require API key authentication."""

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

    @bp.route("/api/keys", methods=["POST"])
    @require_admin
    def api_create_api_key():
        """Create a new API key (admin)."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        data = request_json_object(force=False) if request.is_json else {}
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

    @bp.route("/api/keys", methods=["GET"])
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

    @bp.route("/api/keys/<key_id>", methods=["DELETE"])
    @require_admin
    def api_revoke_api_key(key_id):
        """Revoke an API key (admin).

        Previously gated only by ``require_api_key``. Because the legacy
        ``require_api_key`` decorator accepts *any* non-revoked key and
        performs no ownership check, any holder of any API key could revoke
        any other key — a denial-of-service / lockout primitive. Promoting
        this to admin-only matches ``POST /api/keys`` and closes that gap.
        """
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        try:
            db._exec("UPDATE api_keys SET revoked_at=NOW() WHERE id=%s", (key_id,))
            return jsonify({"revoked": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return bp
