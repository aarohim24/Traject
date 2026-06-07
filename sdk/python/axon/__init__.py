"""Axon SDK — LLM observability, cost attribution, and trajectory compression.

Provides a single decorator and patch function for instrumenting OpenAI and
Anthropic clients with zero changes to existing call sites. Emits structured
OpenTelemetry spans with exact token counts, USD cost, and compression
analysis (shadow mode by default).
"""
from __future__ import annotations

from axon.compression.strategies import CompressionStrategy
from axon.core.instrumentor import configure, instrument, patch
from axon.exceptions import (
    AxonCompressionError,
    AxonConfigError,
    AxonDependencyError,
    AxonError,
    AxonProviderError,
)

__version__ = "0.1.0"

__all__ = [
    "AxonCompressionError",
    "AxonConfigError",
    "AxonDependencyError",
    "AxonError",
    "AxonProviderError",
    "CompressionStrategy",
    "__version__",
    "configure",
    "instrument",
    "patch",
]
