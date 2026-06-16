"""Entry-point-based plugin loader for the Traject plugin system.

Discovers and loads third-party plugins published under the ``"traject.plugins"``
entry-point group using :mod:`importlib.metadata`.  Each entry point is
expected to point to a class that is a concrete subclass of one of the three
plugin ABCs defined in :mod:`traject.plugins.base`.

Typical usage::

    from traject.plugins import PluginLoader, PluginRegistry

    registry = PluginRegistry.get_instance()
    loader = PluginLoader()
    loaded_count = loader.load_all(registry)
"""

from __future__ import annotations

import importlib.metadata

import structlog

from traject.plugins.registry import PluginRegistry

_log = structlog.get_logger(__name__)


class PluginLoader:
    """Discovers and loads Traject plugins from Python entry points.

    Reads all entry points published under the ``"traject.plugins"`` group via
    :func:`importlib.metadata.entry_points`, instantiates each advertised
    class, and registers it with the provided :class:`PluginRegistry`.

    Third-party packages register their plugins by adding an entry to their
    ``pyproject.toml``::

        [project.entry-points."traject.plugins"]
        my_compressor = "my_package.plugins:MyCompressionPlugin"

    Each key is an arbitrary label; the value follows the ``module:ClassName``
    format recognised by :mod:`importlib.metadata`.

    Attributes:
        None.  This class is stateless; all state is held by the registry
        passed to :meth:`load_all`.
    """

    def load_all(self, registry: PluginRegistry) -> int:
        """Discover and load all plugins into *registry*.

        Iterates :func:`importlib.metadata.entry_points` for the
        ``"traject.plugins"`` group, loads each entry point class, instantiates
        it with no arguments, and calls :meth:`PluginRegistry.register` with
        the resulting instance.

        Each plugin is treated independently: if loading or registering one
        plugin raises :exc:`Exception`, an error is logged via structlog and
        the loader continues to the next entry point.  Failures are
        non-fatal.

        Args:
            registry: The :class:`PluginRegistry` instance into which
                successfully instantiated plugins will be registered.

        Returns:
            The number of plugins that were successfully loaded and
            registered.
        """
        success_count: int = 0

        entry_points = importlib.metadata.entry_points(group="traject.plugins")

        for ep in entry_points:
            try:
                plugin_class = ep.load()
                instance = plugin_class()
                registry.register(instance)
                _log.info(
                    "traject.plugins.loaded",
                    entry_point=ep.name,
                    plugin_class=type(instance).__name__,
                )
                success_count += 1
            except Exception as exc:
                _log.error(
                    "traject.plugins.load_failed",
                    entry_point=ep.name,
                    error=str(exc),
                    exc_info=exc,
                )

        return success_count
