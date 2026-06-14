"""Ingestion orchestrator: fetch messages, parse bodies, persist emails, track sync jobs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.email import Email
from app.models.sync_job import SyncJob, SyncJobStatus
from app.services.chunker import EmailChunkerService, get_email_chunker_service
from app.services.embedder import EmbeddingService
from app.services.gmail import GmailService, ParsedEmail

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncJobResult:
    """Summary returned after a synchronous sync completes."""

    job_id: UUID
    status: SyncJobStatus
    total_messages: int
    processed_messages: int
    stored_messages: int
    skipped_messages: int
    chunked_messages: int
    total_chunks: int
    embedded_chunks: int
    error_message: str | None


class IngestionService:
    """Coordinates Gmail fetch, deduplication, email persistence, chunking, and embedding."""

    def __init__(
        self,
        session: AsyncSession,
        user_id: UUID,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._settings = settings or get_settings()
        self._gmail = GmailService(session, user_id, self._settings)
        self._chunker: EmailChunkerService = get_email_chunker_service(self._settings)
        self._embedder = EmbeddingService(session, self._settings)

    async def run_sync(self) -> SyncJobResult:
        """
        Run a synchronous ingestion job for the authenticated user.

        Gmail fetch → store emails → chunk → embed → set indexed_at.
        """
        job = SyncJob(
            user_id=self._user_id,
            status=SyncJobStatus.PENDING,
            processed_messages=0,
        )
        self._session.add(job)
        await self._session.commit()
        await self._session.refresh(job)

        stored_count = 0
        skipped_count = 0
        chunked_count = 0
        total_chunks = 0
        total_embedded = 0

        try:
            job.status = SyncJobStatus.RUNNING
            job.started_at = datetime.now(UTC)
            await self._session.commit()

            profile = await self._gmail.get_profile()
            logger.info(
                "Gmail sync started job_id=%s mailbox=%s messages_total=%s",
                job.id,
                profile.email_address,
                profile.messages_total,
            )

            max_results = self._settings.gmail_sync_max_messages
            message_ids = await self._gmail.list_message_ids(max_results=max_results)
            job.total_messages = len(message_ids)
            await self._session.commit()

            existing_ids = await self._load_existing_gmail_ids(message_ids)

            for index, gmail_message_id in enumerate(message_ids, start=1):
                if gmail_message_id in existing_ids:
                    email = await self._get_email_by_gmail_id(gmail_message_id)
                    if email is not None and email.indexed_at is None:
                        chunk_count = await self._chunker.chunk_and_persist(
                            self._session,
                            email,
                        )
                        chunked_count += 1
                        total_chunks += chunk_count
                        embedded = await self._embedder.embed_chunks_for_email(email.id)
                        total_embedded += embedded
                    skipped_count += 1
                else:
                    parsed = await self._gmail.fetch_parsed_message(gmail_message_id)
                    email = await self._store_email(parsed)
                    if email is not None:
                        stored_count += 1
                        existing_ids.add(gmail_message_id)
                        chunk_count = await self._chunker.chunk_and_persist(
                            self._session,
                            email,
                        )
                        chunked_count += 1
                        total_chunks += chunk_count
                        embedded = await self._embedder.embed_chunks_for_email(email.id)
                        total_embedded += embedded
                    else:
                        skipped_count += 1

                job.processed_messages = index
                await self._session.commit()

            job.status = SyncJobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            job.error_message = None
            await self._session.commit()

            logger.info(
                "Gmail sync completed job_id=%s stored=%s skipped=%s chunked=%s chunks=%s embedded=%s",
                job.id,
                stored_count,
                skipped_count,
                chunked_count,
                total_chunks,
                total_embedded,
            )

        except HTTPException as exc:
            await self._fail_job(job, str(exc.detail))
            raise
        except Exception as exc:
            logger.exception("Unexpected sync failure job_id=%s", job.id)
            await self._fail_job(job, "Unexpected error during Gmail sync")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gmail sync failed",
            ) from exc

        await self._session.refresh(job)
        return SyncJobResult(
            job_id=job.id,
            status=job.status,
            total_messages=job.total_messages or 0,
            processed_messages=job.processed_messages,
            stored_messages=stored_count,
            skipped_messages=skipped_count,
            chunked_messages=chunked_count,
            total_chunks=total_chunks,
            embedded_chunks=total_embedded,
            error_message=job.error_message,
        )

    async def _fail_job(self, job: SyncJob, message: str) -> None:
        job.status = SyncJobStatus.FAILED
        job.error_message = message[:2000]
        job.completed_at = datetime.now(UTC)
        await self._session.commit()

    async def _load_existing_gmail_ids(self, gmail_message_ids: list[str]) -> set[str]:
        if not gmail_message_ids:
            return set()
        result = await self._session.execute(
            select(Email.gmail_message_id).where(
                Email.user_id == self._user_id,
                Email.gmail_message_id.in_(gmail_message_ids),
            )
        )
        return set(result.scalars().all())

    async def _get_email_by_gmail_id(self, gmail_message_id: str) -> Email | None:
        result = await self._session.execute(
            select(Email).where(
                Email.user_id == self._user_id,
                Email.gmail_message_id == gmail_message_id,
            )
        )
        return result.scalar_one_or_none()

    async def _store_email(self, parsed: ParsedEmail) -> Email | None:
        """
        Insert email row. Returns Email if stored, None if duplicate.

        Uses a savepoint so duplicate key does not abort the outer sync transaction.
        """
        email = Email(
            user_id=self._user_id,
            gmail_message_id=parsed.gmail_message_id,
            thread_id=parsed.thread_id,
            subject=_truncate(parsed.subject, 998),
            sender=_truncate(parsed.sender, 320),
            recipient=_truncate(parsed.recipient, 320),
            body_plain=parsed.body_plain,
            received_at=parsed.received_at,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(email)
                await self._session.flush()
                await self._session.refresh(email)
            return email
        except IntegrityError:
            logger.debug(
                "Skipped duplicate gmail_message_id=%s user_id=%s",
                parsed.gmail_message_id,
                self._user_id,
            )
            return None


def _truncate(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    return value[:max_len] if len(value) > max_len else value


async def get_sync_job_for_user(
    session: AsyncSession,
    *,
    job_id: UUID,
    user_id: UUID,
) -> SyncJob:
    """Load sync job scoped to user (prevents cross-tenant reads)."""
    result = await session.execute(
        select(SyncJob).where(SyncJob.id == job_id, SyncJob.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync job not found",
        )
    return job