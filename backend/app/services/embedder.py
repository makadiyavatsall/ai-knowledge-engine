"""Embedding service: generates and stores OpenAI embeddings for text chunks."""

from __future__ import annotations

import logging
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.chunk import Chunk

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generates OpenAI embeddings and persists them to pgvector."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._client = AsyncOpenAI(api_key=self._settings.openai_api_key)

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding vector for a single text string."""
        response = await self._client.embeddings.create(
            model=self._settings.embedding_model,
            input=text,
            dimensions=self._settings.embedding_dimensions,
        )
        return response.data[0].embedding

    async def embed_chunks_for_email(self, email_id: UUID) -> int:
        """
        Generate and store embeddings for all unembedded chunks of an email.
        Returns the number of chunks embedded.
        """
        result = await self._session.execute(
            select(Chunk).where(
                Chunk.email_id == email_id,
                Chunk.embedding.is_(None),
            )
        )
        chunks = result.scalars().all()

        if not chunks:
            logger.info("No unembedded chunks found for email_id=%s", email_id)
            return 0

        embedded_count = 0
        for chunk in chunks:
            try:
                vector = await self.embed_text(chunk.content)
                
                await self._session.execute(
                    update(Chunk)
                    .where(Chunk.id == chunk.id)
                    .values(embedding=vector)
                )
                embedded_count += 1
                logger.debug("Embedded chunk id=%s", chunk.id)
            except Exception as exc:
                logger.exception("Failed to embed chunk id=%s: %s", chunk.id)
                raise

        await self._session.commit()
        logger.info(
            "Embedded %d/%d chunks for email_id=%s",
            embedded_count,
            len(chunks),
            email_id,
        )
        return embedded_count

    async def embed_all_pending(self) -> dict[str, int]:
        """
        Embed all chunks across all emails that have no embedding yet.
        Returns summary of emails processed and chunks embedded.
        """
        result = await self._session.execute(
            select(Chunk.email_id)
            .where(Chunk.embedding.is_(None))
            .distinct()
        )
        email_ids = result.scalars().all()

        if not email_ids:
            logger.info("No pending chunks to embed")
            return {"emails_processed": 0, "chunks_embedded": 0}

        total_embedded = 0
        for email_id in email_ids:
            count = await self.embed_chunks_for_email(email_id)
            total_embedded += count

        summary = {
            "emails_processed": len(email_ids),
            "chunks_embedded": total_embedded,
        }
        logger.info("Embedding complete: %s", summary)
        return summary
