"""Text chunking strategies (fixed size and overlap for MVP)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import tiktoken
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.chunk import Chunk
from app.models.email import Email

logger = logging.getLogger(__name__)

# Align with OpenAI embedding models used in a later phase.
TIKTOKEN_ENCODING = "cl100k_base"


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """In-memory chunk before persistence."""

    chunk_index: int
    content: str
    token_count: int


class EmailChunkerService:
    """
    Split email text into overlapping token windows and persist Chunk rows.

    Searchable text = Subject + Sender + body_plain (metadata preserved in content).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._encoding = tiktoken.get_encoding(TIKTOKEN_ENCODING)
        self._chunk_size = self._settings.chunk_size
        self._chunk_overlap = self._settings.chunk_overlap

    def build_searchable_text(self, email: Email) -> str:
        """Compose canonical text for chunking (metadata + body)."""
        sections: list[str] = []

        if email.subject:
            sections.append(f"Subject: {email.subject.strip()}")
        if email.sender:
            sections.append(f"From: {email.sender.strip()}")

        if sections and email.body_plain and email.body_plain.strip():
            sections.append("")
            sections.append(email.body_plain.strip())
        elif email.body_plain and email.body_plain.strip():
            sections.append(email.body_plain.strip())

        return "\n".join(sections).strip()

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(self._encoding.encode(text))

    def split_into_chunks(self, text: str) -> list[ChunkDraft]:
        """
        Split text into overlapping chunks by token count.

        Uses a sliding window: step = chunk_size - chunk_overlap.
        """
        if not text:
            return [
                ChunkDraft(chunk_index=0, content="", token_count=0),
            ]

        tokens = self._encoding.encode(text)
        total = len(tokens)

        if total <= self._chunk_size:
            return [
                ChunkDraft(
                    chunk_index=0,
                    content=text,
                    token_count=total,
                )
            ]

        step = self._chunk_size - self._chunk_overlap
        if step <= 0:
            raise ValueError("chunk_overlap must be smaller than chunk_size")

        drafts: list[ChunkDraft] = []
        start = 0
        chunk_index = 0

        while start < total:
            end = min(start + self._chunk_size, total)
            chunk_tokens = tokens[start:end]
            chunk_text = self._encoding.decode(chunk_tokens)
            drafts.append(
                ChunkDraft(
                    chunk_index=chunk_index,
                    content=chunk_text,
                    token_count=len(chunk_tokens),
                )
            )
            if end >= total:
                break
            start += step
            chunk_index += 1

        return drafts

    async def chunk_and_persist(self, session: AsyncSession, email: Email) -> int:
        """
        Replace all chunks for an email and mark it indexed.

        Re-chunking deletes existing rows first (safe replace, no duplicate indices).
        """
        searchable = self.build_searchable_text(email)
        drafts = self.split_into_chunks(searchable)

        await session.execute(delete(Chunk).where(Chunk.email_id == email.id))

        for draft in drafts:
            session.add(
                Chunk(
                    email_id=email.id,
                    chunk_index=draft.chunk_index,
                    content=draft.content,
                    token_count=draft.token_count,
                )
            )

        email.indexed_at = datetime.now(UTC)
        await session.flush()

        logger.debug(
            "Chunked email_id=%s chunks=%s tokens_in_source=%s",
            email.id,
            len(drafts),
            self.count_tokens(searchable),
        )
        return len(drafts)


def get_email_chunker_service(settings: Settings | None = None) -> EmailChunkerService:
    return EmailChunkerService(settings)
