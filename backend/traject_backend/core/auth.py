"""Authentication and tenant resolution.

Every request authenticates with an API key. The key resolves to a tenant:

* If the key's SHA-256 hash matches a provisioned ``tenants`` row → that tenant.
* Else, if the key matches the global bootstrap key (``settings.api_key``,
  compared in constant time) → the :data:`DEFAULT_TENANT_ID` tenant. This keeps
  single-key / local deployments working without provisioning a tenant.
* Else → 401.

Handlers depend on :func:`get_current_tenant` to obtain the caller's
``tenant_id`` and MUST scope every query by it. The legacy
:func:`verify_api_key` dependency remains for authn-only endpoints.
"""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.core.config import settings
from traject_backend.core.database import get_db
from traject_backend.models.tenant import (
    DEFAULT_TENANT_ID,
    TenantRecord,
    hash_api_key,
)

INSECURE_DEFAULT_API_KEY = "dev-key-change-in-production"


def assert_secure_api_key() -> None:
    """Refuse to run with the well-known default key unless explicitly allowed.

    Called at startup. The default key ships in config/compose/helm; a
    deployment that forgets to override it would otherwise authorize anyone.
    Set ``allow_insecure_api_key=True`` (env ``ALLOW_INSECURE_API_KEY=true``)
    only for local development and tests.

    Raises:
        RuntimeError: When the API key is still the default and insecure use
            has not been explicitly permitted.
    """
    if settings.api_key == INSECURE_DEFAULT_API_KEY and not settings.allow_insecure_api_key:
        raise RuntimeError(
            "Refusing to start: TRAJECT_API_KEY is still the default "
            f"'{INSECURE_DEFAULT_API_KEY}'. Set a strong API key, or set "
            "ALLOW_INSECURE_API_KEY=true for local development only."
        )


async def get_current_tenant(
    x_api_key: Annotated[str | None, Header(alias="X-Traject-API-Key")] = None,
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Resolve the request's API key to a tenant id, or raise 401.

    Args:
        x_api_key: Value of the ``X-Traject-API-Key`` request header.
        db: Active async session for the tenant lookup.

    Returns:
        The authenticated caller's ``tenant_id``.

    Raises:
        HTTPException: 401 when the key is missing or unrecognized.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    # Bootstrap / single-tenant fast path first: constant-time compare to the
    # global key. This requires no DB round-trip, so single-tenant deployments
    # (and the test suite) authenticate without touching the tenants table.
    if hmac.compare_digest(x_api_key, settings.api_key):
        return DEFAULT_TENANT_ID

    # Provisioned per-tenant key (looked up by hash). Tolerate DB errors by
    # degrading to 401 rather than surfacing a 500 from the auth layer.
    try:
        row = (
            await db.execute(
                select(TenantRecord.id).where(
                    TenantRecord.api_key_hash == hash_api_key(x_api_key),
                    TenantRecord.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 — never 500 from auth
        row = None
    if row is not None:
        return row

    raise HTTPException(status_code=401, detail="Invalid API key")


CurrentTenant = Annotated[uuid.UUID, Depends(get_current_tenant)]
