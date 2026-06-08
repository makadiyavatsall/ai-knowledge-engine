"""Gmail API client wrapper for listing and fetching messages."""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import decrypt_token, encrypt_token
from app.models.user import User
from app.services.google_oauth import GOOGLE_TOKEN_URL

logger = logging.getLogger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
TOKEN_EXPIRY_BUFFER = timedelta(minutes=2)
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class GmailProfile:
    """Authenticated user's Gmail mailbox profile."""

    email_address: str
    messages_total: int
    threads_total: int
    history_id: str


@dataclass(frozen=True, slots=True)
class ParsedEmail:
    """Normalized email fields extracted from a Gmail API message resource."""

    gmail_message_id: str
    thread_id: str | None
    subject: str | None
    sender: str | None
    recipient: str | None
    body_plain: str | None
    received_at: datetime | None


class GmailService:
    """Gmail REST client using OAuth tokens stored on the User model."""

    def __init__(
        self,
        session: AsyncSession,
        user_id: UUID,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._settings = settings or get_settings()

    async def _load_user(self) -> User:
        result = await self._session.execute(
            select(User).where(User.id == self._user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        if not user.access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google account not connected; sign in again",
            )
        return user

    async def _refresh_access_token(self, user: User) -> str:
        if not user.refresh_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google session expired; sign in again",
            )

        refresh_plain = decrypt_token(user.refresh_token, self._settings)
        payload = {
            "client_id": self._settings.google_client_id,
            "client_secret": self._settings.google_client_secret,
            "refresh_token": refresh_plain,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(
            timeout=self._settings.gmail_api_request_timeout_seconds
        ) as client:
            response = await client.post(GOOGLE_TOKEN_URL, data=payload)

        if response.status_code != status.HTTP_200_OK:
            logger.warning("Google token refresh failed: status %s", response.status_code)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to refresh Google token; sign in again",
            )

        data = response.json()
        access_token = data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google token refresh returned no access token",
            )

        user.access_token = encrypt_token(access_token, self._settings)
        expires_in = data.get("expires_in")
        if expires_in is not None:
            user.token_expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))
        await self._session.commit()
        await self._session.refresh(user)
        return access_token

    async def get_valid_access_token(self) -> str:
        """Return a valid Google access token, refreshing when near expiry."""
        user = await self._load_user()
        now = datetime.now(UTC)
        expires_at = user.token_expires_at
        if expires_at is not None and expires_at > now + TOKEN_EXPIRY_BUFFER:
            return decrypt_token(user.access_token, self._settings)
        return await self._refresh_access_token(user)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Authenticated Gmail API request with simple 429 retry."""
        url = f"{GMAIL_API_BASE}{path}"
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            access_token = await self.get_valid_access_token()
            headers = {"Authorization": f"Bearer {access_token}"}
            try:
                async with httpx.AsyncClient(
                    timeout=self._settings.gmail_api_request_timeout_seconds
                ) as client:
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                    )
            except httpx.HTTPError as exc:
                last_error = exc
                await asyncio.sleep(RETRY_BACKOFF_BASE_SECONDS * (2**attempt))
                continue

            if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                retry_after = float(response.headers.get("Retry-After", "1"))
                await asyncio.sleep(min(retry_after, 30.0))
                continue

            if response.status_code == status.HTTP_401_UNAUTHORIZED:
                user = await self._load_user()
                await self._refresh_access_token(user)
                continue

            if response.status_code >= 400:
                logger.warning(
                    "Gmail API error path=%s status=%s",
                    path,
                    response.status_code,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Gmail API request failed",
                )

            return response.json()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail API unavailable after retries",
        ) from last_error

    async def get_profile(self) -> GmailProfile:
        """GET /users/me/profile — authenticated Gmail account metadata."""
        data = await self._request("GET", "/users/me/profile")
        return GmailProfile(
            email_address=str(data.get("emailAddress", "")),
            messages_total=int(data.get("messagesTotal", 0)),
            threads_total=int(data.get("threadsTotal", 0)),
            history_id=str(data.get("historyId", "")),
        )

    async def list_message_ids(self, *, max_results: int) -> list[str]:
        """List latest message IDs (newest first per Gmail default)."""
        data = await self._request(
            "GET",
            "/users/me/messages",
            params={"maxResults": max_results},
        )
        messages = data.get("messages") or []
        return [str(item["id"]) for item in messages if item.get("id")]

    async def fetch_parsed_message(self, message_id: str) -> ParsedEmail:
        """Fetch full message and extract MVP plaintext fields."""
        data = await self._request(
            "GET",
            f"/users/me/messages/{message_id}",
            params={"format": "full"},
        )
        return _parse_gmail_message(data)


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _header_value(headers: list[dict[str, str]], name: str) -> str | None:
    name_lower = name.lower()
    for header in headers:
        if header.get("name", "").lower() == name_lower:
            return header.get("value")
    return None


def _extract_plain_body(payload: dict[str, Any]) -> str | None:
    """Walk MIME parts and return the first text/plain body (MVP: no HTML)."""
    mime_type = payload.get("mimeType", "")
    body = payload.get("body") or {}
    if mime_type == "text/plain" and body.get("data"):
        return _decode_base64url(body["data"])

    for part in payload.get("parts") or []:
        if not isinstance(part, dict):
            continue
        text = _extract_plain_body(part)
        if text:
            return text
    return None


def _parse_received_at(internal_date_ms: str | None, date_header: str | None) -> datetime | None:
    if internal_date_ms:
        try:
            return datetime.fromtimestamp(int(internal_date_ms) / 1000, tz=UTC)
        except (TypeError, ValueError):
            pass
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (TypeError, ValueError):
            return None
    return None


def _parse_gmail_message(data: dict[str, Any]) -> ParsedEmail:
    message_id = str(data.get("id", ""))
    if not message_id:
        raise ValueError("Gmail message missing id")

    payload = data.get("payload") or {}
    headers = payload.get("headers") or []

    return ParsedEmail(
        gmail_message_id=message_id,
        thread_id=data.get("threadId"),
        subject=_header_value(headers, "Subject"),
        sender=_header_value(headers, "From"),
        recipient=_header_value(headers, "To"),
        body_plain=_extract_plain_body(payload),
        received_at=_parse_received_at(
            data.get("internalDate"),
            _header_value(headers, "Date"),
        ),
    )
