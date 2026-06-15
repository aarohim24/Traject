"""Phase 5 schema additions for batch routing and benchmark registry.

Adds a nullable ``routing_decision`` column to ``inference_spans`` (required
by the ML training service), creates the ``batch_jobs`` table used by
``JobTracker`` to persist batch-API submissions, and creates the
``benchmark_submissions`` table used by the public benchmark registry.

Revision ID: 0003
Revises: 0002
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Apply the Phase 5 schema additions.

    Execution order:
    1. Add nullable ``routing_decision`` Text column to ``inference_spans``.
    2. Create ``batch_jobs`` table with all columns and indexes.
    3. Create ``benchmark_submissions`` table with all columns and index.
    """
    # ------------------------------------------------------------------ #
    # inference_spans — add routing_decision column                       #
    # ------------------------------------------------------------------ #
    op.add_column(
        "inference_spans",
        sa.Column("routing_decision", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------ #
    # batch_jobs                                                          #
    # ------------------------------------------------------------------ #
    op.create_table(
        "batch_jobs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("job_id", sa.String(), nullable=False, unique=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("span_count", sa.Integer(), nullable=False),
        sa.Column(
            "estimated_completion_at",
            sa.DateTime(timezone=False),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_batch_jobs_job_id", "batch_jobs", ["job_id"])
    op.create_index("ix_batch_jobs_status", "batch_jobs", ["status"])

    # ------------------------------------------------------------------ #
    # benchmark_submissions                                               #
    # ------------------------------------------------------------------ #
    op.create_table(
        "benchmark_submissions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("sdk_version", sa.String(), nullable=False),
        sa.Column("python_version", sa.String(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("p50_cost_usd", sa.String(), nullable=False),
        sa.Column("p95_cost_usd", sa.String(), nullable=False),
        sa.Column("p50_compression_ratio", sa.Float(), nullable=False),
        sa.Column("p95_compression_ratio", sa.Float(), nullable=False),
        sa.Column("avg_routing_accuracy", sa.Float(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_benchmarks_submitted_at", "benchmark_submissions", ["submitted_at"]
    )


def downgrade() -> None:
    """Reverse the Phase 5 schema additions.

    Drops objects in reverse creation order:
    1. Drop ``benchmark_submissions`` table and its index.
    2. Drop ``batch_jobs`` table and its indexes.
    3. Drop the ``routing_decision`` column from ``inference_spans``.
    """
    op.drop_table("benchmark_submissions")
    op.drop_table("batch_jobs")
    op.drop_column("inference_spans", "routing_decision")
