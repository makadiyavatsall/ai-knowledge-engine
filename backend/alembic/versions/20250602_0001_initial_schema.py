"""Initial schema: users, emails, chunks, sync_jobs.

Revision ID: 20250602_0001
Revises:
Create Date: 2025-06-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20250602_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("google_sub", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)
    op.create_index(op.f("ix_users_google_sub"), "users", ["google_sub"], unique=True)

    op.create_table(
        "emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=998), nullable=True),
        sa.Column("sender", sa.String(length=320), nullable=True),
        sa.Column("recipient", sa.String(length=320), nullable=True),
        sa.Column("body_plain", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "gmail_message_id", name="uq_emails_user_gmail_message"),
    )
    op.create_index(op.f("ix_emails_user_id"), "emails", ["user_id"], unique=False)
    op.create_index(op.f("ix_emails_thread_id"), "emails", ["thread_id"], unique=False)
    op.create_index(op.f("ix_emails_sender"), "emails", ["sender"], unique=False)
    op.create_index(op.f("ix_emails_received_at"), "emails", ["received_at"], unique=False)

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_id", "chunk_index", name="uq_chunks_email_index"),
    )
    op.create_index(op.f("ix_chunks_email_id"), "chunks", ["email_id"], unique=False)

    op.create_table(
        "sync_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="sync_job_status",
            ),
            nullable=False,
        ),
        sa.Column("total_messages", sa.Integer(), nullable=True),
        sa.Column("processed_messages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sync_jobs_user_id"), "sync_jobs", ["user_id"], unique=False)
    op.create_index(op.f("ix_sync_jobs_status"), "sync_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sync_jobs_status"), table_name="sync_jobs")
    op.drop_index(op.f("ix_sync_jobs_user_id"), table_name="sync_jobs")
    op.drop_table("sync_jobs")
    op.execute("DROP TYPE IF EXISTS sync_job_status")

    op.drop_index(op.f("ix_chunks_email_id"), table_name="chunks")
    op.drop_table("chunks")

    op.drop_index(op.f("ix_emails_received_at"), table_name="emails")
    op.drop_index(op.f("ix_emails_sender"), table_name="emails")
    op.drop_index(op.f("ix_emails_thread_id"), table_name="emails")
    op.drop_index(op.f("ix_emails_user_id"), table_name="emails")
    op.drop_table("emails")

    op.drop_index(op.f("ix_users_google_sub"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
