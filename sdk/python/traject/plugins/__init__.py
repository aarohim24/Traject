"""Axon plugin system — public API surface.

Re-exports the three plugin ABCs, the :class:`PluginRegistry` singleton, and
:class:`PluginLoader` so that all plugin-related symbols are importable from
the single ``axon.plugins`` namespace.

:class:`PluginLoader` is defined in ``axon.plugins.loader`` (implemented in
task 16).  It is exposed here via a lazy ``__getattr__`` guard so that this
package is importable before ``loader.py`` exists and without requiring its
runtime dependency on ``importlib.metadata`` to be evaluated eagerly.
"""

from __future__ import annotations

from typing import Any

from traject.plugins.base import (
    ArtifactClassifierPlugin,
    CompressionPlugin,
    RoutingPlugin,
)
from traject.plugins.registry import PluginRegistry

__all__ = [
    "ArtifactClassifierPlugin",
    "CompressionPlugin",
    "PluginLoader",
    "PluginRegistry",
    "RoutingPlugin",
]


def __getattr__(name: str) -> Any:  # Any: dynamic module attribute
    """Lazily import :class:`PluginLoader` to avoid a hard dependency on loader.py.

    Supports ``from traject.plugins import PluginLoader`` without requiring
    ``loader.py`` to exist at import time (it is created in task 16).

    Args:
        name: Attribute name being looked up on this module.

    Returns:
        The requested class.

    Raises:
        AttributeError: If ``name`` is not a known lazy-importable attribute.
    """
    if name == "PluginLoader":
        from traject.plugins.loader import PluginLoader

        return PluginLoader
    raise AttributeError(f"module 'axon.plugins' has no attribute {name!r}")
