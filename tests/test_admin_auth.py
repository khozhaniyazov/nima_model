"""Tests for the ``require_admin`` decorator and all endpoints gated by it (#42).

The shared-token admin auth introduced in #42 guards ten endpoints that were
previously unauthenticated despite being labelled ``admin`` in their
docstrings. These tests pin:

1. The decorator itself (503 when env var unset, 401 when header missing,
   403 when header wrong, 200 when header matches).
2. Every gated route returns 401/403 without a valid admin token, even
   when the database is available.

Routes covered:
- ``POST /api/keys``
- ``GET  /api/templates/pending``
- ``PUT  /api/templates/<id>/approve``
- ``DELETE /api/templates/<id>``
- ``POST /api/webhooks``
- ``GET  /api/webhooks``
- ``DELETE /api/webhooks/<id>``
- ``POST /api/videos/cdn-url``
- ``POST /api/lti/platforms`` (in addition to the LTI feature flag)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from api_routes.admin_auth import require_admin
from api_routes.api_keys import create_api_keys_blueprint
from api_routes.lti import create_lti_blueprint
from api_routes.media import create_media_blueprint
from api_routes.templates import create_templates_blueprint
from api_routes.webhooks import create_webhooks_blueprint


# ─── Decorator-level tests ──────────────────────────────────────────────────


def _make_decorator_app():
    app = Flask(__name__)

    @app.route("/probe", methods=["GET", "POST"])
    @require_admin
    def probe():
        return {"ok": True}

    return app


def test_decorator_503_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("NIMA_ADMIN_TOKEN", raising=False)
    response = _make_decorator_app().test_client().get("/probe")
    assert response.status_code == 503
    assert response.get_json() == {"error": "Admin auth not configured"}


def test_decorator_503_when_env_var_empty(monkeypatch):
    monkeypatch.setenv("NIMA_ADMIN_TOKEN", "   ")
    response = _make_decorator_app().test_client().get("/probe")
    assert response.status_code == 503


def test_decorator_401_when_header_missing(monkeypatch):
    monkeypatch.setenv("NIMA_ADMIN_TOKEN", "secret")
    response = _make_decorator_app().test_client().get("/probe")
    assert response.status_code == 401
    assert response.get_json() == {"error": "Admin authentication required"}


def test_decorator_403_when_header_wrong(monkeypatch):
    monkeypatch.setenv("NIMA_ADMIN_TOKEN", "secret")
    response = _make_decorator_app().test_client().get(
        "/probe", headers={"X-Admin-Token": "nope"}
    )
    assert response.status_code == 403
    assert response.get_json() == {"error": "Invalid admin token"}


def test_decorator_accepts_matching_x_admin_token_header(monkeypatch):
    monkeypatch.setenv("NIMA_ADMIN_TOKEN", "secret")
    response = _make_decorator_app().test_client().get(
        "/probe", headers={"X-Admin-Token": "secret"}
    )
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_decorator_accepts_bearer_authorization(monkeypatch):
    monkeypatch.setenv("NIMA_ADMIN_TOKEN", "secret")
    response = _make_decorator_app().test_client().get(
        "/probe", headers={"Authorization": "Bearer secret"}
    )
    assert response.status_code == 200


def test_decorator_rejects_bearer_with_wrong_token(monkeypatch):
    monkeypatch.setenv("NIMA_ADMIN_TOKEN", "secret")
    response = _make_decorator_app().test_client().get(
        "/probe", headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 403


# ─── Per-route integration tests ────────────────────────────────────────────
#
# We assert that without a valid admin token the route short-circuits BEFORE
# touching the database (401/403/503), which is the whole point of this PR.


@pytest.fixture
def admin_secret(monkeypatch):
    monkeypatch.setenv("NIMA_ADMIN_TOKEN", "test-admin-secret")
    return "test-admin-secret"


def _register_api_keys(app):
    app.register_blueprint(
        create_api_keys_blueprint(
            db=None,
            check_rate_limit=lambda _key: (True, 0),
            request_json_object=lambda *a, **kw: {},
        )
    )


def _register_templates(app):
    app.register_blueprint(
        create_templates_blueprint(
            None, lambda *a, **kw: {},
        )
    )


def _register_webhooks(app):
    app.register_blueprint(
        create_webhooks_blueprint(
            db=None, request_json_object=lambda *a, **kw: {}
        )
    )


def _register_media(app):
    app.register_blueprint(
        create_media_blueprint(
            db=None,
            request_json_object=lambda **_: {},
            find_video_file=lambda *_, **__: None,
            outputs=Path("outputs"),
            cdn_enabled=False,
            cdn_base_url="",
        )
    )


def _register_lti(app):
    app.register_blueprint(
        create_lti_blueprint(
            db=None,
            request_json_object=lambda *a, **kw: {},
            get_job_status=lambda _id: None,
        )
    )


ADMIN_ROUTES = [
    # (register_fn, method, path)
    (_register_api_keys, "POST", "/api/keys"),
    (_register_api_keys, "DELETE", "/api/keys/abc"),
    (_register_templates, "GET", "/api/templates/pending"),
    (_register_templates, "PUT", "/api/templates/1/approve"),
    (_register_templates, "DELETE", "/api/templates/1"),
    (_register_webhooks, "POST", "/api/webhooks"),
    (_register_webhooks, "GET", "/api/webhooks"),
    (_register_webhooks, "DELETE", "/api/webhooks/abc"),
    (_register_media, "POST", "/api/videos/cdn-url"),
]


@pytest.mark.parametrize("register_fn,method,path", ADMIN_ROUTES)
def test_admin_route_503_when_token_unconfigured(
    monkeypatch, register_fn, method, path
):
    monkeypatch.delenv("NIMA_ADMIN_TOKEN", raising=False)
    app = Flask(__name__)
    register_fn(app)
    response = app.test_client().open(path, method=method, json={})
    assert response.status_code == 503, (method, path, response.get_json())
    assert response.get_json() == {"error": "Admin auth not configured"}


@pytest.mark.parametrize("register_fn,method,path", ADMIN_ROUTES)
def test_admin_route_401_without_token_header(
    admin_secret, register_fn, method, path
):
    app = Flask(__name__)
    register_fn(app)
    response = app.test_client().open(path, method=method, json={})
    assert response.status_code == 401, (method, path, response.get_json())


@pytest.mark.parametrize("register_fn,method,path", ADMIN_ROUTES)
def test_admin_route_403_with_wrong_token(
    admin_secret, register_fn, method, path
):
    app = Flask(__name__)
    register_fn(app)
    response = app.test_client().open(
        path, method=method, json={}, headers={"X-Admin-Token": "wrong"}
    )
    assert response.status_code == 403, (method, path, response.get_json())


def test_lti_platforms_requires_both_feature_flag_and_admin(monkeypatch):
    """Decorator ordering: LTI feature flag is outermost, admin second."""
    app = Flask(__name__)
    _register_lti(app)

    # Flag off + no admin → LTI 503 (flag check wins).
    monkeypatch.delenv("NIMA_LTI_ENABLED", raising=False)
    monkeypatch.delenv("NIMA_ADMIN_TOKEN", raising=False)
    response = app.test_client().post("/api/lti/platforms", json={})
    assert response.status_code == 503
    assert response.get_json()["error"] == "LTI disabled"

    # Flag on, admin unconfigured → 503 Admin auth not configured.
    monkeypatch.setenv("NIMA_LTI_ENABLED", "true")
    response = app.test_client().post("/api/lti/platforms", json={})
    assert response.status_code == 503
    assert response.get_json() == {"error": "Admin auth not configured"}

    # Flag on, admin configured, no header → 401.
    monkeypatch.setenv("NIMA_ADMIN_TOKEN", "s3cret")
    response = app.test_client().post("/api/lti/platforms", json={})
    assert response.status_code == 401

    # Flag on, admin configured, wrong header → 403.
    response = app.test_client().post(
        "/api/lti/platforms", json={}, headers={"X-Admin-Token": "nope"}
    )
    assert response.status_code == 403

    # Flag on, admin configured, correct header → past auth. Since this test
    # wires db=None, the route falls through to its own
    # "Database not available" 503; crucially the body differs from the
    # auth-layer 503, proving we got past admin auth.
    response = app.test_client().post(
        "/api/lti/platforms", json={}, headers={"X-Admin-Token": "s3cret"}
    )
    assert response.status_code == 503
    assert response.get_json() == {"error": "Database not available"}


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
