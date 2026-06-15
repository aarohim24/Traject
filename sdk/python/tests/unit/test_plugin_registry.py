"""Unit tests for axon.plugins.registry.PluginRegistry.

Validates: Requirements 5.2, 5.3

Tests cover:
- TypeError raised for non-plugin arguments (Property 6 from design §6.2)
- Successful registration of all three plugin types
- clear() empties all three registries
- Typed getter methods return empty lists before registration and populated
  lists after registration
"""
from __future__ import annotations

from typing import Any

import pytest

from axon.classifier.artifact_type import ArtifactType
from axon.plugins.base import (
    ArtifactClassifierPlugin,
    CompressionPlugin,
    RoutingPlugin,
)
from axon.plugins.registry import PluginRegistry
from axon.router.routing_table import RoutingDecision

# ---------------------------------------------------------------------------
# Minimal concrete implementations of each ABC
# ---------------------------------------------------------------------------


class MinimalCompressionPlugin(CompressionPlugin):
    """Minimal CompressionPlugin implementation for testing."""

    def compress(self, segments: list[str], **kwargs: Any) -> list[str]:  # Any: provider-specific kwargs
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

    def classify(self, content: str, **kwargs: Any) -> ArtifactType | None:  # Any: provider-specific kwargs
        """Always defer to default classifier."""
        return None


# ---------------------------------------------------------------------------
# Fixture — ensure registry is cleared between every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    """Clear the singleton PluginRegistry before each test for isolation."""
    registry = PluginRegistry.get_instance()
    registry.clear()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _registry() -> PluginRegistry:
    """Return the singleton PluginRegistry."""
    return PluginRegistry.get_instance()


# ---------------------------------------------------------------------------
# TypeError for non-plugin arguments (design §6.2, Property 6)
# ---------------------------------------------------------------------------


class TestRegisterTypeError:
    """register() must raise TypeError for any non-plugin argument.

    **Validates: Requirements 5.2**
    """

    def test_register_raises_type_error_for_plain_object(self) -> None:
        """register() raises TypeError when passed a plain object.

        **Validates: Requirements 5.2**
        """
        with pytest.raises(TypeError):
            _registry().register(object())  # type: ignore[arg-type]

    def test_register_raises_type_error_for_string(self) -> None:
        """register() raises TypeError when passed a string.

        **Validates: Requirements 5.2**
        """
        with pytest.raises(TypeError):
            _registry().register("not a plugin")  # type: ignore[arg-type]

    def test_register_raises_type_error_for_integer(self) -> None:
        """register() raises TypeError when passed an integer.

        **Validates: Requirements 5.2**
        """
        with pytest.raises(TypeError):
            _registry().register(42)  # type: ignore[arg-type]

    def test_register_raises_type_error_for_none(self) -> None:
        """register() raises TypeError when passed None.

        **Validates: Requirements 5.2**
        """
        with pytest.raises(TypeError):
            _registry().register(None)  # type: ignore[arg-type]

    def test_register_raises_type_error_for_dict(self) -> None:
        """register() raises TypeError when passed a dict.

        **Validates: Requirements 5.2**
        """
        with pytest.raises(TypeError):
            _registry().register({"compress": lambda x: x})  # type: ignore[arg-type]

    def test_register_type_error_message_is_descriptive(self) -> None:
        """TypeError message mentions the unexpected type.

        **Validates: Requirements 5.2**
        """
        with pytest.raises(TypeError, match=r"CompressionPlugin|RoutingPlugin|ArtifactClassifierPlugin"):
            _registry().register("unexpected")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Successful registration of valid plugin instances
# ---------------------------------------------------------------------------


class TestRegisterValidPlugins:
    """register() succeeds for concrete instances of each plugin ABC.

    **Validates: Requirements 5.2, 5.3**
    """

    def test_register_compression_plugin_succeeds(self) -> None:
        """register() accepts a CompressionPlugin without raising.

        **Validates: Requirements 5.2**
        """
        plugin = MinimalCompressionPlugin()
        _registry().register(plugin)  # must not raise

    def test_register_routing_plugin_succeeds(self) -> None:
        """register() accepts a RoutingPlugin without raising.

        **Validates: Requirements 5.2**
        """
        plugin = MinimalRoutingPlugin()
        _registry().register(plugin)  # must not raise

    def test_register_artifact_classifier_plugin_succeeds(self) -> None:
        """register() accepts an ArtifactClassifierPlugin without raising.

        **Validates: Requirements 5.2**
        """
        plugin = MinimalArtifactClassifierPlugin()
        _registry().register(plugin)  # must not raise


# ---------------------------------------------------------------------------
# Typed getter methods — empty before registration
# ---------------------------------------------------------------------------


class TestGettersBeforeRegistration:
    """All three typed getters return empty lists on a freshly cleared registry.

    **Validates: Requirements 5.3**
    """

    def test_get_compression_plugins_empty_before_registration(self) -> None:
        """get_compression_plugins() returns [] before any plugin is registered.

        **Validates: Requirements 5.3**
        """
        assert _registry().get_compression_plugins() == []

    def test_get_routing_plugins_empty_before_registration(self) -> None:
        """get_routing_plugins() returns [] before any plugin is registered.

        **Validates: Requirements 5.3**
        """
        assert _registry().get_routing_plugins() == []

    def test_get_classifier_plugins_empty_before_registration(self) -> None:
        """get_classifier_plugins() returns [] before any plugin is registered.

        **Validates: Requirements 5.3**
        """
        assert _registry().get_classifier_plugins() == []


