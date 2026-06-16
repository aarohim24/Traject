"""Semantic cache API endpoints.

Provides lookup, store, invalidation, and statistics operations for the
pgvector-backed semantic cache.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.api.v1.spans import verify_api_key
from traject_backend.core.config import settings
from traject_backend.core.database import get_db
from traject_backend.models.cache_entry import CacheEntryRecord
from traject_backend.services.semantic_cache import (
    CacheLookupResponse,
    CacheStoreRequest,
    lookup,
    store,
)

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["cache"])


class CacheLookupRequest(BaseModel):
    """Request body for cache lookup.

    Attributes:
        prompt_hash: SHA-256 hex digest of the normalised prompt.
        prompt_embedding: 384-dimensional sentence embedding.
    """

    prompt_hash: str
    prompt_embedding: list[float]


class CacheInvalidateRequest(BaseModel):
    """Request body for cache invalidation.

    Exactly one of ``feature_tag`` or ``prompt_hash`` must be provided.

    Attributes:
        feature_tag: Delete all entries for this feature tag.
        prompt_hash: Delete the single entry with this hash.
    """

    feature_tag: str | None = None
    prompt_hash: str | None = None


@router.post(
    "/cache/lookup",
    response_model=CacheLookupResponse,
    dependencies=[Depends(verify_api_key)],
)
async def cache_lookup(
    request: CacheLookupRequest,
    db: AsyncSession = Depends(get_db),
) -> CacheLookupResponse:
    """Look up a prompt in the semantic cache.

    Args:
        request: Lookup request with hash and embedding.
        db: Injected async database session.

    Returns:
        CacheLookupResponse indicating hit status and optional preview.
    """
    return await lookup(
        request.prompt_hash,
        request.prompt_embedding,
        db,
        settings.cache_similarity_threshold,
    )


@router.post(
    "/cache/store",
    status_code=201,
    dependencies=[Depends(verify_api_key)],
)
async def cache_store(
    request: CacheStoreRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Store a new cache entry.

    Args:
        request: Cache entry data including hash, embedding, and response.
        db: Injected async database session.

    Returns:
        Confirmation dict.
    """
    await store(request, db)
    return {"status": "stored"}


@router.post(
    "/cache/invalidate",
    dependencies=[Depends(verify_api_key)],
)
async def cache_invalidate(
    request: CacheInvalidateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Invalidate cache entries by feature tag or prompt hash.

    Args:
        request: Specifies which entries to delete.
        db: Injected async database session.

    Returns:
        Dict with count of invalidated entries.
    """
    invalidated = 0

    if request.prompt_hash is not None:
        result = await db.execute(
            text(
                "DELETE FROM cache_entries WHERE prompt_hash = :hash"
            ),
            {"hash": request.prompt_hash},
        )
        invalidated = result.rowcount  # type: ignore[attr-defined]
    elif request.feature_tag is not None:
        result = await db.execute(
            text(
                "DELETE FROM cache_entries WHERE feature_tag = :tag"
            ),
            {"tag": request.feature_tag},
        )
        invalidated = result.rowcount  # type: ignore[attr-defined]

    await db.commit()
    return {"invalidated": invalidated}


@router.get(
    "/cache/stats",
    dependencies=[Depends(verify_api_key)],
)
async def cache_stats(
    db: AsyncSession = Depends(get_db),
    feature_tag: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return aggregate cache statistics.

    Args:
        db: Injected async database session.
        feature_tag: Restrict stats to a single feature tag (optional).

    Returns:
        Dict with hit_count, miss_count, hit_rate, total_cost_saved_usd,
        and entry_count.
    """
    stmt = select(
        func.count().label("entry_count"),
        func.coalesce(func.sum(CacheEntryRecord.hit_count), 0).label("hit_count"),
        func.coalesce(
            func.sum(CacheEntryRecord.cost_saved_usd), Decimal("0")
        ).label("total_cost_saved_usd"),
    )
    if feature_tag is not None:
        stmt = stmt.where(CacheEntryRecord.feature_tag == feature_tag)

    result = await db.execute(stmt)
    row = result.fetchone()

    entry_count = int(row.entry_count) if row else 0
    hit_count = int(row.hit_count) if row else 0
    cost_saved = Decimal(str(row.total_cost_saved_usd)) if row else Decimal("0")
    # miss_count and hit_rate are estimated from hit_count vs entries
    hit_rate = hit_count / max(entry_count, 1)

    return {
        "entry_count": entry_count,
        "hit_count": hit_count,
        "miss_count": 0,  # requires separate tracking table; placeholder
        "hit_rate": hit_rate,
        "total_cost_saved_usd": str(cost_saved),
    }
