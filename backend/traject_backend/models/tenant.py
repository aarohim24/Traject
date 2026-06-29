"""Tenant model and API-key helpers for multi-tenant isolation.

Every data table (spans, budgets, attribution, cache) carries a ``tenant_id``.
Requests authenticate with a per-tenant API key whose SHA-256 hash is stored
here; the key itself is never persisted. A fixed :data:`DEFAULT_TENANT_ID`
provides backwards compatibility for single-key / local deployments that
authenticate with ``settings.api_key`` rather than a provisioned tenant key.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column

from traject_backend.models.base import Base

# Stable sentinel tenant for rows created before tenancy existed and for
# deployments that authenticate with the global bootstrap key (settings.api_key).
DEFAULT_TENANT_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def hash_api_key(api_key: str) -> str:
    """Return the SHA-256 hex digest of *api_key* (the stored, comparable form)."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class TenantRecord(Base):
    """A tenant (team/org) that owns its spans, budgets, attribution, and cache.

    Attributes:
        id: UUID primary key.
        name: Human-readable tenant name.
        api_key_hash: SHA-256 hex digest of the tenant's API key (unique).
        is_active: Whether the tenant may authenticate.
        created_at: Server-side creation timestamp.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )
