"""Google ID-token verification for web-origin-only API access.

When EVO_REQUIRE_ID_TOKEN=1 the API accepts only the web service
account's Google-signed ID token. This module verifies signature
(Google certs), exp/iat and iss, raising ValueError on any failure.
"""
from __future__ import annotations

import time

_GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

# Transport request for cert fetch (google-auth fetches and caches Google certs itself).
def _get_request():
    from google.auth.transport import requests as _requests

    return _requests.Request()


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
    except ImportError as e:
        raise ValueError("google-auth unavailable") from e

    req = _get_request()
    try:
        claims = _id_token.verify_token(token, req, audience=aud)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("invalid ID token") from e

    iss = claims.get("iss")
    if iss not in _GOOGLE_ISSUERS:
        raise ValueError("invalid token issuer")
    # exp/iat are enforced by google-auth; double-check presence.
    now = int(time.time())
    try:
        exp = int(claims.get("exp", 0))
    except Exception:
        raise ValueError("invalid exp claim") from None
    if exp <= now:
        raise ValueError("token expired")
    return dict(claims)
