"""Unit and property-based tests for CompressionCache.

Validates the following correctness properties:

P-CACHE-1  Cached and uncached ``score_segments`` runs produce identical
           scores for identical inputs.
P-CACHE-2  A second call with the same segment content and task hint
           produces a cache hit.
P-CACHE-3  ``hit_rate`` equals ``hits / (hits + misses)`` for all
           non-zero lookup counts.
P-CACHE-4  Cache is disabled (zero hits) when no task hint is provided,
           since semantic scoring is inactive.
P-CACHE-5  ``compress()`` result exposes ``cache_hits`` and
           ``cache_hit_rate`` fields.
"""
from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from traject.classifier.artifact_type import ArtifactType
from traject.compression.engine import compress
from traject.compression.relevance_scorer import (
    CompressionCache,
    score_segments,
)
from traject.compression.strategies import CompressionConfig, CompressionStrategy
from traject.models import Segment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seg(
    index: int,
    content: str,
    turn_index: int,
    protected: bool = False,
    art_type: ArtifactType = ArtifactType.USER_MESSAGE,
) -> Segment:
    """Build a minimal Segment for testing."""
    return Segment(
        index=index,
        role="user",
        content=content,
        artifact_type=art_type,
        token_count=len(content.split()),
        turn_index=turn_index,
        protected=protected,
    )


def _live_config(
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
) -> CompressionConfig:
    """Return a non-shadow config with all turns eligible for compression."""
    return CompressionConfig(
        strategy=strategy,
        target_reduction_pct=0.20,
        min_turns_protected=0,
        protect_system_prompt=True,
        shadow_mode=False,
    )


def _msgs(*contents: str) -> list[dict[str, Any]]:
    """Build a minimal messages list from content strings."""
    return [{"role": "user", "content": c} for c in contents]


# ---------------------------------------------------------------------------
# Unit tests — CompressionCache internals
# ---------------------------------------------------------------------------


class TestCompressionCacheInternals:
    """Tests for CompressionCache get/put/hit_rate mechanics."""

    def test_initial_state_is_empty(self) -> None:
        """A new cache has zero hits, zero misses, and hit_rate of 0.0."""
        cache = CompressionCache()
        assert cache.hits == 0
        assert cache.misses == 0
        assert cache.hit_rate == 0.0

    def test_get_without_task_embedding_is_miss(self) -> None:
        """get_semantic() with no task_embedding always returns None (miss)."""
        cache = CompressionCache()
        result = cache.get_semantic("some content", [0.1, 0.2], None)
        assert result is None
        assert cache.misses == 1
        assert cache.hits == 0

    def test_get_without_segment_embedding_is_miss(self) -> None:
        """get_semantic() with no segment_embedding always returns None (miss)."""
        cache = CompressionCache()
        result = cache.get_semantic("some content", None, [0.1, 0.2])
        assert result is None
        assert cache.misses == 1

    def test_put_then_get_returns_same_score(self) -> None:
        """P-CACHE-2: a score stored via put_semantic() is returned on get_semantic()."""
        cache = CompressionCache()
        seg_emb = [1.0, 0.0]
        task_emb = [1.0, 0.0]
        expected_score = 0.75

        cache.put_semantic("hello world", seg_emb, task_emb, expected_score)
        result = cache.get_semantic("hello world", seg_emb, task_emb)

        assert result == pytest.approx(expected_score)
        assert cache.hits == 1
        assert cache.misses == 0

    def test_different_content_is_cache_miss(self) -> None:
        """Different segment content produces a different hash → miss."""
        cache = CompressionCache()
        seg_emb = [1.0, 0.0]
        task_emb = [1.0, 0.0]
        cache.put_semantic("content A", seg_emb, task_emb, 0.5)

        result = cache.get_semantic("content B", seg_emb, task_emb)
        assert result is None
        assert cache.misses == 1

    def test_hit_rate_computation(self) -> None:
        """P-CACHE-3: hit_rate == hits / (hits + misses)."""
        cache = CompressionCache()
        seg_emb = [1.0, 0.0]
        task_emb = [1.0, 0.0]

        # 1 put + 2 hits + 1 miss
        cache.put_semantic("x", seg_emb, task_emb, 0.8)
        cache.get_semantic("x", seg_emb, task_emb)   # hit
        cache.get_semantic("x", seg_emb, task_emb)   # hit
        cache.get_semantic("y", seg_emb, task_emb)   # miss

        assert cache.hits == 2
        assert cache.misses == 1
        assert cache.hit_rate == pytest.approx(2 / 3)

    def test_hit_rate_is_zero_with_no_lookups(self) -> None:
        """hit_rate returns 0.0 when no get() calls have been made."""
        cache = CompressionCache()
        assert cache.hit_rate == 0.0


# ---------------------------------------------------------------------------
# Integration tests — score_segments with cache
# ---------------------------------------------------------------------------


