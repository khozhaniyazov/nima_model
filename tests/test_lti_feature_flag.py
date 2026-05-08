"""Feature-flag gating tests for the LTI blueprint.

Pins the behaviour introduced in #43: every LTI route must return 503 unless
``NIMA_LTI_ENABLED=true`` is set. This closes the
``jwt.decode(..., verify_signature=False)`` privilege-escalation path
documented in ``api_routes/lti.py``'s module docstring.
"""

from __future__ import annotations

import pytest
from flask import Flask

from api_routes.lti import create_lti_blueprint


LTI_ROUTES = [
    ("GET", "/api/lti/login", {}),
    ("POST", "/api/lti/launch", {"id_token": "x", "state": "y"}),
    ("GET", "/api/lti/embed/any-job-id", {}),
    ("GET", "/api/lti/config", {}),
    ("POST", "/api/lti/platforms", {}),
    ("GET", "/api/lti/jwks", {}),
]


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(
        create_lti_blueprint(
            db=None,
            request_json_object=lambda *a, **kw: {},
            get_job_status=lambda _id: None,
        )
    )
    return app


@pytest.mark.parametrize("method,path,form", LTI_ROUTES)
def test_every_lti_route_is_503_by_default(monkeypatch, method, path, form):
    monkeypatch.delenv("NIMA_LTI_ENABLED", raising=False)
    app = _make_app()
    client = app.test_client()

    response = client.open(path, method=method, data=form)

    assert response.status_code == 503, (method, path, response.get_json())
    body = response.get_json()
    assert body == {
        "error": "LTI disabled",
        "detail": (
            "LTI 1.3 integration is feature-flagged off by default "
            "(see api_routes/lti.py docstring). Set "
            "NIMA_LTI_ENABLED=true to enable."
        ),
    }


@pytest.mark.parametrize(
    "value",
    ["false", "FALSE", "0", "no", "", "yes-but-not-true", "  True-ish  "],
)
def test_non_true_values_keep_lti_disabled(monkeypatch, value):
    monkeypatch.setenv("NIMA_LTI_ENABLED", value)
    app = _make_app()
    response = app.test_client().get("/api/lti/config")
    assert response.status_code == 503


def test_true_flag_unlocks_routes_but_launch_still_requires_inputs(monkeypatch):
    # With the flag flipped the routes stop short-circuiting to 503. We only
    # assert that the feature flag is no longer the gate — the endpoints
    # still enforce their own argument validation (missing id_token/state
    # here surfaces as a 400 from lti_launch).
    monkeypatch.setenv("NIMA_LTI_ENABLED", "true")
    app = _make_app()
    response = app.test_client().post("/api/lti/launch", data={})
    assert response.status_code == 400
    assert response.get_json() == {"error": "Missing id_token or state"}
