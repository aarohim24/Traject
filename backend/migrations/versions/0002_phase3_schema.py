"""Phase 3 schema additions for cascade tracing and prompt cache advisor.

Adds ``trace_id`` and ``ab_test_group`` columns to ``inference_spans``
to support multi-agent cascade tracing (W3C TraceContext) and A/B router
result attribution introduced in Phase 3.

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Apply the Phase 3 schema additions.

    Adds nullable ``ab_test_group`` Text column to ``inference_spans``
    for A/B router group attribution.
    """
    op.add_column(
        "inference_spans",
        sa.Column("ab_test_group", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Reverse the Phase 3 schema additions."""
    op.drop_column("inference_spans", "ab_test_group")
