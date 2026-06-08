"""Google OAuth service: authorization, token exchange, profile fetch, user upsert."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import (
    GOOGLE_OAUTH_SCOPES,
    decrypt_token,
    encrypt_token,
    validate_granted_scopes,
)
from app.models.user import User

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


@dataclass(frozen=True, slots=True)
class GoogleTokenResponse:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    token_type: str | None
    scope: str | None


@dataclass(frozen=True, slots=True)
class GoogleUserProfile:
    google_sub: str
    email: str
    display_name: str | None
    email_verified: bool


class GoogleOAuthService:
    """Encapsulates all Google OAuth and user persistence logic."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def build_authorization_url(self, state: str) -> str:
        """Build Google consent screen URL with CSRF state."""
        params = {
            "client_id": self._settings.google_client_id,
            "redirect_uri": self._settings.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_OAUTH_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> GoogleTokenResponse:
        """Exchange authorization code for Google access and refresh tokens."""
        payload = {
            "code": code,
            "client_id": self._settings.google_client_id,
            "client_secret": self._settings.google_client_secret,
            "redirect_uri": self._settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(GOOGLE_TOKEN_URL, data=payload)

        if response.status_code != status.HTTP_200_OK:
            logger.warning(
                "Google token exchange failed with status %s",
                response.status_code,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code with Google",
            )

        data = response.json()
        access_token = data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google did not return an access token",
            )

        token_response = GoogleTokenResponse(
            access_token=access_token,
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type"),
            scope=data.get("scope"),
        )
        validate_granted_scopes(token_response.scope)
        return token_response

    async def fetch_user_profile(self, access_token: str) -> GoogleUserProfile:
        """Fetch Google user profile (sub, email, name) and require verified email."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(GOOGLE_USERINFO_URL, headers=headers)

        if response.status_code != status.HTTP_200_OK:
            logger.warning(
                "Google userinfo failed with status %s",
                response.status_code,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to fetch user profile from Google",
            )

        data = response.json()
        google_sub = data.get("sub")
        email = data.get("email")
        email_verified = data.get("email_verified") is True

        if not google_sub or not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google profile missing required fields (sub, email)",
            )

        if not email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Google account email is not verified",
            )

        return GoogleUserProfile(
            google_sub=str(google_sub),
            email=str(email),
            display_name=data.get("name"),
            email_verified=email_verified,
        )

    @staticmethod
    def _token_expires_at(expires_in: int | None) -> datetime | None:
        if expires_in is None:
            return None
        return datetime.now(UTC) + timedelta(seconds=int(expires_in))

    async def upsert_user(
        self,
        session: AsyncSession,
        *,
        profile: GoogleUserProfile,
        tokens: GoogleTokenResponse,
    ) -> User:
        """
        Create or update user by google_sub.

        Updates profile fields and encrypted OAuth tokens on every login.
        """
        encrypted_access = encrypt_token(tokens.access_token, self._settings)
        encrypted_refresh = (
            encrypt_token(tokens.refresh_token, self._settings)
            if tokens.refresh_token
            else None
        )
        token_expires_at = self._token_expires_at(tokens.expires_in)

        result = await session.execute(
            select(User).where(User.google_sub == profile.google_sub)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                google_sub=profile.google_sub,
                email=profile.email,
                display_name=profile.display_name,
                access_token=encrypted_access,
                refresh_token=encrypted_refresh,
                token_expires_at=token_expires_at,
            )
            session.add(user)
            logger.info("Created user google_sub=%s", profile.google_sub)
        else:
            user.email = profile.email
            user.display_name = profile.display_name
            user.access_token = encrypted_access
            if encrypted_refresh is not None:
                user.refresh_token = encrypted_refresh
            user.token_expires_at = token_expires_at
            logger.info("Updated user id=%s google_sub=%s", user.id, profile.google_sub)

        await session.commit()
        await session.refresh(user)
        return user

    async def get_decrypted_google_access_token(
        self,
        session: AsyncSession,
        user_id: UUID,
    ) -> str:
        """Load decrypted Google access token for a user (for Gmail API in Phase 4+)."""
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None or not user.access_token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return decrypt_token(user.access_token, self._settings)


def get_google_oauth_service(settings: Settings = Depends(get_settings)) -> GoogleOAuthService:
    return GoogleOAuthService(settings)

