"""The web app is a separate origin; browser calls need CORS on the API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

c = TestClient(app)


def _preflight(origin):
    return c.options("/v1/gates/evaluate", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})


@pytest.mark.parametrize("origin", [
    "http://localhost:3000",
    "https://evoforge-web-abc123-du.a.run.app",
    "https://evoforge-web-123456789.asia-northeast3.run.app",
])
def test_web_origins_allowed(origin):
    r = _preflight(origin)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["https://evil.example", "https://evoforge-web-x.a.run.app.evil.example"])
def test_other_origins_refused(origin):
    r = _preflight(origin)
    assert "access-control-allow-origin" not in r.headers
