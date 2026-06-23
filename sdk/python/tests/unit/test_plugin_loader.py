"""Unit tests for traject.plugins.loader.PluginLoader.

Validates: Requirements 5.4, 5.5

Tests cover:
- load_all() skips failing plugins and continues (non-fatal error handling)
- load_all() returns the correct success count
- load_all() integrates correctly with mock entry_points

All tests mock ``importlib.metadata.entry_points`` so no real entry points
are required on the test environment.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from traject.classifier.artifact_type import ArtifactType
from traject.plugins.base import (
    ArtifactClassifierPlugin,
    CompressionPlugin,
    RoutingPlugin,
)
from traject.plugins.loader import PluginLoader
from traject.plugins.registry import PluginRegistry
from traject.router.routing_table import RoutingDecision

# ---------------------------------------------------------------------------
# Minimal concrete plugin implementations (mirrored from test_plugin_registry)
# ---------------------------------------------------------------------------


class MinimalCompressionPlugin(CompressionPlugin):
    """Minimal CompressionPlugin implementation for testing."""

    def compress(
        self, segments: list[str], **kwargs: Any
    ) -> list[str]:  # Any: provider-specific kwargs
        """Return segments unchanged."""
        return segments


class MinimalRoutingPlugin(RoutingPlugin):
    """Minimal RoutingPlugin implementation for testing."""

    def route(
        self,
        messages: list[dict[str, Any]],  # Any: message value types vary
        requested_model: str,
        **kwargs: Any,  # Any: provider-specific kwargs
    ) -> RoutingDecision | None:
        """Always defer to default router."""
        return None


class MinimalArtifactClassifierPlugin(ArtifactClassifierPlugin):
    """Minimal ArtifactClassifierPlugin implementation for testing."""

    def classify(
        self, content: str, **kwargs: Any
    ) -> ArtifactType | None:  # Any: provider-specific kwargs
        """Always defer to default classifier."""
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry_point(name: str, plugin_class: type) -> MagicMock:
    """Return a mock entry point whose .load() returns *plugin_class*.

    Args:
        name: The entry point name attribute.
        plugin_class: The class to be returned by ep.load().

    Returns:
        A MagicMock that behaves like an importlib.metadata.EntryPoint.
    """
    ep: MagicMock = MagicMock()
    ep.name = name
    ep.load.return_value = plugin_class
    return ep


def _make_failing_entry_point(name: str, exc: Exception | None = None) -> MagicMock:
    """Return a mock entry point whose .load() raises *exc*.

    Args:
        name: The entry point name attribute.
        exc: Exception to raise (defaults to ``RuntimeError``).

    Returns:
        A MagicMock that raises an exception on .load().
    """
    ep: MagicMock = MagicMock()
    ep.name = name
    ep.load.side_effect = exc or RuntimeError("simulated load failure")
    return ep


# ---------------------------------------------------------------------------
# Fixture — ensure registry isolation between every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    """Clear the singleton PluginRegistry before each test for isolation.

    **Validates: Requirements 5.4, 5.5**
    """
    registry = PluginRegistry.get_instance()
    registry.clear()


# ---------------------------------------------------------------------------
# Tests: load_all() returns correct success count
# ---------------------------------------------------------------------------


class TestLoadAllSuccessCount:
    """load_all() returns the number of plugins that were successfully loaded.

    **Validates: Requirements 5.4, 5.5**
    """

    def test_returns_zero_when_no_entry_points(self) -> None:
        """load_all() returns 0 when there are no registered entry points.

        **Validates: Requirements 5.4**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=[]
        ):
            count = loader.load_all(registry)

        assert count == 0

    def test_returns_one_for_single_successful_plugin(self) -> None:
        """load_all() returns 1 when a single plugin loads successfully.

        **Validates: Requirements 5.4**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        ep = _make_entry_point("my_compression", MinimalCompressionPlugin)

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=[ep]
        ):
            count = loader.load_all(registry)

        assert count == 1

    def test_returns_correct_count_for_multiple_successful_plugins(self) -> None:
        """load_all() returns the total count of all successful plugin loads.

        **Validates: Requirements 5.4**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        eps = [
            _make_entry_point("comp", MinimalCompressionPlugin),
            _make_entry_point("router", MinimalRoutingPlugin),
            _make_entry_point("classifier", MinimalArtifactClassifierPlugin),
        ]

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=eps
        ):
            count = loader.load_all(registry)

        assert count == 3

    def test_returns_zero_when_all_entry_points_fail(self) -> None:
        """load_all() returns 0 when every entry point raises during load.

        **Validates: Requirements 5.5**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        eps = [
            _make_failing_entry_point("bad_one"),
            _make_failing_entry_point("bad_two"),
        ]

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=eps
        ):
            count = loader.load_all(registry)

        assert count == 0


# ---------------------------------------------------------------------------
# Tests: load_all() skips failing plugins and continues
# ---------------------------------------------------------------------------


class TestLoadAllSkipsFailingPlugins:
    """load_all() treats each plugin independently; failures are non-fatal.

    **Validates: Requirements 5.5**
    """

    def test_skips_failing_plugin_and_loads_remaining(self) -> None:
        """load_all() skips a failing plugin and continues loading the rest.

        **Validates: Requirements 5.5**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        eps = [
            _make_failing_entry_point("bad_plugin"),
            _make_entry_point("good_plugin", MinimalCompressionPlugin),
        ]

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=eps
        ):
            count = loader.load_all(registry)

        # Only the good plugin counted
        assert count == 1
        assert len(registry.get_compression_plugins()) == 1

    def test_success_count_excludes_failures(self) -> None:
        """load_all() success count does not include plugins that raised.

        **Validates: Requirements 5.4, 5.5**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        eps = [
            _make_entry_point("good_1", MinimalCompressionPlugin),
            _make_failing_entry_point("bad_1"),
            _make_entry_point("good_2", MinimalRoutingPlugin),
            _make_failing_entry_point("bad_2"),
        ]

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=eps
        ):
            count = loader.load_all(registry)

        assert count == 2

    def test_failure_does_not_affect_previously_loaded_plugins(self) -> None:
        """A later-failing plugin does not remove previously registered plugins.

        **Validates: Requirements 5.5**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        eps = [
            _make_entry_point("good_first", MinimalCompressionPlugin),
            _make_failing_entry_point("bad_second"),
        ]

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=eps
        ):
            loader.load_all(registry)

        # The first plugin must still be registered
        assert len(registry.get_compression_plugins()) == 1

    @pytest.mark.parametrize(
        "exc",
        [
            RuntimeError("load failed"),
            ImportError("missing dep"),
            TypeError("bad type"),
            ValueError("bad value"),
        ],
        ids=["RuntimeError", "ImportError", "TypeError", "ValueError"],
    )
    def test_skips_plugin_for_various_exception_types(self, exc: Exception) -> None:
        """load_all() skips a plugin that raises any Exception subclass.

        **Validates: Requirements 5.5**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        eps = [
            _make_failing_entry_point("bad", exc),
            _make_entry_point("good", MinimalCompressionPlugin),
        ]

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=eps
        ):
            count = loader.load_all(registry)

        assert count == 1

    def test_failing_instantiation_is_also_skipped(self) -> None:
        """load_all() skips a plugin whose class instantiation raises.

        The .load() step succeeds (returns the class) but constructing the
        instance raises.

        **Validates: Requirements 5.5**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()

        class _BrokenInit(MinimalCompressionPlugin):
            """CompressionPlugin that raises on __init__."""

            def __init__(self) -> None:
                """Always raise."""
                raise RuntimeError("cannot instantiate")

        ep: MagicMock = MagicMock()
        ep.name = "broken_init"
        ep.load.return_value = _BrokenInit

        good_ep = _make_entry_point("good", MinimalCompressionPlugin)

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points",
            return_value=[ep, good_ep],
        ):
            count = loader.load_all(registry)

        assert count == 1
        assert len(registry.get_compression_plugins()) == 1


