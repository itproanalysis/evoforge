"""Google ID-token verification for web-origin-only API access.

When EVO_REQUIRE_ID_TOKEN=1 the API accepts only the web service
account's Google-signed ID token. This module verifies signature
(Google certs), exp/iat and iss, raising ValueError on any failure.
"""
from __future__ import annotations

import time
import urllib.request
import json

_GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

# Google signing certs cached for 1h.
_CERTS_TTL_S = 3600
_certs_cache: dict = {"certs": None, "fetched_at": 0.0}


def _fetch_certs() -> dict | None:
    now = time.time()
    cached = _certs_cache.get("certs")
    if cached is not None and (now - _certs_cache.get("fetched_at", 0.0)) < _CERTS_TTL_S:
        return cached
    try:
        with urllib.request.urlopen(_GOOGLE_CERTS_URL, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        # Keep stale certs if we have them; otherwise let google-auth fetch.
        return cached
    _certs_cache["certs"] = payload
    _certs_cache["fetched_at"] = now
    return payload


def verify_id_token(token: str, audience: str) -> dict:
    """Verify a Google ID token and return its claims.

    Verifies signature (via Google certs), exp/iat and iss.
    Raises ValueError (or a subclass) on any failure.
    """
    if not isinstance(token, str) or not token:
        raise ValueError("missing ID token")
    if not isinstance(audience, str):
        raise ValueError("invalid audience")
    aud = audience.strip() or None
    try:
        from google.oauth2 import id_token as _id_token
        from google.auth.transport import requests as _requests
    except ImportError as e:
        raise ValueError(f"google-auth unavailable: {e}")

    req = _requests.Request()
    certs = _fetch_certs()
    try:
        if certs is not None:
            claims = _id_token.verify_token(token, req, audience=aud, certs=certs)
        else:
            claims = _id_token.verify_oauth2_token(token, req, audience=aud)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"invalid ID token: {e}")

    iss = claims.get("iss")
    if iss not in _GOOGLE_ISSUERS:
        raise ValueError("invalid token issuer")
    # exp/iat are enforced by google-auth; double-check presence.
    now = int(time.time())
    try:
        exp = int(claims.get("exp", 0))
    except Exception:
        raise ValueError("invalid exp claim")
    if exp <= now:
        raise ValueError("token expired")
    return dict(claims)
