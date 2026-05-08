from flask import Blueprint, jsonify, request

from api_routes.admin_auth import require_admin


def create_webhooks_blueprint(*, db, request_json_object):
    bp = Blueprint("webhooks_api", __name__)

    @bp.route("/api/webhooks", methods=["POST"])
    @require_admin
    def api_create_webhook():
        """Register a new webhook."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        data = request_json_object(force=False) if request.is_json else {}
        url = data.get("url", "").strip()
        secret = data.get("secret")
        events = data.get("events", ["render.complete", "render.error"])

        if not url or not url.startswith(("http://", "https://")):
            return jsonify({"error": "Valid URL required"}), 400

        try:
            wid = db.save_webhook(user_id=None, url=url, secret=secret, events=events)
            return jsonify({"webhook_id": wid, "message": "Webhook registered"}), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/webhooks", methods=["GET"])
    @require_admin
    def api_list_webhooks():
        """List registered webhooks."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        try:
            webhooks = (
                db._exec(
                    "SELECT id, url, events, active, created_at FROM webhooks",
                    fetch="all",
                )
                or []
            )
            return jsonify({"webhooks": [dict(w) for w in webhooks]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/webhooks/<webhook_id>", methods=["DELETE"])
    @require_admin
    def api_delete_webhook(webhook_id):
        """Delete a webhook."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        try:
            db._exec("UPDATE webhooks SET active=false WHERE id=%s", (webhook_id,))
            return jsonify({"deleted": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return bp
