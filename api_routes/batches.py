from flask import Blueprint, jsonify


def create_batches_blueprint(*, job_state, list_statuses):
    bp = Blueprint("batches_api", __name__)

    @bp.route("/api/batch/<batch_id>", methods=["GET"])
    def api_batch_status(batch_id):
        """Get batch status and progress."""
        return jsonify(job_state.batch_summary(batch_id).as_dict())

    @bp.route("/api/batch/<batch_id>/jobs", methods=["GET"])
    def api_batch_jobs(batch_id):
        """Get all jobs in a batch with their status."""
        batch_jobs = [
            {"job_id": jid, **status}
            for jid, status in list_statuses()
            if status.get("batch_id") == batch_id
        ]
        return jsonify({"batch_id": batch_id, "jobs": batch_jobs})

    return bp
