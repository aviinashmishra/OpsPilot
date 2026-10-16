"""OIDC verification against a local JWKS (no network): RS256 accepted, alg confusion rejected."""

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import security
from app.core.config import get_settings, reset_settings_cache
from app.core.errors import AuthenticationError

ISSUER = "https://idp.example.test/"
JWKS_URL = "https://idp.example.test/.well-known/jwks.json"


@pytest.fixture
def oidc_env(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "k1", "alg": "RS256", "use": "sig"})
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_JWKS_URL", JWKS_URL)
    monkeypatch.setenv("OIDC_AUDIENCE", "opspilot-api")
    reset_settings_cache()
    security._jwks_cache.keys = {"k1": jwk}
    security._jwks_cache.fetched_at = time.time()
    yield key, pub_pem
    security._jwks_cache.keys = {}
    security._jwks_cache.fetched_at = 0.0
    reset_settings_cache()


def _claims():
    now = int(time.time())
    return {"sub": "user-1", "iss": ISSUER, "aud": "opspilot-api", "iat": now, "exp": now + 300}


def test_rs256_token_from_idp_is_accepted(oidc_env):
    key, _ = oidc_env
    token = jwt.encode(_claims(), key, algorithm="RS256", headers={"kid": "k1"})
    assert security.decode_token(token)["sub"] == "user-1"


def _b64(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def test_hs256_with_public_key_as_secret_is_rejected(oidc_env):
    """Classic key-confusion attack: an attacker hand-crafts an HS256 token using the IdP's public key
    as the HMAC secret (PyJWT itself refuses to build such tokens, so we build it manually)."""
    import hashlib
    import hmac

    _, pub_pem = oidc_env
    for secret in (pub_pem, pub_pem.replace("\n", ""), pub_pem.replace("\n", "\r")):
        header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
        payload = _b64(json.dumps(_claims()).encode())
        sig = _b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        with pytest.raises(AuthenticationError):
            security.decode_token(f"{header}.{payload}.{sig}")


def test_unknown_kid_and_wrong_audience_rejected(oidc_env):
    key, _ = oidc_env
    with pytest.raises(AuthenticationError):
        security.decode_token(jwt.encode(_claims(), key, algorithm="RS256", headers={"kid": "other"}))
    with pytest.raises(AuthenticationError):
        security.decode_token(jwt.encode({**_claims(), "aud": "someone-else"}, key, algorithm="RS256", headers={"kid": "k1"}))


def test_local_tokens_still_work_alongside_oidc(oidc_env):
    tok = security.create_access_token(subject="u", tenant_id="t", roles=[], permissions=[])
    assert security.decode_token(tok)["sub"] == "u"
    assert get_settings().oidc_issuer == ISSUER
