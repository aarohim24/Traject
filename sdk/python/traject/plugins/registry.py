"""In-process singleton registry for Traject plugins.

Maintains three separate ordered lists — one for each recognized plugin ABC
(:class:`~traject.plugins.base.CompressionPlugin`,
:class:`~traject.plugins.base.RoutingPlugin`,
:class:`~traject.plugins.base.ArtifactClassifierPlugin`) — and exposes a
thread-safe API for registering plugins and retrieving them by type.

The registry follows the singleton pattern: exactly one
:class:`PluginRegistry` instance exists per interpreter process and is
accessed via :meth:`PluginRegistry.get_instance`.  Calling ``clear()`` is
intended for test isolation only.
"""

from __future__ import annotations

import threading

import structlog

from traject.plugins.base import (
    ArtifactClassifierPlugin,
    CompressionPlugin,
    RoutingPlugin,
)

_log = structlog.get_logger(__name__)

# Module-level lock used by PluginRegistry for thread-safe mutations.
_registry_lock: threading.Lock = threading.Lock()

# Union alias for all recognised plugin base types.
_AnyPlugin = CompressionPlugin | RoutingPlugin | ArtifactClassifierPlugin


class PluginRegistry:
    """In-process registry for all registered Traject plugins.

    Maintains three separate ordered lists (one per plugin type).
    Thread-safe via a module-level lock (not needed in most single-threaded
    async contexts but included for correctness under threaded test runners).

    Access the singleton via :meth:`get_instance` rather than constructing
    instances directly.

    Raises:
        TypeError: When :meth:`register` receives an argument that is not an
            instance of :class:`~traject.plugins.base.CompressionPlugin`,
            :class:`~traject.plugins.base.RoutingPlugin`, or
            :class:`~traject.plugins.base.ArtifactClassifierPlugin`.
    """

    _instance: PluginRegistry | None = None

    def __init__(self) -> None:
        self._compression_plugins: list[CompressionPlugin] = []
        self._routing_plugins: list[RoutingPlugin] = []
        self._classifier_plugins: list[ArtifactClassifierPlugin] = []

    @classmethod
    def get_instance(cls) -> PluginRegistry:
        """Return the process-wide singleton :class:`PluginRegistry`.

        Creates the instance on first call.  Subsequent calls always return
        the same object.

        Returns:
            The singleton :class:`PluginRegistry` instance.
        """
        with _registry_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def register(
        self,
        plugin: _AnyPlugin,
    ) -> None:
        """Register a plugin with the appropriate typed list.

        The plugin is appended to the end of the list for its type, so
        registration order is preserved.

        Args:
            plugin: A concrete instance of
                :class:`~traject.plugins.base.CompressionPlugin`,
                :class:`~traject.plugins.base.RoutingPlugin`, or
                :class:`~traject.plugins.base.ArtifactClassifierPlugin`.

        Raises:
            TypeError: If ``plugin`` is not an instance of one of the three
                recognised plugin ABCs.
        """
        with _registry_lock:
            if isinstance(plugin, CompressionPlugin):
                self._compression_plugins.append(plugin)
                _log.info(
                    "traject.plugins.registered",
                    plugin_type="CompressionPlugin",
                    plugin_class=type(plugin).__name__,
                )
            elif isinstance(plugin, RoutingPlugin):
                self._routing_plugins.append(plugin)
                _log.info(
                    "traject.plugins.registered",
                    plugin_type="RoutingPlugin",
                    plugin_class=type(plugin).__name__,
                )
            elif isinstance(plugin, ArtifactClassifierPlugin):
                self._classifier_plugins.append(plugin)
                _log.info(
                    "traject.plugins.registered",
                    plugin_type="ArtifactClassifierPlugin",
                    plugin_class=type(plugin).__name__,
                )
            else:
                raise TypeError(
                    f"Expected an instance of CompressionPlugin, RoutingPlugin, or "
                    f"ArtifactClassifierPlugin, got {type(plugin).__name__!r}.  "
                    "Ensure your plugin class inherits from one of the ABCs in "
                    "traject.plugins.base."
                )

    def get_compression_plugins(self) -> list[CompressionPlugin]:
        """Return a snapshot of all registered compression plugins.

        Returns:
            Ordered list of registered
            :class:`~traject.plugins.base.CompressionPlugin` instances.
        """
        with _registry_lock:
            return list(self._compression_plugins)

    def get_routing_plugins(self) -> list[RoutingPlugin]:
        """Return a snapshot of all registered routing plugins.

        Returns:
            Ordered list of registered
            :class:`~traject.plugins.base.RoutingPlugin` instances.
        """
        with _registry_lock:
            return list(self._routing_plugins)

    def get_classifier_plugins(self) -> list[ArtifactClassifierPlugin]:
        """Return a snapshot of all registered artifact classifier plugins.

        Returns:
            Ordered list of registered
            :class:`~traject.plugins.base.ArtifactClassifierPlugin` instances.
        """
        with _registry_lock:
            return list(self._classifier_plugins)

    def clear(self) -> None:
        """Remove all registered plugins from all typed lists.

        Intended for test isolation only.  Do not call this in production
        code.
        """
        with _registry_lock:
            self._compression_plugins.clear()
            self._routing_plugins.clear()
            self._classifier_plugins.clear()
