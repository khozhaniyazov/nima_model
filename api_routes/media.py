from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory
from psycopg2.extras import RealDictCursor


VIDEO_SORT_COLUMNS = {
    "created_at": "v.created_at",
    "filename": "v.filename",
    "file_size_bytes": "v.file_size_bytes",
    "duration_seconds": "v.duration_seconds",
    "domain": "v.domain",
    "overall_score": "ae.overall_score",
}


def _bounded_int(value: int | None, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        value = default
    return min(max(value, minimum), maximum)


def _local_output_url(organized_path: str | None) -> str | None:
    if not organized_path:
        return None
    return f"/outputs/{Path(organized_path).name}"


def _safe_output_stem(filename: str) -> str | None:
    normalized = (filename or "").replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    if not name or name != normalized or name in {".", ".."}:
        return None
    if any(ch in name for ch in '<>:"|?*'):
        return None

    path = Path(name)
    if path.suffix and path.suffix.lower() != ".mp4":
        return None
    return path.stem if path.suffix else path.name


def _cdn_url_for_path(organized_path: str, outputs: Path, cdn_base_url: str) -> str:
    video_path = Path(organized_path)
    try:
        rel_path = video_path.resolve().relative_to(outputs.resolve())
    except (OSError, ValueError):
        rel_path = Path(video_path.name)
    return f"{cdn_base_url.rstrip('/')}/{rel_path.as_posix()}"


def create_media_blueprint(
    *,
    db,
    request_json_object,
    find_video_file,
    outputs: Path,
    cdn_enabled: bool,
    cdn_base_url: str,
):
    bp = Blueprint("media_api", __name__)

    @bp.route("/outputs/<path:filename>")
    def download_file(filename):
        base = _safe_output_stem(filename)
        if not base:
            return "Video not found", 404
        video_path = find_video_file(base, max_age_seconds=None)
        if video_path and video_path.exists():
            try:
                resolved_path = video_path.resolve()
                resolved_path.relative_to(outputs.resolve())
            except (OSError, ValueError):
                return "Video not found", 404
            return send_from_directory(resolved_path.parent, resolved_path.name)
        return "Video not found", 404

    @bp.route("/stats")
    def stats():
        if not db or not db.available:
            return jsonify({"error": "Database not available"})
        try:
            with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(DISTINCT r.id) as total_requests,
                        COUNT(DISTINCT CASE WHEN rj.status = 'done' THEN rj.id END) as successful_renders,
                        ROUND(CAST(AVG(CASE WHEN rj.status='done' THEN ae.overall_score END) AS numeric), 1) as avg_quality_score,
                        COUNT(DISTINCT ep.id) as unique_error_patterns,
                        COUNT(DISTINCT CASE WHEN rj.status='done' THEN rj.id END) * 100.0 / NULLIF(COUNT(DISTINCT r.id), 0) as success_rate
                    FROM requests r
                    LEFT JOIN render_jobs rj ON r.id = rj.request_id
                    LEFT JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                    LEFT JOIN error_patterns ep ON true
                """)
                stats_data = dict(cur.fetchone())

                cur.execute("""
                    SELECT domain, COUNT(*) as count
                    FROM requests GROUP BY domain ORDER BY count DESC LIMIT 5
                """)
                domains = [dict(r) for r in cur.fetchall()]

                cur.execute("""
                    SELECT
                        ROUND(CAST(AVG(ae.layout_quality) AS numeric), 1) as avg_layout,
                        ROUND(CAST(AVG(ae.educational_value) AS numeric), 1) as avg_educational,
                        ROUND(CAST(AVG(ae.technical_accuracy) AS numeric), 1) as avg_technical,
                        ROUND(CAST(AVG(ae.pacing) AS numeric), 1) as avg_pacing,
                        ROUND(CAST(AVG(ae.manim_quality) AS numeric), 1) as avg_manim
                    FROM ai_evaluations ae
                    WHERE ae.overall_score IS NOT NULL
                """)
                quality_dims = dict(cur.fetchone() or {})

                cur.execute("""
                    SELECT
                        COUNT(CASE WHEN overall_score >= 80 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) as pct_80_plus,
                        COUNT(CASE WHEN overall_score >= 70 AND overall_score < 80 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) as pct_70_79,
                        COUNT(CASE WHEN overall_score >= 60 AND overall_score < 70 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) as pct_60_69,
                        COUNT(CASE WHEN overall_score < 60 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) as pct_below_60
                    FROM ai_evaluations
                """)
                quality_dist = dict(cur.fetchone() or {})

                cur.execute("""
                    SELECT error_category, root_cause, fix_description, occurrence_count
                    FROM error_patterns
                    WHERE NOT resolved
                    ORDER BY occurrence_count DESC LIMIT 5
                """)
                error_patterns = [dict(r) for r in cur.fetchall()]

                cur.execute("""
                    SELECT MAX(rj.completed_at) as last_render_at,
                           COUNT(CASE WHEN DATE(rj.completed_at) = CURRENT_DATE THEN 1 END) as renders_today,
                           ROUND(AVG(rj.render_duration_seconds), 1) as avg_render_duration
                    FROM render_jobs rj
                    WHERE rj.status = 'done'
                """)
                render_meta = dict(cur.fetchone() or {})

            return jsonify(
                {
                    "stats": stats_data,
                    "quality_dims": quality_dims,
                    "quality_tiers": quality_dist,
                    "top_domains": domains,
                    "top_errors": error_patterns,
                    "last_render_at": render_meta.get("last_render_at"),
                    "renders_today": render_meta.get("renders_today", 0),
                    "avg_render_duration": render_meta.get("avg_render_duration"),
                    "database_enabled": True,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)})

    @bp.route("/stats/top-examples")
    def stats_top_examples():
        """Get highest scoring examples for showcase."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"})
        try:
            with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT r.prompt, r.domain, r.topic,
                           ae.overall_score, ae.visual_quality_score,
                           ae.educational_value_score, ae.pacing,
                           rj.video_path, rj.created_at
                    FROM requests r
                    JOIN render_jobs rj ON r.id = rj.request_id
                    JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                    WHERE rj.status = 'done' AND ae.overall_score >= 80
                    ORDER BY ae.overall_score DESC
                    LIMIT 10
                """)
                examples = [dict(r) for r in cur.fetchall()]
            return jsonify({"top_examples": examples})
        except Exception as e:
            return jsonify({"error": str(e)})

    @bp.route("/api/videos", methods=["GET"])
    def list_videos():
        """List videos with pagination and filtering."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        page = _bounded_int(
            request.args.get("page", 1, type=int),
            default=1,
            minimum=1,
            maximum=100000,
        )
        per_page = _bounded_int(
            request.args.get("per_page", 20, type=int),
            default=20,
            minimum=1,
            maximum=100,
        )
        domain = request.args.get("domain")
        search = request.args.get("search")
        sort_by = request.args.get("sort_by", "created_at")
        sort_order = request.args.get("sort_order", "desc").lower()

        offset = (page - 1) * per_page

        try:
            with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
                base_query = """
                    SELECT v.id, v.filename, v.organized_path, v.file_size_bytes,
                           v.duration_seconds, v.resolution, v.domain, v.cdn_url,
                           v.created_at, r.prompt, r.topic,
                           rj.status as render_status, ae.overall_score
                    FROM videos v
                    JOIN render_jobs rj ON v.render_job_id = rj.id
                    JOIN requests r ON v.request_id = r.id
                    LEFT JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                    WHERE v.id IS NOT NULL
                """
                params = []

                if domain:
                    base_query += " AND v.domain = %s"
                    params.append(domain)

                if search:
                    base_query += " AND r.prompt ILIKE %s"
                    params.append(f"%{search}%")

                count_query = f"SELECT COUNT(*) FROM ({base_query}) sub"
                cur.execute(count_query, params)
                total = cur.fetchone()["count"]

                order_col = VIDEO_SORT_COLUMNS.get(sort_by, "v.created_at")
                sort_dir = "ASC" if sort_order == "asc" else "DESC"
                base_query += f" ORDER BY {order_col} {sort_dir}"
                base_query += " LIMIT %s OFFSET %s"
                params.extend([per_page, offset])

                cur.execute(base_query, params)
                videos = [dict(r) for r in cur.fetchall()]

            return jsonify(
                {
                    "videos": videos,
                    "total": total,
                    "page": page,
                    "per_page": per_page,
                    "pages": (total + per_page - 1) // per_page,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/videos/<video_id>", methods=["GET"])
    def get_video(video_id):
        """Get single video details."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        try:
            with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT v.*, r.prompt, r.topic, r.domain,
                           rj.status as render_status, ae.overall_score
                    FROM videos v
                    JOIN render_jobs rj ON v.render_job_id = rj.id
                    JOIN requests r ON v.request_id = r.id
                    LEFT JOIN ai_evaluations ae ON rj.id = ae.render_job_id
                    WHERE v.id = %s
                """,
                    (video_id,),
                )
                video = cur.fetchone()

            if not video:
                return jsonify({"error": "Video not found"}), 404

            return jsonify(dict(video))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/videos/search", methods=["GET"])
    def search_videos():
        """Search videos by prompt text."""
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"error": "Query parameter 'q' is required"}), 400

        limit = _bounded_int(
            request.args.get("limit", 10, type=int),
            default=10,
            minimum=1,
            maximum=50,
        )

        try:
            with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT v.id, v.filename, v.organized_path, v.domain,
                           v.created_at, r.prompt, ae.overall_score
                    FROM videos v
                    JOIN requests r ON v.request_id = r.id
                    LEFT JOIN ai_evaluations ae ON v.render_job_id = ae.render_job_id
                    WHERE r.prompt ILIKE %s
                    ORDER BY v.created_at DESC
                    LIMIT %s
                """,
                    (f"%{query}%", limit),
                )
                results = [dict(r) for r in cur.fetchall()]

            return jsonify({"results": results, "query": query})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/videos/cdn-url/<video_id>", methods=["GET"])
    def get_video_cdn_url(video_id):
        """
        Get CDN URL for a video.
        If CDN is not configured, returns the local /outputs URL.
        """
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        try:
            with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, organized_path, cdn_url
                    FROM videos
                    WHERE id = %s
                """,
                    (video_id,),
                )

                video = cur.fetchone()
                if not video:
                    return jsonify({"error": "Video not found"}), 404

                if video.get("cdn_url"):
                    return jsonify(
                        {
                            "video_id": video_id,
                            "url": video["cdn_url"],
                            "source": "stored",
                        }
                    )

                organized_path = video.get("organized_path")
                if cdn_enabled and cdn_base_url and organized_path:
                    cdn_url = _cdn_url_for_path(organized_path, outputs, cdn_base_url)
                    cur.execute(
                        "UPDATE videos SET cdn_url = %s WHERE id = %s",
                        (cdn_url, video_id),
                    )
                    db.conn.commit()

                    return jsonify(
                        {"video_id": video_id, "url": cdn_url, "source": "generated"}
                    )

                local_url = _local_output_url(organized_path)
                if not local_url:
                    return jsonify({"error": "Video file path unavailable"}), 404
                return jsonify({"video_id": video_id, "url": local_url, "source": "local"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/videos/cdn-url", methods=["POST"])
    def set_video_cdn_url():
        """
        Manually set CDN URL for a video (admin endpoint).
        """
        if not db or not db.available:
            return jsonify({"error": "Database not available"}), 503

        data = request_json_object(force=False) if request.is_json else {}
        video_id = data.get("video_id")
        cdn_url = data.get("cdn_url")

        if not video_id or not cdn_url:
            return jsonify({"error": "video_id and cdn_url required"}), 400

        try:
            with db.conn.cursor() as cur:
                cur.execute(
                    "UPDATE videos SET cdn_url = %s WHERE id = %s", (cdn_url, video_id)
                )
                if cur.rowcount == 0:
                    db.conn.rollback()
                    return jsonify({"error": "Video not found"}), 404

                db.conn.commit()
                return jsonify(
                    {"success": True, "video_id": video_id, "cdn_url": cdn_url}
                )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return bp
