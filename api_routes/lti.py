import secrets
import uuid
from urllib.parse import urlencode

from flask import Blueprint, jsonify, request


def create_lti_blueprint(*, db, request_json_object, get_job_status):
    bp = Blueprint("lti_api", __name__)
    lti_sessions: dict[str, dict] = {}

    @bp.route("/api/lti/login", methods=["GET", "POST"])
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

        lti_sessions[state] = {
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

        full_url = f"{auth_url}?{urlencode(params)}"
        return jsonify({"auth_url": full_url, "state": state})

    @bp.route("/api/lti/launch", methods=["POST"])
    def lti_launch():
        """LTI 1.3 launch handler."""
        id_token = request.form.get("id_token", "").strip()
        state = request.form.get("state", "").strip()

        if not id_token or not state:
            return jsonify({"error": "Missing id_token or state"}), 400

        session = lti_sessions.pop(state, None)
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

    @bp.route("/api/lti/embed/<job_id>", methods=["GET"])
    def lti_embed_video(job_id):
        """Get embed URL for a video in LMS."""
        status = get_job_status(job_id)
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

    @bp.route("/api/lti/config", methods=["GET"])
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

    @bp.route("/api/lti/platforms", methods=["POST"])
    def api_register_lti_platform():
        """Register a new LTI platform (admin)."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        data = request_json_object(force=False) if request.is_json else {}
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

    @bp.route("/api/lti/jwks", methods=["GET"])
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

    return bp
