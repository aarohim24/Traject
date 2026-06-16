"""Client-side semantic cache for the Traject SDK.

Provides :class:`SemanticCacheClient` which computes embeddings locally
using the Phase 1 ``all-MiniLM-L6-v2`` singleton and delegates cache
lookups and stores to the Traject backend via :class:`~traject.backend_client.BackendClient`.

All public methods are fail-open: they catch every exception and return
``None`` / no-op rather than raising.  The inference path must never be
blocked by cache failures.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import structlog

from traject.backend_client import BackendClient

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CacheLookupResult:
    """Result of a :meth:`SemanticCacheClient.lookup` call.

    Attributes:
        hit: Whether the cache contained a matching entry.
        response_preview: First 200 characters of the cached LLM response,
            or ``None`` on a miss.
        similarity: Cosine similarity of the matched embedding, or ``None``
            for exact-hash hits and misses.
    """

    hit: bool
    response_preview: str | None = None
    similarity: float | None = None


def _hash_messages(messages: list[dict[str, Any]]) -> str:
    """Compute a SHA-256 hex digest from normalized message content.

    Mirrors the normalization in :func:`traject.core.instrumentor._hash_prompt`:
    concatenate all text content strings, strip whitespace, lowercase.

    Args:
        messages: List of message dicts with optional ``"content"`` fields.

    Returns:
        64-character lowercase hex SHA-256 digest.
    """
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content.strip().lower())
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_val = part.get("text", "")
                    if isinstance(text_val, str):
                        parts.append(text_val.strip().lower())
    normalized = " ".join(parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _get_embedding_model() -> Any:  # noqa: ANN401 — SentenceTransformer avoids heavy dep at import
    """Return the Phase 1 all-MiniLM-L6-v2 model singleton.

    Reuses the module-level singleton from
    :mod:`traject.compression.relevance_scorer` so that no additional model
    load is required.

    Returns:
        The ``SentenceTransformer`` singleton.
    """
    from traject.compression.relevance_scorer import _model

    return _model


class SemanticCacheClient:
    """Client-side semantic cache that delegates to the Traject backend.

    Computes embeddings locally using the Phase 1 ``all-MiniLM-L6-v2``
    singleton (no extra model load) and calls the backend cache endpoints
    via the provided :class:`~traject.backend_client.BackendClient`.

    Args:
        backend_client: A configured :class:`~traject.backend_client.BackendClient`
            instance pointing at the Traject backend service.
    """

    def __init__(self, backend_client: BackendClient) -> None:
        self._client = backend_client

    async def lookup(
        self,
        messages: list[dict[str, Any]],
        model: str,
    ) -> CacheLookupResult | None:
        """Check the semantic cache before calling the LLM provider.

        Computes a SHA-256 prompt hash and a 384-dimensional embedding
        locally, then calls ``POST /v1/cache/lookup`` on the backend.

        Args:
            messages: The conversation messages to look up.
            model: The LLM model identifier (included for cache keying).

        Returns:
            :class:`CacheLookupResult` on success, or ``None`` on any error
            (fail open).
        """
        try:
            prompt_hash = _hash_messages(messages)
            content = " ".join(
                msg.get("content", "") if isinstance(msg.get("content"), str) else ""
                for msg in messages
            )
            embedding_model = _get_embedding_model()
            embedding: list[float] = embedding_model.encode(
                content, normalize_embeddings=True
            ).tolist()

            response = await self._client._client.post(
                "/v1/cache/lookup",
                json={
                    "prompt_hash": prompt_hash,
                    "prompt_embedding": embedding,
                },
            )

            if not response.is_success:
                return None

            data = response.json()
            return CacheLookupResult(
                hit=bool(data.get("hit", False)),
                response_preview=data.get("response_preview"),
                similarity=data.get("similarity"),
            )

        except Exception as exc:
            _log.warning("traject.cache.lookup.error", error=str(exc))
            return None

    async def store(
        self,
        messages: list[dict[str, Any]],
        response_text: str,
        model: str,
        feature_tag: str,
        cost_usd: Decimal,
    ) -> None:
        """Store a response in the semantic cache after a successful LLM call.

        Fire-and-forget: any error is caught and logged, never raised.

        Args:
            messages: The conversation messages that produced the response.
            response_text: The LLM response to cache.
            model: The LLM model identifier.
            feature_tag: Cost-attribution label for the call.
            cost_usd: USD cost of the original call.
        """
        try:
            prompt_hash = _hash_messages(messages)
            content = " ".join(
                msg.get("content", "") if isinstance(msg.get("content"), str) else ""
                for msg in messages
            )
            embedding_model = _get_embedding_model()
            embedding: list[float] = embedding_model.encode(
                content, normalize_embeddings=True
            ).tolist()

            await self._client._client.post(
                "/v1/cache/store",
                json={
                    "prompt_hash": prompt_hash,
                    "prompt_embedding": embedding,
                    "response_preview": response_text[:200],
                    "model": model,
                    "feature_tag": feature_tag,
                    "cost_usd": str(cost_usd),
                },
            )
        except Exception as exc:
            _log.warning("traject.cache.store.error", error=str(exc))
