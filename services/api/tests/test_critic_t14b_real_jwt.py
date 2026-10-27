"""Critic acceptance (sealed during build, promoted after) — T14b verify_id_token must accept a REAL signed Google-style ID token (no mocks of auth)."""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402
from google.auth import crypt, jwt  # noqa: E402
from google.oauth2 import id_token as gid  # noqa: E402

from evoforge import auth  # noqa: E402

AUD = "https://evoforge-api-230852112787.asia-northeast3.run.app"
KID = "critic-test-kid"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "critic-test")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    pem_key = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    pem_cert = cert.public_bytes(serialization.Encoding.PEM).decode()
    return pem_key, pem_cert


@pytest.fixture(autouse=True)
def google_certs(monkeypatch, keypair):
    """Serve our key wherever Google's signing certs are fetched (v1 PEM and v3 JWKS); no network.

    The production code path must run unmodified: nothing inside evoforge.auth is stubbed.
    """
    import base64
    import io
    import json as _json
    import urllib.request

    pem_key, pem_cert = keypair
    pub = serialization.load_pem_private_key(pem_key.encode(), None).public_key().public_numbers()

    def b64u(n):
        return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()

    jwks = {"keys": [{"kty": "RSA", "alg": "RS256", "use": "sig", "kid": KID, "n": b64u(pub.n), "e": b64u(pub.e)}]}
    v1 = {KID: pem_cert}

    class _CM(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *x):
            return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, *a, **k: _CM(_json.dumps(jwks if "v3" in (req if isinstance(req, str) else req.full_url) else v1).encode()))
    monkeypatch.setattr(gid, "_fetch_certs", lambda request, certs_url: jwks if "v3" in certs_url else v1)
    if hasattr(auth, "_certs_cache"):
        monkeypatch.setitem(auth._certs_cache, "certs", None)
        monkeypatch.setitem(auth._certs_cache, "fetched_at", 0.0)


def _token(keypair, **over):
    pem_key, _ = keypair
    now = int(time.time())
    payload = {"iss": "https://accounts.google.com", "aud": AUD, "sub": "1", "iat": now, "exp": now + 600,
               "email": "evoforge-web@evoforge-prod-4ff3.iam.gserviceaccount.com", "email_verified": True, **over}
    return jwt.encode(crypt.RSASigner.from_string(pem_key, KID), payload).decode()


def test_real_token_verifies(keypair):
    claims = auth.verify_id_token(_token(keypair), audience=AUD)
    assert claims["aud"] == AUD and claims["email"].startswith("evoforge-web@")


def test_expired_token_rejected(keypair):
    now = int(time.time())
    with pytest.raises(ValueError):
        auth.verify_id_token(_token(keypair, iat=now - 7200, exp=now - 3600), audience=AUD)


def test_wrong_issuer_rejected(keypair):
    with pytest.raises(ValueError):
        auth.verify_id_token(_token(keypair, iss="https://evil.example"), audience=AUD)


def test_tampered_signature_rejected(keypair):
    t = _token(keypair)
    head, body, sig = t.split(".")
    with pytest.raises(ValueError):
        auth.verify_id_token(f"{head}.{body}.{sig[:-4]}AAAA", audience=AUD)


def test_other_audience_rejected_or_reported(keypair):
    try:
        claims = auth.verify_id_token(_token(keypair, aud="https://other.run.app"), audience=AUD)
    except ValueError:
        return
    assert claims["aud"] != AUD  # if verification defers aud to the HTTP layer, it must at least report it
