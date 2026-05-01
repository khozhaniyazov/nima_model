"""API route wiring and hardening checks."""
import os
import tempfile
from pathlib import Path

os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["USE_DATABASE"] = "false"
os.environ["JOB_STATE_PERSISTENCE"] = "false"


def test_real_app_routes_registered():
    import app

    factory_app = app.create_app()
    paths = {str(rule) for rule in factory_app.url_map.iter_rules()}
    expected_paths = {
        "/",
        "/status/<job_id>",
        "/api/generate",
        "/api/prompts",
        "/api/batch",
        "/health",
        "/api/render-templates",
        "/api/templates",
        "/api/templates/pending",
        "/outputs/<path:filename>",
        "/stats",
        "/stats/top-examples",
        "/api/videos",
        "/api/videos/<video_id>",
        "/api/videos/search",
        "/api/videos/cdn-url",
        "/api/videos/cdn-url/<video_id>",
        "/api/keys",
        "/api/keys/<key_id>",
        "/api/webhooks",
        "/api/webhooks/<webhook_id>",
        "/api/batch/<batch_id>",
        "/api/batch/<batch_id>/jobs",
        "/api/lti/login",
        "/api/lti/launch",
        "/api/lti/embed/<job_id>",
        "/api/lti/config",
        "/api/lti/platforms",
        "/api/lti/jwks",
    }

    missing = expected_paths - paths
    assert not missing, f"Missing routes: {sorted(missing)}"
    print(f"[OK] API route registration — {len(expected_paths)} routes present")


def test_health_reports_background_threads():
    import app

    response = app.app.test_client().get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["database"] is False
    assert "background_threads" in payload
    assert "background_running" in payload
    assert "background_queued" in payload
    print("[OK] health route — reports database and background worker counts")


class _FakeCursor:
    def __init__(self):
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, list(params or [])))

    def fetchone(self):
        return {"count": 0}

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self):
        self.cursor_obj = _FakeCursor()

    def cursor(self, *args, **kwargs):
        return self.cursor_obj


class _FakeDb:
    available = True

    def __init__(self):
        self.conn = _FakeConn()


def test_video_listing_rejects_sort_injection():
    from flask import Flask

    from api_routes.media import create_media_blueprint

    fake_db = _FakeDb()
    flask_app = Flask(__name__)
    flask_app.register_blueprint(
        create_media_blueprint(
            db=fake_db,
            request_json_object=lambda **_: {},
            find_video_file=lambda *_, **__: None,
            outputs=Path("outputs"),
            cdn_enabled=False,
            cdn_base_url="",
        )
    )

    response = flask_app.test_client().get(
        "/api/videos?sort_by=created_at;DROP TABLE videos&sort_order=asc&page=0&per_page=500"
    )
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["page"] == 1
    assert payload["per_page"] == 100

    list_query = fake_db.conn.cursor_obj.executed[-1][0]
    assert "DROP TABLE" not in list_query
    assert "ORDER BY v.created_at ASC" in list_query
    print("[OK] API videos — sort column whitelisted and pagination clamped")


def test_outputs_rejects_path_traversal_before_lookup():
    from flask import Flask

    from api_routes.media import create_media_blueprint

    lookups = []
    flask_app = Flask(__name__)
    flask_app.register_blueprint(
        create_media_blueprint(
            db=None,
            request_json_object=lambda **_: {},
            find_video_file=lambda name, **_: lookups.append(name) or None,
            outputs=Path("outputs"),
            cdn_enabled=False,
            cdn_base_url="",
        )
    )

    response = flask_app.test_client().get("/outputs/%2e%2e%2fsecret.mp4")

    assert response.status_code == 404
    assert lookups == []
    print("[OK] outputs route — rejects path traversal before file lookup")


def test_outputs_rejects_discovered_file_outside_outputs():
    from flask import Flask

    from api_routes.media import create_media_blueprint

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        outputs = root / "outputs"
        outside = root / "outside.mp4"
        outputs.mkdir()
        outside.write_bytes(b"not-a-real-video")

        flask_app = Flask(__name__)
        flask_app.register_blueprint(
            create_media_blueprint(
                db=None,
                request_json_object=lambda **_: {},
                find_video_file=lambda *_, **__: outside,
                outputs=outputs,
                cdn_enabled=False,
                cdn_base_url="",
            )
        )

        response = flask_app.test_client().get("/outputs/video.mp4")

    assert response.status_code == 404
    print("[OK] outputs route — rejects discovered files outside outputs")


if __name__ == "__main__":
    test_real_app_routes_registered()
    test_health_reports_background_threads()
    test_video_listing_rejects_sort_injection()
    test_outputs_rejects_path_traversal_before_lookup()
    test_outputs_rejects_discovered_file_outside_outputs()
    print("\nALL API ROUTE CHECKS PASSED")
