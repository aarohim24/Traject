"""Pydantic v2 data models for the Traject SDK.

This module defines the canonical cross-boundary data structures used
throughout the SDK: :class:`InferenceSpan`, :class:`Segment`, and
:class:`CompressionResult`. It also re-exports :class:`ModelPricing` from
:mod:`traject.core.pricing` so callers can import all model types from a single
location.

All monetary fields use :class:`decimal.Decimal` (ADR-006). Enums are used
for all categorical values. No raw ``dict`` objects cross module boundaries.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from traject.classifier.artifact_type import ArtifactType
from traject.core.pricing import ModelPricing

__all__ = [
    "CompressionResult",
    "InferenceSpan",
    "ModelPricing",
    "Segment",
]

# ---------------------------------------------------------------------------
# InferenceSpan
# ---------------------------------------------------------------------------

_PROMPT_HASH_RE = re.compile(r"^[a-f0-9]{64}$")


class InferenceSpan(BaseModel):
    """Immutable record of a single instrumented LLM API call.

    Every field is populated by the instrumentor immediately after the
    provider response is received. The span is emitted to the configured
    OTEL exporter and is never mutated after creation.

    Attributes:
        id: Unique identifier for this span (UUID v4).
        trace_id: Trace identifier grouping related spans.
        parent_span_id: Parent span identifier, or ``None`` for root spans.
        span_name: Human-readable span label in ``gen_ai.<provider>.<model>``
            format.
        timestamp: UTC wall-clock time at which the instrumented call started.
        duration_ms: Elapsed time of the provider call in milliseconds
            (>= 0).
        provider: Provider name (e.g. ``"openai"``, ``"anthropic"``).
        model: Model identifier as returned by the provider response.
        api_version: Provider API version string, or ``None`` if not
            surfaced.
        input_tokens: Number of prompt/input tokens consumed (>= 0).
        output_tokens: Number of completion/output tokens generated (>= 0).
        cached_tokens: Number of tokens served from the provider cache
            (>= 0).
        token_count_method: How token counts were obtained — ``"exact"``
            from provider usage fields, ``"estimated"`` via tiktoken.
        cost_usd: Calculated USD cost as a ``Decimal``, or ``None`` for
            unknown models.
        feature_tag: Logical grouping label for cost attribution.
        prompt_hash: SHA-256 hex digest of the normalized prompt content
            (64 lowercase hex characters). Raw prompt text is never stored.
        artifact_type: Classified artifact type of the first message.
        compression_applied: ``True`` when compression was applied and
            messages were actually modified (shadow mode off).
        shadow_mode: ``True`` when the compression pipeline ran but original
            messages were forwarded unchanged.
        pre_compression_tokens: Total token count before compression, or
            ``None`` if compression did not run.
        tokens_saved: Tokens eliminated by compression, or ``None`` if
            compression did not run.
        cache_hit: ``True`` when at least one token was served from the
            provider cache.
        environment: Deployment environment label (e.g. ``"production"``).
        batch_eligible: ``True`` when this span is eligible for submission
            to a provider batch API (non-latency-sensitive workloads).
            Defaults to ``False``.
    """

    id: UUID
    trace_id: str
    parent_span_id: str | None
    span_name: str
    timestamp: datetime
    duration_ms: int
    provider: str
    model: str
    api_version: str | None
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    token_count_method: Literal["exact", "estimated"]
    cost_usd: Decimal | None
    feature_tag: str
    prompt_hash: str  # SHA-256 hex digest — 64 lowercase hex chars
    artifact_type: ArtifactType
    compression_applied: bool
    shadow_mode: bool
    pre_compression_tokens: int | None
    tokens_saved: int | None
    cache_hit: bool
    environment: str
    batch_eligible: bool = False

    @field_validator("duration_ms", mode="after")
    @classmethod
    def _validate_duration_ms(cls, v: int) -> int:
        """Assert duration_ms is non-negative."""
        if v < 0:
            raise ValueError(f"duration_ms must be >= 0, got {v}")
        return v

    @field_validator("input_tokens", "output_tokens", "cached_tokens", mode="after")
    @classmethod
    def _validate_token_counts(cls, v: int) -> int:
        """Assert token count fields are non-negative."""
        if v < 0:
            raise ValueError(f"Token count must be >= 0, got {v}")
        return v

    @field_validator("prompt_hash", mode="after")
    @classmethod
    def _validate_prompt_hash(cls, v: str) -> str:
        """Assert prompt_hash is a 64-character lowercase hex SHA-256 digest."""
        if not _PROMPT_HASH_RE.match(v):
            raise ValueError(
                f"prompt_hash must match ^[a-f0-9]{{64}}$, got {v!r} "
                f"(length {len(v)})"
            )
        return v

    @field_validator("cost_usd", mode="after")
    @classmethod
    def _validate_cost_usd(cls, v: Decimal | None) -> Decimal | None:
        """Assert cost_usd is None or a non-negative Decimal."""
        if v is not None and v < Decimal("0"):
            raise ValueError(f"cost_usd must be None or >= Decimal('0'), got {v}")
        return v


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------

_EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output dimension


class Segment(BaseModel):
    """A single message segment within a compression analysis pipeline.

    Segments are produced by the segment parser from the normalized message
    list. Each segment carries a pre-computed token count, a relevance
    embedding (populated by the relevance scorer), and protection flags that
    prevent the compression engine from dropping high-priority content.

    Attributes:
        index: Zero-based position of this segment in the original message
            list.
        role: Message role string (e.g. ``"system"``, ``"user"``,
            ``"assistant"``).
        content: Text content of the segment.
        artifact_type: Classified artifact type for this segment.
        token_count: Number of tokens in ``content`` as counted by tiktoken
            (>= 0).
        turn_index: Conversational turn index, incremented each time the
            dialogue transitions from assistant to user (>= 0).
        protected: ``True`` when the compression engine must not drop or
            summarize this segment.
        embedding: 384-dimensional unit-norm float embedding produced by
            ``all-MiniLM-L6-v2``, or ``None`` before the scorer runs.
    """

    index: int
    role: str
    content: str
    artifact_type: ArtifactType
    token_count: int
    turn_index: int
    protected: bool
    embedding: list[float] | None = None

    @field_validator("token_count", mode="after")
    @classmethod
    def _validate_token_count(cls, v: int) -> int:
        """Assert token_count is non-negative."""
        if v < 0:
            raise ValueError(f"token_count must be >= 0, got {v}")
        return v

    @field_validator("turn_index", mode="after")
    @classmethod
    def _validate_turn_index(cls, v: int) -> int:
        """Assert turn_index is non-negative."""
        if v < 0:
            raise ValueError(f"turn_index must be >= 0, got {v}")
        return v

    @field_validator("embedding", mode="after")
    @classmethod
    def _validate_embedding(cls, v: list[float] | None) -> list[float] | None:
        """Assert embedding is None or a list of exactly 384 floats."""
        if v is not None and len(v) != _EMBEDDING_DIM:
            raise ValueError(
                f"embedding must be None or a list of exactly {_EMBEDDING_DIM} floats, "
                f"got a list of length {len(v)}"
            )
        return v


# ---------------------------------------------------------------------------
# CompressionResult
# ---------------------------------------------------------------------------


class CompressionResult(BaseModel):
    """Result of a single compression pipeline run.

    Produced by :func:`traject.compression.engine.compress` after every call,
    regardless of whether compression was actually applied. In shadow mode,
    ``messages`` contains the original unmodified message list and
    ``tokens_saved`` is 0.

    Attributes:
        original_tokens: Total token count of the input message list.
        compressed_tokens: Total token count after applying compression
            decisions.
        tokens_saved: Tokens eliminated; must equal
            ``original_tokens - compressed_tokens``.
        compression_ratio: Fraction of tokens eliminated, in ``[0.0, 1.0]``.
        segments_analyzed: Total number of segments evaluated.
        segments_retained: Segments kept verbatim.
        segments_summarized: Segments replaced with a short summary.
        segments_dropped: Segments removed entirely.
        shadow_mode: ``True`` when original messages were returned unchanged
            despite compression analysis running.
        strategy_applied: Name of the
            :class:`~traject.compression.strategies.CompressionStrategy` that
            was applied (stored as a string value for forward compatibility).
        messages: The final message list returned to the caller.
        warnings: Human-readable diagnostic messages generated during
            the pipeline run.
        cache_hits: Number of segment scores served from the
            :class:`~traject.compression.relevance_scorer.CompressionCache`
            during the scoring step. Zero when caching is disabled or when
            no task hint is provided.
        cache_hit_rate: Fraction of scoring lookups satisfied by the cache,
            in ``[0.0, 1.0]``. Zero when no lookups were made.
    """

    original_tokens: int
    compressed_tokens: int
    tokens_saved: int
    compression_ratio: float
    segments_analyzed: int
    segments_retained: int
    segments_summarized: int
    segments_dropped: int
    shadow_mode: bool
    strategy_applied: str  # CompressionStrategy string value — str for forward compat
    messages: list[Any]  # Any: message dicts may contain heterogeneous values
    warnings: list[str]
    cache_hits: int = 0
    cache_hit_rate: float = 0.0

    @field_validator("compression_ratio", mode="after")
    @classmethod
    def _validate_compression_ratio(cls, v: float) -> float:
        """Assert compression_ratio is in [0.0, 1.0]."""
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"compression_ratio must be in [0.0, 1.0], got {v}"
            )
        return v

    @model_validator(mode="after")
    def _validate_tokens_saved(self) -> CompressionResult:
        """Assert tokens_saved equals original_tokens minus compressed_tokens."""
        expected = self.original_tokens - self.compressed_tokens
        if self.tokens_saved != expected:
            raise ValueError(
                f"tokens_saved ({self.tokens_saved}) must equal "
                f"original_tokens - compressed_tokens "
                f"({self.original_tokens} - {self.compressed_tokens} = {expected})"
            )
        return self

    @model_validator(mode="after")
    def _validate_segment_counts(self) -> CompressionResult:
        """Assert segment counts sum to segments_analyzed."""
        total = (
            self.segments_retained
            + self.segments_summarized
            + self.segments_dropped
        )
        if total != self.segments_analyzed:
            raise ValueError(
                f"segments_retained ({self.segments_retained}) + "
                f"segments_summarized ({self.segments_summarized}) + "
                f"segments_dropped ({self.segments_dropped}) = {total}, "
                f"but segments_analyzed = {self.segments_analyzed}"
            )
        return self
