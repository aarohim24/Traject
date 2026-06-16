"""Trajectory compression engine for the Axon SDK.

Provides the main ``compress`` function for reducing LLM context window
size before provider calls, plus the ``CompressionStrategy`` enum for
selecting compression aggressiveness.
"""

__all__ = ["CompressionStrategy", "compress"]


def __getattr__(name: str) -> object:
    """Lazy-load compression symbols to avoid circular imports."""
    if name == "compress":
        from axon.compression.engine import compress  # noqa: PLC0415
        return compress
    if name == "CompressionStrategy":
        from axon.compression.strategies import CompressionStrategy  # noqa: PLC0415
        return CompressionStrategy
    raise AttributeError(f"module 'axon.compression' has no attribute {name!r}")
