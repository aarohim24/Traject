"""Semantic cache service for the Traject backend.

Provides exact-hash and pgvector cosine-similarity lookup against the
``cache_entries`` table, and stores new entries with upsert semantics.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import structlog
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.core.config import settings
from traject_backend.models.cache_entry import CacheEntryRecord
from traject_backend.models.tenant import DEFAULT_TENANT_ID

_log = structlog.get_logger(__name__)


class CacheLookupResponse(BaseModel):
    """Result of a cache lookup request.

    Attributes:
        hit: Whether a cache entry was found at or above the similarity
            threshold.
        response_preview: First 200 characters of the cached response, or
            ``None`` on a miss.
        similarity: Cosine similarity of the matched embedding, or ``None``
            on a miss or exact-hash hit.
    """

    hit: bool
    response_preview: str | None = None
    similarity: float | None = None


class CacheStoreRequest(BaseModel):
    """Request body for storing a new cache entry.

    Attributes:
        prompt_hash: SHA-256 hex digest of the normalised prompt.
        prompt_embedding: 384-dimensional sentence embedding.
        response_preview: First 200 characters of the LLM response.
        model: Model identifier used for the original call.
        feature_tag: Cost-attribution label.
        cost_usd: USD cost of the original call (used to accumulate savings).
    """

    prompt_hash: str
    prompt_embedding: list[float]
    response_preview: str
    model: str
    feature_tag: str
    cost_usd: Decimal = Decimal("0")


async def lookup(
    prompt_hash: str,
    embedding: list[float],
    db: AsyncSession,
    threshold: float,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> CacheLookupResponse:
    """Look up a prompt in the semantic cache.

    First performs an exact SHA-256 hash match (fast path).  On a miss,
    falls back to a pgvector cosine-similarity nearest-neighbour search.
    Returns a cache hit only when the similarity meets or exceeds
    ``threshold``.

    On any database error the function returns a ``CacheLookupResponse``
    with ``hit=False`` (fail open) so that cache failures never block
    inference.

    Args:
        prompt_hash: SHA-256 hex digest of the normalised prompt.
        embedding: 384-dimensional sentence embedding of the prompt.
        db: An active async SQLAlchemy session.
        threshold: Minimum cosine similarity required for a cache hit.

    Returns:
        A :class:`CacheLookupResponse` indicating whether a hit was found.
    """
    try:
        # ------------------------------------------------------------------
        # Fast path: exact hash lookup
        # ------------------------------------------------------------------
        exact_result = await db.execute(
            select(CacheEntryRecord).where(
                CacheEntryRecord.tenant_id == tenant_id,
                CacheEntryRecord.prompt_hash == prompt_hash,
            )
        )
        exact_row = exact_result.scalar_one_or_none()
        if exact_row is not None:
            # Update hit tracking
            await db.execute(
                text(
                    "UPDATE cache_entries SET hit_count = hit_count + 1, "
                    "last_hit_at = now() WHERE prompt_hash = :hash "
                    "AND tenant_id = :tenant_id"
                ),
                {"hash": prompt_hash, "tenant_id": str(tenant_id)},
            )
            await db.commit()
            return CacheLookupResponse(
                hit=True,
                response_preview=exact_row.response_preview,
                similarity=None,
            )

        # ------------------------------------------------------------------
        # Slow path: pgvector cosine similarity search
        # ------------------------------------------------------------------
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
        # Scope the ANN search to the tenant — without this filter a lookup
        # could return another tenant's cached response (and the HNSW index is
        # tenant-agnostic, so the filter also prevents cross-tenant matches).
        sim_result = await db.execute(
            text(
                "SELECT id, response_preview, "
                "1 - (embedding <=> :query_embedding::vector) AS similarity "
                "FROM cache_entries "
                "WHERE tenant_id = :tenant_id "
                "ORDER BY embedding <=> :query_embedding::vector "
                "LIMIT 1"
            ),
            {"query_embedding": embedding_str, "tenant_id": str(tenant_id)},
        )
        row = sim_result.fetchone()

        if row is None:
            return CacheLookupResponse(hit=False)

        similarity = float(row.similarity)
        if similarity >= threshold:
            return CacheLookupResponse(
                hit=True,
                response_preview=str(row.response_preview),
                similarity=similarity,
            )
        return CacheLookupResponse(hit=False, similarity=similarity)

    except Exception as exc:  # noqa: BLE001
        _log.warning("traject.cache.lookup.error", error=str(exc))
        return CacheLookupResponse(hit=False)


async def store(
    request: CacheStoreRequest,
    db: AsyncSession,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> None:
    """Insert a new cache entry or update an existing one on hash collision.

    On conflict with an existing ``prompt_hash``, increments ``hit_count``
    and updates ``last_hit_at`` rather than inserting a duplicate row.

    Args:
        request: The cache entry data to persist.
        db: An active async SQLAlchemy session.
    """
    try:
        expires_at = datetime.utcnow() + timedelta(
            seconds=settings.redis_cache_ttl_seconds
        )
        now = datetime.utcnow()

        stmt = pg_insert(CacheEntryRecord).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            prompt_hash=request.prompt_hash,
            embedding=request.prompt_embedding,
            response_preview=request.response_preview[:200],
            model=request.model,
            feature_tag=request.feature_tag,
            similarity_threshold=settings.cache_similarity_threshold,
            created_at=now,
            expires_at=expires_at,
            last_hit_at=now,
            hit_count=0,
            cost_saved_usd=Decimal("0"),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "prompt_hash"],
            set_={
                "hit_count": text("cache_entries.hit_count + 1"),
                "last_hit_at": now,
                # Bound parameter — never interpolate a value into raw SQL.
                "cost_saved_usd": text(
                    "cache_entries.cost_saved_usd + :cost_delta"
                ).bindparams(cost_delta=request.cost_usd or Decimal("0")),
            },
        )
        await db.execute(stmt)
        await db.commit()
        _log.debug("traject.cache.stored", prompt_hash=request.prompt_hash)

    except Exception as exc:  # noqa: BLE001
        _log.warning("traject.cache.store.error", error=str(exc))
