"""Instrumentation decorator and patch function for Traject SDK.

Provides @instrument() decorator and patch() for wrapping OpenAI and
Anthropic LLM calls with zero behavioral change to the caller. Orchestrates
the full Traject pipeline: compression (shadow mode), token extraction, cost
calculation, artifact classification, and OTEL span emission.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import structlog

from traject.classifier.artifact_type import ArtifactType, classify
from traject.compression.engine import compress
from traject.compression.strategies import (
    CompressionConfig,
    CompressionStrategy,
    get_config,
)
from traject.core.cost_calculator import calculate_cost
from traject.core.provider_adapter import UsageData, get_adapter
from traject.exceptions import TrajectError
from traject.models import CompressionResult, InferenceSpan
from traject.telemetry.otel_exporter import configure_exporter, emit_span

_logger = structlog.get_logger(__name__)

# Module-level BackendClient — set by configure() when backend_url is provided.
# TYPE_CHECKING guard avoids importing httpx at module load time.
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from traject.backend_client import BackendClient
    from traject.router.rule_router import RuleRouter

_backend_client: BackendClient | None = None

# Module-level RuleRouter — set by configure() when router is provided.
# Import is guarded with TYPE_CHECKING to prevent circular imports at load time.
_router: RuleRouter | None = None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _hash_prompt(messages: list[dict[str, Any]]) -> str:
    """Compute SHA-256 hex digest of normalized prompt content.

    Normalization: concatenate all content strings, strip whitespace, lowercase.
    Raw content is never stored or logged.

    Args:
        messages: List of message dicts with optional 'content' fields.

    Returns:
        64-character lowercase hex SHA-256 digest.
    """
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content.strip().lower())
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text", "")
                    if isinstance(text, str):
                        parts.append(text.strip().lower())
    normalized = " ".join(parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _extract_messages(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Best-effort extraction of messages from function arguments.

    Checks kwargs first ('messages' key), then the first positional arg
    if it is a list of dicts.

    Args:
        args: Positional arguments from the wrapped function call.
        kwargs: Keyword arguments from the wrapped function call.

    Returns:
        The messages list if found, or None.
    """
    messages = kwargs.get("messages")
    if (
        isinstance(messages, list)
        and len(messages) > 0
        and isinstance(messages[0], dict)
    ):
        return messages
    if (
        args
        and isinstance(args[0], list)
        and len(args[0]) > 0
        and isinstance(args[0][0], dict)
    ):
        return args[0]
    return None


def _detect_provider(fn: Any, args: tuple[Any, ...]) -> str:  # noqa: ANN401 — fn is an arbitrary callable
    """Best-effort detection of provider from function module or first arg class.

    Args:
        fn: The wrapped callable.
        args: Positional arguments from the call.

    Returns:
        'openai', 'anthropic', or 'unknown'.
    """
    module_name = getattr(fn, "__module__", "") or ""
    if "openai" in module_name.lower():
        return "openai"
    if "anthropic" in module_name.lower():
        return "anthropic"
    if args:
        cls_name = type(args[0]).__name__.lower()
        if "openai" in cls_name:
            return "openai"
        if "anthropic" in cls_name:
            return "anthropic"
    return "unknown"


def _build_compression_config(
    strategy: CompressionStrategy,
    shadow_mode: bool,
) -> CompressionConfig:
    """Build CompressionConfig from strategy and shadow_mode flag."""
    base = get_config(strategy)
    return CompressionConfig(
        strategy=base.strategy,
        target_reduction_pct=base.target_reduction_pct,
        min_turns_protected=base.min_turns_protected,
        protect_system_prompt=True,
        shadow_mode=shadow_mode,
    )