# ---------------------------------------------------------------------------
# Tests: load_all() integrates correctly with mock entry_points
# ---------------------------------------------------------------------------


class TestLoadAllEntryPointIntegration:
    """load_all() correctly plumbs entry point output into PluginRegistry.

    **Validates: Requirements 5.4, 5.5**
    """

    def test_loaded_plugin_appears_in_registry(self) -> None:
        """After load_all(), the plugin is present in the registry.

        **Validates: Requirements 5.4**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        ep = _make_entry_point("my_comp", MinimalCompressionPlugin)

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=[ep]
        ):
            loader.load_all(registry)

        plugins = registry.get_compression_plugins()
        assert len(plugins) == 1
        assert isinstance(plugins[0], MinimalCompressionPlugin)

    def test_routing_plugin_loaded_into_correct_registry_list(self) -> None:
        """A RoutingPlugin entry point ends up in get_routing_plugins().

        **Validates: Requirements 5.4**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        ep = _make_entry_point("my_router", MinimalRoutingPlugin)

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=[ep]
        ):
            loader.load_all(registry)

        assert len(registry.get_routing_plugins()) == 1
        assert len(registry.get_compression_plugins()) == 0
        assert len(registry.get_classifier_plugins()) == 0

    def test_classifier_plugin_loaded_into_correct_registry_list(self) -> None:
        """An ArtifactClassifierPlugin entry point ends up in get_classifier_plugins().

        **Validates: Requirements 5.4**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        ep = _make_entry_point("my_classifier", MinimalArtifactClassifierPlugin)

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=[ep]
        ):
            loader.load_all(registry)

        assert len(registry.get_classifier_plugins()) == 1
        assert len(registry.get_compression_plugins()) == 0
        assert len(registry.get_routing_plugins()) == 0

    def test_entry_points_queried_with_correct_group(self) -> None:
        """load_all() calls entry_points with group='traject.plugins'.

        **Validates: Requirements 5.4**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=[]
        ) as mock_eps:
            loader.load_all(registry)

        mock_eps.assert_called_once_with(group="traject.plugins")

    def test_mixed_plugins_all_land_in_correct_typed_lists(self) -> None:
        """Multiple plugin types loaded together each appear in the right list.

        **Validates: Requirements 5.4**
        """
        registry = PluginRegistry.get_instance()
        loader = PluginLoader()
        eps = [
            _make_entry_point("comp", MinimalCompressionPlugin),
            _make_entry_point("router", MinimalRoutingPlugin),
            _make_entry_point("classifier", MinimalArtifactClassifierPlugin),
        ]

        with patch(
            "traject.plugins.loader.importlib.metadata.entry_points", return_value=eps
        ):
            count = loader.load_all(registry)

        assert count == 3
        assert len(registry.get_compression_plugins()) == 1
        assert len(registry.get_routing_plugins()) == 1
        assert len(registry.get_classifier_plugins()) == 1
