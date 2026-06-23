"""Traject SDK — LLM observability, cost attribution, and trajectory compression.

Provides a single decorator and patch function for instrumenting OpenAI and
Anthropic clients with zero changes to existing call sites. Emits structured
OpenTelemetry spans with exact token counts, USD cost, and compression
analysis (shadow mode by default).
"""

from __future__ import annotations

import os

# Suppress HuggingFace unauthenticated-request warnings and tokenizer
# parallelism warnings that appear on first import — neither is relevant
# to Traject's in-process embedding model (ADR-003).
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from traject.compression.strategies import CompressionStrategy
from traject.core.instrumentor import configure, instrument, patch
from traject.exceptions import (
    InsufficientDataError,
    TrajectCompressionError,
    TrajectConfigError,
    TrajectDependencyError,
    TrajectError,
    TrajectProviderError,
)

__version__ = "0.1.0"

__all__ = [
    "CompressionStrategy",
    "InsufficientDataError",
    "TrajectCompressionError",
    "TrajectConfigError",
    "TrajectDependencyError",
    "TrajectError",
    "TrajectProviderError",
    "__version__",
    "configure",
    "instrument",
    "patch",
]