def _run_pipeline(
    response: Any,  # noqa: ANN401 — provider response type is framework-specific
    messages: list[dict[str, Any]] | None,
    prompt_hash: str,
    compression_result: CompressionResult | None,
    fn: Any,  # noqa: ANN401 — fn is an arbitrary user-provided callable
    args: tuple[Any, ...],
    start_time: float,
    feature_tag: str,
    environment: str,
    config: CompressionConfig,
) -> None:
    """Run the post-call Traject pipeline (usage extraction → cost → span emit).

    Never raises. All TrajectError subclasses are caught and logged.
    """
    duration_ms = int((time.perf_counter() - start_time) * 1000)

    # Extract usage
    provider = _detect_provider(fn, args)
    input_tokens = 0
    output_tokens = 0
    cached_tokens = 0
    token_count_method: str = "estimated"
    model = "unknown"
    cost = None
    try:
        adapter = get_adapter(provider)
        usage: UsageData = adapter.extract_usage(response)
        model = adapter.extract_model(response)
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cached_tokens = usage.cached_tokens
        token_count_method = usage.token_count_method
        cost = calculate_cost(model, input_tokens, output_tokens, cached_tokens)
    except TrajectError as exc:
        _logger.warning("traject.usage_extraction.failed", error=str(exc))

    # Classify first message
    artifact_type = ArtifactType.UNKNOWN
    if messages:
        try:
            artifact_type = classify(messages[0], 0, len(messages))
        except Exception as exc:
            _logger.warning("traject.classification.failed", error=str(exc))

    # Build and emit span
    try:
        span = InferenceSpan(
            id=uuid.uuid4(),
            trace_id=str(uuid.uuid4()),
            parent_span_id=None,
            span_name=f"gen_ai.{provider}.{model}",
            timestamp=datetime.utcnow(),
            duration_ms=max(0, duration_ms),
            provider=provider,
            model=model,
            api_version=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            token_count_method=(
                "exact" if token_count_method == "exact" else "estimated"
            ),
            cost_usd=cost,
            feature_tag=feature_tag,
            prompt_hash=prompt_hash,
            artifact_type=artifact_type,
            compression_applied=(
                compression_result is not None and not config.shadow_mode
            ),
            shadow_mode=config.shadow_mode,
            pre_compression_tokens=(
                compression_result.original_tokens if compression_result else None
            ),
            tokens_saved=(
                compression_result.tokens_saved if compression_result else None
            ),
            cache_hit=cached_tokens > 0,
            environment=environment,
        )
        emit_span(span)
        # Fire-and-forget to backend if configured
        if _backend_client is not None:
            with contextlib.suppress(RuntimeError):
                asyncio.create_task(_backend_client.send_span(span))
    except TrajectError as exc:
        _logger.warning("traject.span_emission.failed", error=str(exc))
    except Exception as exc:
        _logger.warning("traject.span_emission.unexpected_error", error=str(exc))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def instrument(
    feature_tag: str = "default",
    shadow_mode: bool = True,
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
    environment: str = "production",
) -> Callable[..., Any]:
    """Return a decorator that instruments an LLM-calling function.

    The decorator wraps both synchronous and asynchronous callables. It:
    1. Records wall-clock start time
    2. Hashes the prompt (SHA-256 of normalized content — never stores raw text)
    3. Runs the compression pipeline in shadow mode (ADR-004)
    4. Calls the original function with ORIGINAL arguments (unmodified)
    5. Extracts token usage from the response
    6. Calculates cost via the static pricing table
    7. Emits an OTEL span

    If any Traject pipeline step raises an TrajectError, it is caught, logged via
    structlog, and the original response is returned unchanged. Caller
    exceptions are never suppressed.

    Args:
        feature_tag: Logical label for cost attribution (e.g. "support-bot").
        shadow_mode: When True (default), compression analysis runs but
            original messages are always forwarded to the provider.
        strategy: Compression strategy to apply (default: CONSERVATIVE).
        environment: Deployment environment label (e.g. "production").

    Returns:
        A decorator that wraps a sync or async callable.
    """
    config = _build_compression_config(strategy, shadow_mode)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
                start_time = time.perf_counter()
                messages = _extract_messages(args, kwargs)
                prompt_hash = _hash_prompt(messages) if messages else _hash_prompt([])

                # Run compression pipeline (shadow mode — never modifies args)
                compression_result: CompressionResult | None = None
                if messages:
                    try:
                        compression_result = compress(messages, config)
                    except TrajectError as exc:
                        _logger.warning("traject.compression.failed", error=str(exc))

                # Apply router if configured — logs and records routing decision
                if _router is not None and messages is not None:
                    requested_model: str = kwargs.get("model", "unknown") or "unknown"
                    routing_decision = _router.route(messages, requested_model)
                    _logger.info(
                        "traject.router.decision",
                        selected_model=routing_decision.selected_model,
                        original_model=routing_decision.original_model,
                        task_type=routing_decision.task_type,
                        complexity_tier=routing_decision.complexity_tier,
                        routing_rule=routing_decision.routing_rule,
                        cost_delta_pct=routing_decision.cost_delta_pct,
                    )

                # Call original function with original arguments
                response = await fn(*args, **kwargs)

                # Run post-call pipeline (never raises)
                _run_pipeline(
                    response=response,
                    messages=messages,
                    prompt_hash=prompt_hash,
                    compression_result=compression_result,
                    fn=fn,
                    args=args,
                    start_time=start_time,
                    feature_tag=feature_tag,
                    environment=environment,
                    config=config,
                )
                return response

            return async_wrapper
        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
                start_time = time.perf_counter()
                messages = _extract_messages(args, kwargs)
                prompt_hash = _hash_prompt(messages) if messages else _hash_prompt([])

                # Run compression pipeline
                compression_result: CompressionResult | None = None
                if messages:
                    try:
                        compression_result = compress(messages, config)
                    except TrajectError as exc:
                        _logger.warning("traject.compression.failed", error=str(exc))

                # Apply router if configured — logs and records routing decision
                if _router is not None and messages is not None:
                    requested_model_sync: str = (
                        kwargs.get("model", "unknown") or "unknown"
                    )
                    routing_decision_sync = _router.route(
                        messages, requested_model_sync
                    )
                    _logger.info(
                        "traject.router.decision",
                        selected_model=routing_decision_sync.selected_model,
                        original_model=routing_decision_sync.original_model,
                        task_type=routing_decision_sync.task_type,
                        complexity_tier=routing_decision_sync.complexity_tier,
                        routing_rule=routing_decision_sync.routing_rule,
                        cost_delta_pct=routing_decision_sync.cost_delta_pct,
                    )

                # Call original function
                response = fn(*args, **kwargs)

                # Run post-call pipeline
                _run_pipeline(
                    response=response,
                    messages=messages,
                    prompt_hash=prompt_hash,
                    compression_result=compression_result,
                    fn=fn,
                    args=args,
                    start_time=start_time,
                    feature_tag=feature_tag,
                    environment=environment,
                    config=config,
                )
                return response

            return sync_wrapper

    return decorator