# ---------------------------------------------------------------------------
# Typed getter methods — populated after registration
# ---------------------------------------------------------------------------


class TestGettersAfterRegistration:
    """Typed getters return only plugins of the matching type.

    **Validates: Requirements 5.3**
    """

    def test_get_compression_plugins_returns_registered_instance(self) -> None:
        """get_compression_plugins() includes the registered CompressionPlugin.

        **Validates: Requirements 5.3**
        """
        plugin = MinimalCompressionPlugin()
        _registry().register(plugin)

        result = _registry().get_compression_plugins()
        assert len(result) == 1
        assert result[0] is plugin

    def test_get_routing_plugins_returns_registered_instance(self) -> None:
        """get_routing_plugins() includes the registered RoutingPlugin.

        **Validates: Requirements 5.3**
        """
        plugin = MinimalRoutingPlugin()
        _registry().register(plugin)

        result = _registry().get_routing_plugins()
        assert len(result) == 1
        assert result[0] is plugin

    def test_get_classifier_plugins_returns_registered_instance(self) -> None:
        """get_classifier_plugins() includes the registered ArtifactClassifierPlugin.

        **Validates: Requirements 5.3**
        """
        plugin = MinimalArtifactClassifierPlugin()
        _registry().register(plugin)

        result = _registry().get_classifier_plugins()
        assert len(result) == 1
        assert result[0] is plugin

    def test_compression_plugin_does_not_appear_in_routing_or_classifier_lists(self) -> None:
        """Registering a CompressionPlugin does not pollute the other lists.

        **Validates: Requirements 5.3**
        """
        _registry().register(MinimalCompressionPlugin())

        assert _registry().get_routing_plugins() == []
        assert _registry().get_classifier_plugins() == []

    def test_routing_plugin_does_not_appear_in_compression_or_classifier_lists(self) -> None:
        """Registering a RoutingPlugin does not pollute the other lists.

        **Validates: Requirements 5.3**
        """
        _registry().register(MinimalRoutingPlugin())

        assert _registry().get_compression_plugins() == []
        assert _registry().get_classifier_plugins() == []

    def test_classifier_plugin_does_not_appear_in_compression_or_routing_lists(self) -> None:
        """Registering an ArtifactClassifierPlugin does not pollute the other lists.

        **Validates: Requirements 5.3**
        """
        _registry().register(MinimalArtifactClassifierPlugin())

        assert _registry().get_compression_plugins() == []
        assert _registry().get_routing_plugins() == []

    def test_registration_order_is_preserved(self) -> None:
        """Plugins are returned in registration order.

        **Validates: Requirements 5.3**
        """
        p1 = MinimalCompressionPlugin()
        p2 = MinimalCompressionPlugin()
        _registry().register(p1)
        _registry().register(p2)

        result = _registry().get_compression_plugins()
        assert result == [p1, p2]

    def test_multiple_plugin_types_registered_independently(self) -> None:
        """All three types can be registered simultaneously without interference.

        **Validates: Requirements 5.3**
        """
        compression = MinimalCompressionPlugin()
        routing = MinimalRoutingPlugin()
        classifier = MinimalArtifactClassifierPlugin()

        _registry().register(compression)
        _registry().register(routing)
        _registry().register(classifier)

        assert _registry().get_compression_plugins() == [compression]
        assert _registry().get_routing_plugins() == [routing]
        assert _registry().get_classifier_plugins() == [classifier]


# ---------------------------------------------------------------------------
# clear() empties all three registries
# ---------------------------------------------------------------------------


class TestClear:
    """clear() must empty all three typed lists.

    **Validates: Requirements 5.3**
    """

    def test_clear_empties_compression_plugins(self) -> None:
        """clear() makes get_compression_plugins() return [].

        **Validates: Requirements 5.3**
        """
        _registry().register(MinimalCompressionPlugin())
        _registry().clear()
        assert _registry().get_compression_plugins() == []

    def test_clear_empties_routing_plugins(self) -> None:
        """clear() makes get_routing_plugins() return [].

        **Validates: Requirements 5.3**
        """
        _registry().register(MinimalRoutingPlugin())
        _registry().clear()
        assert _registry().get_routing_plugins() == []

    def test_clear_empties_classifier_plugins(self) -> None:
        """clear() makes get_classifier_plugins() return [].

        **Validates: Requirements 5.3**
        """
        _registry().register(MinimalArtifactClassifierPlugin())
        _registry().clear()
        assert _registry().get_classifier_plugins() == []

    def test_clear_empties_all_three_lists_simultaneously(self) -> None:
        """clear() empties all three lists in a single call.

        **Validates: Requirements 5.3**
        """
        _registry().register(MinimalCompressionPlugin())
        _registry().register(MinimalRoutingPlugin())
        _registry().register(MinimalArtifactClassifierPlugin())

        _registry().clear()

        assert _registry().get_compression_plugins() == []
        assert _registry().get_routing_plugins() == []
        assert _registry().get_classifier_plugins() == []

    def test_clear_on_empty_registry_does_not_raise(self) -> None:
        """Calling clear() on an already-empty registry does not raise.

        **Validates: Requirements 5.3**
        """
        _registry().clear()  # already empty from fixture
        _registry().clear()  # second call must also be safe

    def test_can_register_after_clear(self) -> None:
        """Plugins can be registered again after clear() is called.

        **Validates: Requirements 5.3**
        """
        p1 = MinimalCompressionPlugin()
        _registry().register(p1)
        _registry().clear()

        p2 = MinimalCompressionPlugin()
        _registry().register(p2)

        result = _registry().get_compression_plugins()
        assert result == [p2]
