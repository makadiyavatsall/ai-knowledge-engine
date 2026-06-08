"""OAuth routes: Google login, callback, and session JWT issuance."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_oauth_state,
    set_session_cookie,
    validate_oauth_state,
)
from app.services.google_oauth import GoogleOAuthService, get_google_oauth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google", tags=["auth"])


@router.get("/login")
async def google_login(
    settings: Settings = Depends(get_settings),
    oauth_service: GoogleOAuthService = Depends(get_google_oauth_service),
) -> RedirectResponse:
    """
    Redirect the browser to Google's OAuth consent screen.

    A signed state parameter prevents CSRF on the callback.
    """
    state = create_oauth_state(settings)
    authorization_url = oauth_service.build_authorization_url(state)
    return RedirectResponse(url=authorization_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/callback")
async def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    oauth_service: GoogleOAuthService = Depends(get_google_oauth_service),
) -> RedirectResponse:
    """
    Handle Google OAuth redirect: validate state, exchange code, upsert user, set session cookie.
    """
    if error:
        logger.warning("Google OAuth error from provider")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google OAuth authorization failed",
        )

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code",
        )

    validate_oauth_state(state or "", settings)

    tokens = await oauth_service.exchange_code_for_tokens(code)
    profile = await oauth_service.fetch_user_profile(tokens.access_token)
    user = await oauth_service.upsert_user(
        session,
        profile=profile,
        tokens=tokens,
    )

    app_jwt = create_access_token(
        user_id=user.id,
        email=user.email,
        settings=settings,
    )

    response = RedirectResponse(
        url=settings.frontend_oauth_redirect_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    set_session_cookie(response, app_jwt, settings)
    return response
