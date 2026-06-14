"""Chunk model: text segments and vector embeddings for retrieval."""

from __future__ import annotations
from pgvector.sqlalchemy import Vector

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.email import Email


class Chunk(Base):
    """Text segment derived from an email body.

    Embedding vector column (pgvector) will be added in a later migration.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("email_id", "chunk_index", name="uq_chunks_email_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("emails.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Zero-based order of chunk within the parent email",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Token count (tiktoken cl100k_base) for this chunk payload",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
    	Vector(1536),
    	nullable=True,
    	comment="OpenAI embedding vector stored in pgvector",
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

    email: Mapped[Email] = relationship(back_populates="chunks")
