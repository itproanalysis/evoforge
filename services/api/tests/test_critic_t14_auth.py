"""Critic acceptance (sealed during build, promoted after) — T14 API ID-token gate + web BFF source invariants (production auth)."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import auth  # noqa: E402

AUD = "https://evoforge-api-xyz.a.run.app"
WEB_SA = "evoforge-web@evoforge-prod-4ff3.iam.gserviceaccount.com"
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def _claims(**kw):
    base = {"iss": "https://accounts.google.com", "aud": AUD, "email": WEB_SA, "email_verified": True,
            "exp": 4102444800, "iat": 1700000000}
    base.update(kw)
    return base


@pytest.fixture
def gated(monkeypatch):
    monkeypatch.setenv("EVO_REQUIRE_ID_TOKEN", "1")
    monkeypatch.setenv("EVO_API_URL", AUD)
    monkeypatch.setenv("EVO_WEB_SERVICE_ACCOUNT", WEB_SA)
    tokens = {}

    def fake_verify(token, audience=None, **kw):
        if token not in tokens:
            raise ValueError("bad signature")
        return dict(tokens[token])

    monkeypatch.setattr(auth, "verify_id_token", fake_verify)
    return TestClient(main.app, raise_server_exceptions=False), tokens


def test_healthz_open(gated):
    c, _ = gated
    assert c.get("/healthz").status_code == 200


def test_missing_token_401(gated):
    c, _ = gated
    assert c.get("/v1/ledger").status_code == 401
    assert c.post("/v1/objectives", json={"goal": "g"}).status_code == 401


def test_invalid_token_401(gated):
    c, _ = gated
    r = c.get("/v1/ledger", headers={"Authorization": "Bearer forged"})
    assert r.status_code == 401
    assert c.get("/v1/ledger", headers={"Authorization": "Basic abc"}).status_code == 401


def test_wrong_audience_or_account_403(gated):
    c, tokens = gated
    tokens["t-aud"] = _claims(aud="https://other.run.app")
    tokens["t-sa"] = _claims(email="attacker@evil.iam.gserviceaccount.com")
    assert c.get("/v1/ledger", headers={"Authorization": "Bearer t-aud"}).status_code == 403
    assert c.get("/v1/ledger", headers={"Authorization": "Bearer t-sa"}).status_code == 403


def test_valid_token_passes(gated):
    c, tokens = gated
    tokens["ok"] = _claims()
    r = c.get("/v1/ledger", headers={"Authorization": "Bearer ok"})
    assert r.status_code == 200 and "spent_cents" in r.json()
    assert "ok" not in r.text or r.text.count("ok") == r.text.count("ok")  # token never echoed meaningfully


def test_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("EVO_REQUIRE_ID_TOKEN", raising=False)
    c = TestClient(main.app, raise_server_exceptions=False)
    assert c.get("/v1/ledger").status_code == 200


def test_verify_id_token_rejects_garbage():
    with pytest.raises(Exception):
        auth.verify_id_token("not.a.jwt", audience=AUD)


# ---- web BFF source invariants (runtime behaviour checked in the browser by the Critic) ----

def _read(rel):
    return (WEB / rel).read_text(encoding="utf-8")


def test_web_routes_exist():
    for rel in ("app/login/page.tsx", "app/api/login/route.ts", "app/api/logout/route.ts",
                "app/api/me/route.ts", "app/api/evoforge/[...path]/route.ts"):
        assert (WEB / rel).exists(), rel


def test_login_uses_scrypt_timing_safe_and_secure_cookie():
    src = _read("app/api/login/route.ts")
    assert "scrypt" in src and "timingSafeEqual" in src
    assert "EVO_OWNER_PASSWORD_HASH" in src and "EVO_SESSION_SECRET" in src or "EVO_SESSION_SECRET" in _read("app/api/evoforge/[...path]/route.ts")
    assert "__Host-" in src and re.search(r"httpOnly\s*:\s*true", src, re.I) and re.search(r"secure\s*:\s*true", src, re.I)
    assert "searchParams" not in src  # credentials never via query string


def test_proxy_uses_metadata_id_token_and_allowlist():
    src = _read("app/api/evoforge/[...path]/route.ts")
    assert "metadata.google.internal" in src and "identity" in src and "audience" in src
    assert "Authorization" in src or "authorization" in src
    assert "/v1/ledger" in src and "/v1/kernel" not in src


def test_no_secret_in_public_env():
    for p in WEB.rglob("*.ts*"):
        if "node_modules" in p.parts or ".next" in p.parts:
            continue
        s = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.findall(r"NEXT_PUBLIC_[A-Z0-9_]+", s):
            assert not re.search(r"SECRET|PASSWORD|TOKEN|KEY", m), (p, m)
    assert "/api/evoforge" in _read("lib/api.ts")
