from flask import Blueprint, jsonify
from psycopg2.extras import Json, RealDictCursor


def create_templates_blueprint(db, request_json_object):
    bp = Blueprint("templates_api", __name__)

    @bp.route("/api/templates", methods=["GET"])
    def api_list_templates():
        """List approved user templates."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"})
        try:
            with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, name, domain, slots, beats, notes, code_pattern, created_at
                    FROM user_templates
                    WHERE status = 'approved'
                    ORDER BY created_at DESC
                """)
                templates = [dict(r) for r in cur.fetchall()]
            return jsonify({"templates": templates})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/render-templates", methods=["GET"])
    def api_list_render_templates():
        """List curated backend render templates for streaming pipeline."""
        try:
            from algorithms.streaming import VISUAL_TEMPLATES

            return jsonify(
                {"templates": [{"id": k, **v} for k, v in VISUAL_TEMPLATES.items()]}
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/templates", methods=["POST"])
    def api_submit_template():
        """Submit a new user template."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"})
        try:
            data = request_json_object(force=True)
            name = data.get("name", "").strip()
            domain = data.get("domain", "").strip()
            slots = data.get("slots", [])
            beats = data.get("beats", 5)
            notes = data.get("notes", "")
            code_pattern = data.get("code_pattern", "")
            submitted_by = data.get("submitted_by", "anonymous")

            if not name or not domain:
                return jsonify({"error": "name and domain are required"}), 400

            with db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_templates (name, domain, slots, beats, notes, code_pattern, status, submitted_by)
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)
                    RETURNING id
                """,
                    (
                        name,
                        domain,
                        Json(slots),
                        beats,
                        notes,
                        code_pattern,
                        submitted_by,
                    ),
                )
                template_id = cur.fetchone()[0]
                db.conn.commit()

            return jsonify(
                {
                    "id": template_id,
                    "status": "pending",
                    "message": "Template submitted for review",
                }
            ), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/templates/pending", methods=["GET"])
    def api_pending_templates():
        """List pending templates (admin)."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"})
        try:
            with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, name, domain, slots, beats, notes, submitted_by, created_at
                    FROM user_templates
                    WHERE status = 'pending'
                    ORDER BY created_at DESC
                """)
                templates = [dict(r) for r in cur.fetchall()]
            return jsonify({"templates": templates})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/templates/<int:template_id>/approve", methods=["PUT"])
    def api_approve_template(template_id):
        """Approve a user template (admin)."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"})
        try:
            with db.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE user_templates SET status = 'approved'
                    WHERE id = %s AND status = 'pending'
                    RETURNING id
                """,
                    (template_id,),
                )
                result = cur.fetchone()
                db.conn.commit()

            if result:
                return jsonify({"id": template_id, "status": "approved"})
            return jsonify({"error": "Template not found or already approved"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/templates/<int:template_id>", methods=["DELETE"])
    def api_delete_template(template_id):
        """Delete a user template (admin)."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"})
        try:
            with db.conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM user_templates WHERE id = %s RETURNING id",
                    (template_id,),
                )
                result = cur.fetchone()
                db.conn.commit()

            if result:
                return jsonify({"id": template_id, "deleted": True})
            return jsonify({"error": "Template not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return bp
