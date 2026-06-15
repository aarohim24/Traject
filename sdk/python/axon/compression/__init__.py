"""Trajectory compression engine for the Axon SDK.

Provides the main ``compress`` function for reducing LLM context window
size before provider calls, plus the ``CompressionStrategy`` enum for
selecting compression aggressiveness.
"""
from axon.compression.engine import compress
from axon.compression.strategies import CompressionStrategy

__all__ = ["CompressionStrategy", "compress"]