def patch(
    client: Any,  # noqa: ANN401 — accepts OpenAI/Anthropic/async variants; no common base type
    feature_tag: str = "default",
    shadow_mode: bool = True,
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
    environment: str = "production",
) -> None:
    """Monkey-patch an existing provider client to instrument all calls.

    Wraps the appropriate method on the client object in-place:
    - OpenAI / AsyncOpenAI: patches ``client.chat.completions.create``
    - Anthropic / AsyncAnthropic: patches ``client.messages.create``

    Args:
        client: An OpenAI or Anthropic client instance.
        feature_tag: Logical label for cost attribution.
        shadow_mode: When True, compression analysis runs but original
            messages are always forwarded.
        strategy: Compression strategy to apply.
        environment: Deployment environment label.
    """
    decorator = instrument(
        feature_tag=feature_tag,
        shadow_mode=shadow_mode,
        strategy=strategy,
        environment=environment,
    )

    # Try OpenAI chat.completions.create
    try:
        original = client.chat.completions.create
        client.chat.completions.create = decorator(original)
        return
    except AttributeError:
        pass

    # Try Anthropic messages.create
    try:
        original = client.messages.create
        client.messages.create = decorator(original)
        return
    except AttributeError:
        pass

    _logger.warning(
        "traject.patch.no_method_found",
        client_type=type(client).__name__,
        message=(
            "Could not find chat.completions.create or messages.create on "
            f"{type(client).__name__}. The client was not patched."
        ),
    )


def configure(
    otlp_endpoint: str | None = None,
    export_to_stdout: bool = True,
    export_format: str = "summary",
    local_span_log: str | None = None,
    backend_url: str | None = None,
    backend_api_key: str | None = None,
    router: RuleRouter | None = None,
) -> None:
    """Configure the Traject SDK telemetry exporter, optional backend client, and router.

    Delegates OTEL setup to
    :func:`~traject.telemetry.otel_exporter.configure_exporter`.
    When ``backend_url`` is provided, creates a
    :class:`~traject.backend_client.BackendClient` that receives a copy of
    every span in addition to the OTEL export path.  Both paths run
    independently — a backend error never affects OTEL export.

    When ``router`` is provided, stores it as the module-level ``_router``
    so that subsequent ``instrument()`` / ``patch()`` wrappers invoke
    ``router.route()`` before each LLM call and log the routing decision.
    When ``router`` is ``None`` (default), routing is skipped and behaviour
    is identical to Phase 1/2.

    Idempotent: safe to call multiple times.  A second call with the same
    ``backend_url`` is a no-op; a second call with a different
    ``backend_url`` replaces the existing client.

    Args:
        otlp_endpoint: gRPC endpoint for an OTLP collector.
        export_to_stdout: Whether to also export to stdout (console).
        export_format: Controls stdout output format when ``export_to_stdout``
            is ``True``.  ``"summary"`` (default) prints a compact
            human-readable line per span.  ``"json"`` outputs full OTEL JSON.
        local_span_log: Reserved for Phase 2 local SQLite logging.
            Currently unused.
        backend_url: Base URL of the Traject backend service.  When set,
            spans are also sent to ``POST /v1/spans`` via
            :class:`~traject.backend_client.BackendClient`.
        backend_api_key: API key for the backend service.  Required when
            ``backend_url`` is set.
        router: Optional :class:`~traject.router.rule_router.RuleRouter`
            instance.  When provided, ``route()`` is called before each
            LLM call and the routing decision is recorded in structlog
            output.  When ``None``, no routing logic executes.
    """
    global _backend_client, _router
    configure_exporter(
        otlp_endpoint=otlp_endpoint,
        export_to_stdout=export_to_stdout,
        export_format=export_format,
    )

    if backend_url is not None:
        from traject.backend_client import BackendClient

        _backend_client = BackendClient(
            base_url=backend_url,
            api_key=backend_api_key or "",
        )

    if router is not None:
        _router = router