class TestScoreSegmentsWithCache:
    """Tests integrating CompressionCache into score_segments."""

    def test_no_cache_hits_when_no_task_hint(self) -> None:
        """P-CACHE-4: cache never hits when task_hint=None (semantic scoring off)."""
        segments = [_seg(i, f"turn {i} content", i) for i in range(5)]
        cache = CompressionCache()

        score_segments(segments, task_hint=None, cache=cache)

        assert cache.hits == 0

    def test_second_call_hits_cache_for_repeated_segments(self) -> None:
        """P-CACHE-2: a segment seen twice with the same task_hint hits the cache."""
        content = "the quick brown fox"
        segments = [_seg(0, content, 0)]
        cache = CompressionCache()
        task = "summarize documents"

        # First call — miss, score computed and stored
        scores_first = score_segments(segments, task_hint=task, cache=cache)
        assert cache.misses == 1
        assert cache.hits == 0

        # Second call with same segment and task — hit
        scores_second = score_segments(segments, task_hint=task, cache=cache)
        assert cache.hits == 1
        assert scores_first == pytest.approx(scores_second, abs=1e-6)

    def test_cached_and_uncached_scores_are_identical(self) -> None:
        """P-CACHE-1: cached run produces the same scores as uncached run."""
        segments = [_seg(i, f"segment content number {i}", i) for i in range(4)]
        task = "classify each item"

        # Uncached baseline
        scores_no_cache = score_segments(segments, task_hint=task, cache=None)

        # First cached run (all misses — populates cache)
        cache = CompressionCache()
        scores_cached_first = score_segments(segments, task_hint=task, cache=cache)

        # Second cached run (should hit for all non-protected segments)
        scores_cached_second = score_segments(segments, task_hint=task, cache=cache)

        assert scores_no_cache == pytest.approx(scores_cached_first, abs=1e-6)
        assert scores_no_cache == pytest.approx(scores_cached_second, abs=1e-6)

    def test_protected_segments_always_score_1_regardless_of_cache(self) -> None:
        """Protected segments score 1.0 and do not interact with the cache."""
        seg = _seg(0, "protected content", 0, protected=True)
        cache = CompressionCache()

        scores = score_segments([seg], task_hint="some task", cache=cache)

        assert scores == [1.0]
        assert cache.hits == 0
        assert cache.misses == 0


# ---------------------------------------------------------------------------
# Integration tests — compress() exposes cache fields
# ---------------------------------------------------------------------------


class TestCompressExposesCache:
    """Tests that compress() correctly populates cache_hits/cache_hit_rate."""

    def test_cache_fields_present_on_result(self) -> None:
        """P-CACHE-5: CompressionResult has cache_hits and cache_hit_rate fields."""
        msgs = _msgs("Hello, how are you?", "I need help with a task.")
        result = compress(msgs, _live_config(), task_hint="assist user")

        assert hasattr(result, "cache_hits")
        assert hasattr(result, "cache_hit_rate")
        assert result.cache_hits >= 0
        assert 0.0 <= result.cache_hit_rate <= 1.0

    def test_cache_hits_zero_when_no_task_hint(self) -> None:
        """P-CACHE-4: cache_hits is 0 in result when no task_hint is provided."""
        msgs = _msgs("First message.", "Second message.", "Third message.")
        result = compress(msgs, _live_config(), task_hint=None)

        assert result.cache_hits == 0
        assert result.cache_hit_rate == 0.0

    def test_summarized_marker_says_traject_not_axon(self) -> None:
        """Summarized segments carry the 'Traject' brand, not the old 'Axon' name."""
        # Build a long tool-result message that will be summarized under CONSERVATIVE
        long_tool_result = "Tool result: " + ("data point, " * 200)
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": "You are an assistant."},
            {"role": "user", "content": "Step 1"},
            {"role": "tool", "content": long_tool_result},   # turn 0 — old
            {"role": "user", "content": "Step 2"},
            {"role": "assistant", "content": "Processed."},
            {"role": "user", "content": "Step 3"},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Final question."},  # recent
        ]
        cfg = CompressionConfig(
            strategy=CompressionStrategy.CONSERVATIVE,
            target_reduction_pct=0.20,
            min_turns_protected=1,
            protect_system_prompt=True,
            shadow_mode=False,
        )
        result = compress(msgs, cfg, task_hint="process steps")

        all_content = " ".join(
            str(m.get("content", "")) for m in result.messages
        )
        assert "Axon" not in all_content
        # If summarization occurred, 'Traject' label must be present
        if result.segments_summarized > 0:
            assert "Traject" in all_content


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------


class TestCompressionCacheProperties:
    """Hypothesis property tests for CompressionCache."""

    @settings(max_examples=100, deadline=None)
    @given(
        contents=st.lists(
            st.text(min_size=1, max_size=50),
            min_size=1,
            max_size=10,
        ),
        task=st.text(min_size=1, max_size=30),
    )
    def test_cached_scores_equal_uncached_scores(
        self, contents: list[str], task: str
    ) -> None:
        """P-CACHE-1 (property): for any segments and task hint, cached == uncached."""
        segments = [
            _seg(i, content, i)
            for i, content in enumerate(contents)
        ]

        scores_no_cache = score_segments(segments, task_hint=task, cache=None)

        cache = CompressionCache()
        scores_with_cache = score_segments(segments, task_hint=task, cache=cache)

        assert len(scores_no_cache) == len(scores_with_cache)
        for i, (s1, s2) in enumerate(zip(scores_no_cache, scores_with_cache, strict=False)):
            assert abs(s1 - s2) < 1e-5, (
                f"Score mismatch at index {i}: no_cache={s1}, cached={s2}, "
                f"content={contents[i]!r}"
            )

    @settings(max_examples=50)
    @given(score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    def test_hit_rate_invariant(self, score: float) -> None:
        """P-CACHE-3 (property): hit_rate == hits / (hits + misses) always."""
        cache = CompressionCache()
        seg_emb = [1.0, 0.0]
        task_emb = [1.0, 0.0]

        cache.put_semantic("content", seg_emb, task_emb, score)
        cache.get_semantic("content", seg_emb, task_emb)   # hit
        cache.get_semantic("other", seg_emb, task_emb)     # miss

        expected = cache.hits / (cache.hits + cache.misses)
        assert cache.hit_rate == pytest.approx(expected, abs=1e-9)
