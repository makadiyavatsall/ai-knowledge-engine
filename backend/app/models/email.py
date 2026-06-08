"""Email model: Gmail message metadata and plaintext body storage."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.user import User


class Email(Base):
    """Stored Gmail message (plaintext body for MVP ingestion)."""

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("user_id", "gmail_message_id", name="uq_emails_user_gmail_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    gmail_message_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Gmail API message id",
    )
    thread_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Gmail thread id for grouping conversation context",
    )
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    sender: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    recipient: Mapped[str | None] = mapped_column(String(320), nullable=True)
    body_plain: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Plaintext body only for MVP (no HTML parsing yet)",
    )
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Message internal date from Gmail",
    )
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set when chunking/embedding pipeline completes",
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

    user: Mapped[User] = relationship(back_populates="emails")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="email",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )
