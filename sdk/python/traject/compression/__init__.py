"""Trajectory compression engine for the Traject SDK.

Provides the main ``compress`` function for reducing LLM context window
size before provider calls, plus the ``CompressionStrategy`` enum for
selecting compression aggressiveness.
"""

__all__ = ["CompressionStrategy", "compress"]


def __getattr__(name: str) -> object:
    """Lazy-load compression symbols to avoid circular imports."""
    if name == "compress":
        from traject.compression.engine import compress

        return compress
    if name == "CompressionStrategy":
        from traject.compression.strategies import CompressionStrategy

        return CompressionStrategy
    raise AttributeError(f"module 'traject.compression' has no attribute {name!r}")
