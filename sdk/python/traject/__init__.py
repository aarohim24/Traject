"""Traject SDK — LLM observability, cost attribution, and trajectory compression.

Provides a single decorator and patch function for instrumenting OpenAI and
Anthropic clients with zero changes to existing call sites. Emits structured
OpenTelemetry spans with exact token counts, USD cost, and compression
analysis (shadow mode by default).
"""
from __future__ import annotations

from traject.compression.strategies import CompressionStrategy
from traject.core.instrumentor import configure, instrument, patch
from traject.exceptions import (
    TrajectCompressionError,
    TrajectConfigError,
    TrajectDependencyError,
    TrajectError,
    TrajectProviderError,
    InsufficientDataError,
)

__version__ = "0.1.0"

__all__ = [
    "TrajectCompressionError",
    "TrajectConfigError",
    "TrajectDependencyError",
    "TrajectError",
    "TrajectProviderError",
    "CompressionStrategy",
    "InsufficientDataError",
    "__version__",
    "configure",
    "instrument",
    "patch",
]
