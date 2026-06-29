"""Tenant isolation: tenants table, tenant_id columns, scoped uniqueness, HNSW.

Adds multi-tenant isolation (audit C4) and the missing pgvector ANN index
(audit H6):

* New ``tenants`` table (hashed per-tenant API keys).
* ``tenant_id`` on inference_spans, budget_controls, cost_attribution,
  cache_entries — NOT NULL, defaulting to the all-zeros bootstrap tenant so
  existing rows backfill automatically.
* Uniqueness re-scoped per tenant (budget feature_tag, cache prompt_hash,
  attribution rollup key).
* HNSW cosine index on cache_entries.embedding (was a full scan per lookup).

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _tenant_id_column() -> sa.Column:
    """A fresh tenant_id column (NOT NULL; server_default backfills rows)."""
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        nullable=False,
        server_default=sa.text(f"'{_ZERO_UUID}'"),
    )


def upgrade() -> None:
    # ---- tenants -----------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column(
            "id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("api_key_hash", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("api_key_hash", name="uq_tenants_api_key_hash"),
    )
    op.create_index("ix_tenants_api_key_hash", "tenants", ["api_key_hash"])

    # ---- tenant_id columns (NOT NULL via server_default backfills rows) -----
    for table in ("inference_spans", "budget_controls", "cost_attribution", "cache_entries"):
        op.add_column(table, _tenant_id_column())

    # ---- spans indexes -----------------------------------------------------
    op.create_index("ix_spans_tenant_id", "inference_spans", ["tenant_id"])
    op.create_index("ix_spans_tenant_timestamp", "inference_spans", ["tenant_id", "timestamp"])
    op.create_index("ix_spans_tenant_feature_tag", "inference_spans", ["tenant_id", "feature_tag"])

    # ---- budgets: re-scope uniqueness per tenant ---------------------------
    op.drop_constraint("budget_controls_feature_tag_key", "budget_controls", type_="unique")
    op.create_unique_constraint(
        "uq_budget_tenant_feature", "budget_controls", ["tenant_id", "feature_tag"]
    )
    op.create_index("ix_budget_tenant_id", "budget_controls", ["tenant_id"])

    # ---- attribution: re-scope rollup uniqueness ---------------------------
    op.drop_constraint(
        "uq_attribution_feature_hour_provider_model", "cost_attribution", type_="unique"
    )
    op.create_unique_constraint(
        "uq_attribution_feature_hour_provider_model",
        "cost_attribution",
        ["tenant_id", "feature_tag", "hour_bucket", "provider", "model"],
    )
    op.create_index("ix_attribution_tenant_hour", "cost_attribution", ["tenant_id", "hour_bucket"])

    # ---- cache: re-scope uniqueness + add the missing HNSW index -----------
    op.drop_constraint("cache_entries_prompt_hash_key", "cache_entries", type_="unique")
    op.create_unique_constraint(
        "uq_cache_tenant_prompt_hash", "cache_entries", ["tenant_id", "prompt_hash"]
    )
    op.create_index("ix_cache_entries_tenant_id", "cache_entries", ["tenant_id"])
    op.create_index(
        "ix_cache_entries_embedding_hnsw",
        "cache_entries",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_cache_entries_embedding_hnsw", table_name="cache_entries")
    op.drop_index("ix_cache_entries_tenant_id", table_name="cache_entries")
    op.drop_constraint("uq_cache_tenant_prompt_hash", "cache_entries", type_="unique")
    op.create_unique_constraint("cache_entries_prompt_hash_key", "cache_entries", ["prompt_hash"])

    op.drop_index("ix_attribution_tenant_hour", table_name="cost_attribution")
    op.drop_constraint(
        "uq_attribution_feature_hour_provider_model", "cost_attribution", type_="unique"
    )
    op.create_unique_constraint(
        "uq_attribution_feature_hour_provider_model",
        "cost_attribution",
        ["feature_tag", "hour_bucket", "provider", "model"],
    )

    op.drop_index("ix_budget_tenant_id", table_name="budget_controls")
    op.drop_constraint("uq_budget_tenant_feature", "budget_controls", type_="unique")
    op.create_unique_constraint("budget_controls_feature_tag_key", "budget_controls", ["feature_tag"])

    op.drop_index("ix_spans_tenant_feature_tag", table_name="inference_spans")
    op.drop_index("ix_spans_tenant_timestamp", table_name="inference_spans")
    op.drop_index("ix_spans_tenant_id", table_name="inference_spans")

    for table in ("cache_entries", "cost_attribution", "budget_controls", "inference_spans"):
        op.drop_column(table, "tenant_id")

    op.drop_index("ix_tenants_api_key_hash", table_name="tenants")
    op.drop_table("tenants")
