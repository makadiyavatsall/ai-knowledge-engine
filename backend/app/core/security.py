"""JWT issuance or validation and encryption of OAuth tokens at rest."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import Settings, get_settings

_bearer_scheme = HTTPBearer(auto_error=False)

# Gmail read scope included so stored refresh tokens work for ingestion (Phase 4+).
GOOGLE_OAUTH_SCOPES = (
    "openid",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
)

REQUIRED_OAUTH_SCOPES: frozenset[str] = frozenset(["openid", "https://www.googleapis.com/auth/userinfo.profile", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/gmail.readonly"])


def _fernet(settings: Settings) -> Fernet:
    """Fernet instance for Google OAuth token encryption at rest."""
    return Fernet(settings.token_encryption_key.encode("utf-8"))


def _state_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        secret_key=settings.jwt_secret_key,
        salt="google-oauth-state",
    )


def create_oauth_state(settings: Settings | None = None) -> str:
    """Create a signed, time-limited OAuth state value (CSRF protection)."""
    cfg = settings or get_settings()
    payload = {"nonce": secrets.token_urlsafe(32)}
    return _state_serializer(cfg).dumps(payload)


def validate_oauth_state(state: str, settings: Settings | None = None) -> None:
    """Validate state from Google callback; raises HTTPException on failure."""
    cfg = settings or get_settings()
    if not state or not state.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth state parameter",
        )
    try:
        _state_serializer(cfg).loads(
            state,
            max_age=cfg.oauth_state_max_age_seconds,
        )
    except SignatureExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state expired; restart login",
        ) from exc
    except BadSignature as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state",
        ) from exc


def validate_granted_scopes(scope: str | None) -> None:
    """Ensure Google returned all scopes required for Gmail RAG."""
    if not scope or not scope.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google did not grant any OAuth scopes",
        )
    granted = set(scope.strip().split())
    missing = REQUIRED_OAUTH_SCOPES - granted

    print("GRANTED:", granted)
    print("MISSING:", missing)

    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required Google permissions; please grant all requested scopes",
        )


def encrypt_token(plain: str, settings: Settings | None = None) -> str:
    """Encrypt OAuth token for storage at rest."""
    cfg = settings or get_settings()
    return _fernet(cfg).encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_token(cipher: str, settings: Settings | None = None) -> str:
    """Decrypt OAuth token loaded from the database."""
    cfg = settings or get_settings()
    try:
        return _fernet(cfg).decrypt(cipher.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored token could not be decrypted") from exc


def create_access_token(
    *,
    user_id: UUID,
    email: str,
    settings: Settings | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Issue an application JWT for API authentication."""
    cfg = settings or get_settings()
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=cfg.jwt_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, cfg.jwt_secret_key, algorithm=cfg.jwt_algorithm)


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    """Decode and validate an application JWT."""
    cfg = settings or get_settings()
    try:
        return jwt.decode(
            token,
            cfg.jwt_secret_key,
            algorithms=[cfg.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def set_session_cookie(
    response: Response,
    token: str,
    settings: Settings | None = None,
) -> None:
    """Attach HttpOnly session JWT cookie (not exposed in URLs)."""
    cfg = settings or get_settings()
    response.set_cookie(
        key=cfg.auth_cookie_name,
        value=token,
        httponly=True,
        secure=cfg.auth_cookie_secure,
        samesite="lax",
        max_age=cfg.jwt_expire_minutes * 60,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def _extract_bearer_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    settings: Settings,
) -> str | None:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    return request.cookies.get(settings.auth_cookie_name)


async def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> UUID:
    """
    FastAPI dependency: user id from Bearer header or HttpOnly session cookie.

    Used by protected routes in later phases (/emails, /query, etc.).
    """
    token = _extract_bearer_token(request, credentials, settings)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(token, settings)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return UUID(str(sub))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
