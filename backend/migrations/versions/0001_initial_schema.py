"""Initial database schema for Traject backend.

Creates the pgvector extension and all four tables:
- inference_spans
- cost_attribution
- budget_controls
- cache_entries

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Apply the initial schema migration.

    Creates the pgvector extension, then creates all four tables in
    dependency order.  All indexes and constraints are created inline.
    """
    # Enable pgvector extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------ #
    # inference_spans                                                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "inference_spans",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("parent_span_id", sa.String(), nullable=True),
        sa.Column("span_name", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "cached_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("token_count_method", sa.String(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 8), nullable=True),
        sa.Column("feature_tag", sa.String(), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column(
            "compression_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "shadow_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("pre_compression_tokens", sa.Integer(), nullable=True),
        sa.Column("tokens_saved", sa.Integer(), nullable=True),
        sa.Column(
            "cache_hit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_spans_trace_id", "inference_spans", ["trace_id"])
    op.create_index("ix_spans_timestamp", "inference_spans", ["timestamp"])
    op.create_index("ix_spans_provider", "inference_spans", ["provider"])
    op.create_index("ix_spans_model", "inference_spans", ["model"])
    op.create_index("ix_spans_feature_tag", "inference_spans", ["feature_tag"])
    op.create_index("ix_spans_environment", "inference_spans", ["environment"])
    op.create_index(
        "ix_spans_feature_tag_timestamp",
        "inference_spans",
        ["feature_tag", "timestamp"],
    )
    op.create_index(
        "ix_spans_environment_timestamp",
        "inference_spans",
        ["environment", "timestamp"],
    )

    # ------------------------------------------------------------------ #
    # cost_attribution                                                     #
    # ------------------------------------------------------------------ #
    op.create_table(
        "cost_attribution",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("feature_tag", sa.String(), nullable=False),
        sa.Column("hour_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column(
            "total_input_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_output_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_cached_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_cost_usd",
            sa.Numeric(12, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_tokens_saved",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_saved_compression_usd",
            sa.Numeric(12, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_saved_cache_usd",
            sa.Numeric(12, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "call_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cache_hit_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "p50_latency_ms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "p95_latency_ms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "feature_tag",
            "hour_bucket",
            "provider",
            "model",
            name="uq_attribution_feature_hour_provider_model",
        ),
    )
    op.create_index("ix_attribution_hour_bucket", "cost_attribution", ["hour_bucket"])
    op.create_index("ix_attribution_feature_tag", "cost_attribution", ["feature_tag"])

    # ------------------------------------------------------------------ #
    # budget_controls                                                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "budget_controls",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("feature_tag", sa.String(), nullable=False, unique=True),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("budget_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column(
            "alert_threshold_pct",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.8"),
        ),
        sa.Column(
            "hard_stop",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("alert_webhook_url", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------ #
    # cache_entries (requires pgvector)                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "cache_entries",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("prompt_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("response_preview", sa.String(200), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("feature_tag", sa.String(), nullable=False),
        sa.Column(
            "similarity_threshold",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.92"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_hit_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "hit_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_saved_usd",
            sa.Numeric(10, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index(
        "ix_cache_entries_prompt_hash", "cache_entries", ["prompt_hash"]
    )
    op.create_index(
        "ix_cache_entries_feature_tag", "cache_entries", ["feature_tag"]
    )
    op.create_index(
        "ix_cache_entries_expires_at", "cache_entries", ["expires_at"]
    )


def downgrade() -> None:
    """Reverse the initial schema migration.

    Drops all four tables in reverse creation order, then drops the
    pgvector extension.
    """
    op.drop_table("cache_entries")
    op.drop_table("budget_controls")
    op.drop_table("cost_attribution")
    op.drop_table("inference_spans")
    op.execute("DROP EXTENSION IF EXISTS vector")
