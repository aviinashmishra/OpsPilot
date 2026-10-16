"""Authentication primitives: password hashing, JWT issuing/verification (local
issuer or external OIDC via JWKS), API-key hashing, webhook signatures, and
Fernet encryption for stored integration credentials.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.errors import AuthenticationError


# --- Passwords -------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# --- API keys ---------------------------------------------------------------
def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext_key, prefix, sha256_hash). Only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    key = f"opk_{raw}"
    return key, key[:12], hash_api_key(key)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# --- JWT (local issuer) ------------------------------------------------------
def create_access_token(
    *, subject: str, tenant_id: str, roles: list[str], permissions: list[str], extra: dict[str, Any] | None = None
) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "tid": tenant_id,
        "roles": roles,
        "perms": permissions,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.access_token_ttl_minutes)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


OIDC_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"]


class _JWKSCache:
    def __init__(self) -> None:
        self.keys: dict[str, Any] = {}
        self.fetched_at: float = 0.0

    def get(self, url: str) -> dict[str, Any]:
        if time.time() - self.fetched_at > 3600 or not self.keys:
            resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            self.keys = {k["kid"]: k for k in resp.json().get("keys", []) if "kid" in k}
            self.fetched_at = time.time()
        return self.keys


_jwks_cache = _JWKSCache()


def decode_token(token: str) -> dict[str, Any]:
    """Verify a bearer token. Local HS tokens are verified with the app secret;
    tokens from a configured OIDC issuer are verified against its JWKS."""
    s = get_settings()
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Malformed token") from exc

    issuer = unverified.get("iss")
    try:
        if s.oidc_issuer and issuer == s.oidc_issuer:
            if not s.oidc_jwks_url:
                raise AuthenticationError("OIDC JWKS URL not configured")
            header = jwt.get_unverified_header(token)
            keys = _jwks_cache.get(s.oidc_jwks_url)
            jwk = keys.get(header.get("kid"))
            if not jwk:
                raise AuthenticationError("Unknown signing key")
            if header.get("alg") not in OIDC_ALGORITHMS:
                raise AuthenticationError("Unsupported token algorithm")
            public_key = jwt.PyJWK(jwk).key
            # The allow-list is fixed and asymmetric-only: never trust `alg` from the token header,
            # and never mix HMAC with asymmetric algorithms (key-confusion attacks).
            return jwt.decode(
                token,
                public_key,
                algorithms=OIDC_ALGORITHMS,
                audience=s.oidc_audience or s.jwt_audience,
                issuer=s.oidc_issuer,
            )
        return jwt.decode(
            token, s.secret_key, algorithms=[s.jwt_algorithm], audience=s.jwt_audience, issuer=s.jwt_issuer
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid token") from exc


# --- Webhook signatures ----------------------------------------------------
def sign_payload(secret: str, body: bytes, timestamp: str | None = None) -> str:
    ts = timestamp or str(int(time.time()))
    mac = hmac.new(secret.encode("utf-8"), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(secret: str, body: bytes, signature_header: str | None, tolerance_seconds: int = 300) -> bool:
    if not signature_header:
        return False
    parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
    ts, sig = parts.get("t"), parts.get("v1")
    if not ts or not sig:
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance_seconds:
            return False
    except ValueError:
        return False
    expected = hmac.new(secret.encode("utf-8"), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def verify_hmac_sha256(secret: str, body: bytes, provided_hex: str | None, prefix: str = "") -> bool:
    """Generic provider-style HMAC verification (e.g. Meta/WhatsApp `sha256=<hex>`)."""
    if not provided_hex:
        return False
    if prefix and provided_hex.startswith(prefix):
        provided_hex = provided_hex[len(prefix) :]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided_hex)


def verify_hmac_sha256_base64(secret: str, body: bytes, provided_b64: str | None) -> bool:
    """Shopify-style base64 HMAC verification."""
    if not provided_b64:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), provided_b64)


# --- Credential encryption -----------------------------------------------------
def _fernet() -> Fernet:
    s = get_settings()
    key = s.encryption_key
    if not key:
        # Derive a stable dev-only key from the app secret. Production must set ENCRYPTION_KEY.
        derived = hashlib.sha256(s.secret_key.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(derived).decode()
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise AuthenticationError("Stored credential cannot be decrypted with the current key") from exc


def canonical_hash(payload: Any) -> str:
    """Stable SHA-256 of a JSON-serialisable payload (used to bind approvals to exact actions)."""
    import json

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()
