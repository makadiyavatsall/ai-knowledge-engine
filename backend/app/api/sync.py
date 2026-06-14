"""Sync routes: POST /sync/trigger and GET /sync/status for Gmail ingestion jobs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.sync_job import SyncJobStatus
from app.services.gmail import GmailProfile, GmailService
from app.services.ingestion import IngestionService, SyncJobResult, get_sync_job_for_user

router = APIRouter(prefix="/sync", tags=["sync"])


class GmailProfileResponse(BaseModel):
    email_address: str
    messages_total: int
    threads_total: int
    history_id: str


class SyncTriggerResponse(BaseModel):
    job_id: UUID
    status: SyncJobStatus
    total_messages: int
    processed_messages: int
    stored_messages: int
    skipped_messages: int
    chunked_messages: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0
    error_message: str | None = None


class SyncStatusResponse(BaseModel):
    job_id: UUID
    status: SyncJobStatus
    total_messages: int | None
    processed_messages: int
    error_message: str | None
    started_at: str | None = None
    completed_at: str | None = None


@router.get("/gmail/profile", response_model=GmailProfileResponse)
async def get_gmail_profile(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> GmailProfileResponse:
    """Return authenticated user's Gmail mailbox profile."""
    profile: GmailProfile = await GmailService(session, user_id).get_profile()
    return GmailProfileResponse(
        email_address=profile.email_address,
        messages_total=profile.messages_total,
        threads_total=profile.threads_total,
        history_id=profile.history_id,
    )


@router.post("/trigger", response_model=SyncTriggerResponse)
async def trigger_sync(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SyncTriggerResponse:
    """
    Manually run Gmail ingestion synchronously (MVP).

    Fetches messages, stores new emails, chunks text, and sets indexed_at.
    """
    ingestion = IngestionService(session, user_id)
    result: SyncJobResult = await ingestion.run_sync()

    return SyncTriggerResponse(
        job_id=result.job_id,
        status=result.status,
        total_messages=result.total_messages,
        processed_messages=result.processed_messages,
        stored_messages=result.stored_messages,
        skipped_messages=result.skipped_messages,
        chunked_messages=result.chunked_messages,
        total_chunks=result.total_chunks,
        embedded_chunks=result.embedded_chunks,
        error_message=result.error_message,
    )


@router.get("/status/{job_id}", response_model=SyncStatusResponse)
async def get_sync_status(
    job_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> SyncStatusResponse:
    """Poll sync job progress (scoped to authenticated user)."""
    job = await get_sync_job_for_user(session, job_id=job_id, user_id=user_id)
    return SyncStatusResponse(
        job_id=job.id,
        status=job.status,
        total_messages=job.total_messages,
        processed_messages=job.processed_messages,
        error_message=job.error_message,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )
