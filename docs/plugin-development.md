# Plugin Development Guide

Axon's plugin system lets you extend compression, routing, and artifact
classification behavior without modifying the core SDK.  Plugins are discovered
at runtime via Python entry points and are composed into the existing pipeline.

---

## Plugin Types

There are three abstract base classes (ABCs) in `axon.plugins.base`:

| Plugin ABC | Method signature | Effect |
|---|---|---|
| `CompressionPlugin` | `compress(segments, **kwargs) -> list[str]` | Called in pipeline order; output feeds the next plugin |
| `RoutingPlugin` | `route(messages, requested_model, **kwargs) -> RoutingDecision \| None` | Called before the default router; `None` means "defer to default" |
| `ArtifactClassifierPlugin` | `classify(content, **kwargs) -> ArtifactType \| None` | Called before the built-in classifier; `None` means "defer to built-in" |

---

## Writing a Plugin

### Compression Plugin

```python
from axon.plugins.base import CompressionPlugin

class MyCompressionPlugin(CompressionPlugin):
    """Strips XML tags from every segment before compression."""

    def compress(self, segments: list[str], **kwargs: object) -> list[str]:
        import re
        return [re.sub(r"<[^>]+>", "", seg) for seg in segments]
```

### Routing Plugin

```python
from axon.plugins.base import RoutingPlugin
from axon.router.rule_router import RoutingDecision, ModelTier

class MyRoutingPlugin(RoutingPlugin):
    """Always route requests that mention 'embed' to the embeddings tier."""

    def route(
        self,
        messages: list[dict[str, object]],
        requested_model: str,
        **kwargs: object,
    ) -> RoutingDecision | None:
        content = " ".join(
            str(m.get("content", "")) for m in messages
        ).lower()
        if "embed" in content:
            return RoutingDecision(
                tier=ModelTier.EMBEDDING,
                routing_rule="plugin.embed_keyword",
            )
        return None  # defer to default router
```

### Artifact Classifier Plugin

```python
from axon.plugins.base import ArtifactClassifierPlugin
from axon.classifier.artifact_type import ArtifactType

class MyClassifierPlugin(ArtifactClassifierPlugin):
    """Classify segments beginning with '##METRIC:' as TOOL_RESULT."""

    def classify(self, content: str, **kwargs: object) -> ArtifactType | None:
        if content.startswith("##METRIC:"):
            return ArtifactType.TOOL_RESULT
        return None  # defer to built-in classifier
```

---

## Registering a Plugin via Entry Points

The recommended way to distribute a plugin is as an installable Python package
with an entry point in the `"axon.plugins"` group.

### `pyproject.toml` example

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "axon-plugin-mycompany"
version = "0.1.0"
dependencies = ["axon-sdk>=0.5.0"]

[project.entry-points."axon.plugins"]
my_compression = "axon_plugin_mycompany.compression:MyCompressionPlugin"
my_router      = "axon_plugin_mycompany.routing:MyRoutingPlugin"
my_classifier  = "axon_plugin_mycompany.classifier:MyClassifierPlugin"
```

After installing your package (`pip install axon-plugin-mycompany`), Axon's
`PluginLoader` will discover and load all registered plugins automatically.

---

## Loading Plugins Programmatically

If you prefer to register plugins directly without entry points:

```python
from axon.plugins import PluginRegistry, PluginLoader

registry = PluginRegistry()

# Manual registration
registry.register(MyCompressionPlugin())
registry.register(MyRoutingPlugin())

# Entry-point discovery (loads all installed axon.plugins entry points)
loader = PluginLoader()
loaded_count = loader.load_all(registry)
print(f"Loaded {loaded_count} plugins from entry points")
```

---

## Plugin Composition Rules

### Compression plugins
All registered `CompressionPlugin` instances are called in registration order.
The output of one plugin is the input of the next (pipeline composition):

```
segments → Plugin1.compress → Plugin2.compress → ... → compressed_segments
```

### Routing plugins
The first `RoutingPlugin` that returns a non-`None` `RoutingDecision` wins.
The default router is skipped entirely for that request.

### Artifact classifier plugins
The first `ArtifactClassifierPlugin` that returns a non-`None` `ArtifactType`
wins.  The built-in classifier is skipped for that segment.

---

## Error Handling

Plugin load failures are non-fatal.  If a plugin raises an exception during
`PluginLoader.load_all()`, Axon logs the error via structlog and continues
loading remaining plugins.  A partial failure never prevents the SDK from
operating.

At call time, exceptions in compression plugins propagate (you own your plugin).
Exceptions in routing plugins are caught by the router and treated as `None`
(defer to default).

---

## Testing Your Plugin

```python
from axon.plugins import PluginRegistry

registry = PluginRegistry()
registry.register(MyCompressionPlugin())

# Isolate test state
registry.clear()
```

---

## See Also

- [ml-router-guide.md](ml-router-guide.md) — built-in ML router
- [provider-expansion.md](provider-expansion.md) — adding custom providers
