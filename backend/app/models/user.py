"""User model: Google identity, OAuth tokens, and session metadata."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.email import Email
    from app.models.sync_job import SyncJob


class User(Base):
    """Authenticated Gmail account (single-tenant MVP, multi-tenant ready via user_id FKs)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    google_sub: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        comment="Google OAuth subject identifier (stable user id from Google)",
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Populated after OAuth callback; encryption applied in core/security.py (later phase)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    emails: Mapped[list[Email]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sync_jobs: Mapped[list[SyncJob]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
