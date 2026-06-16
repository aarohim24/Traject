"""Core instrumentation and configuration for the Axon SDK.

Exposes ``configure``, ``patch``, and ``instrument`` — the three main entry
points for integrating Axon into an existing application.
"""

__all__ = ["configure", "instrument", "patch"]


def __getattr__(name: str) -> object:
    """Lazy-load core symbols to avoid circular imports."""
    if name in ("configure", "instrument", "patch"):
        from traject.core.instrumentor import configure, instrument, patch  # noqa: PLC0415
        return {"configure": configure, "instrument": instrument, "patch": patch}[name]
    raise AttributeError(f"module 'axon.core' has no attribute {name!r}")
