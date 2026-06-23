"""FastAPI application for the Traject transparent compression proxy.

Provides a drop-in OpenAI-compatible ``/v1/chat/completions`` endpoint that
compresses incoming messages with Traject's compression pipeline before
forwarding the request to any upstream provider. Supports shadow mode
(metrics-only, default) and live compression.

All responses are forwarded verbatim from the upstream provider. Two
additional response headers are injected:

- ``X-Traject-Tokens-Saved``: tokens eliminated (0 in shadow mode)
- ``X-Traject-Shadow-Mode``: ``"true"`` or ``"false"``
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from traject.compression.engine import compress
from traject.compression.strategies import (
    CompressionConfig,
    CompressionStrategy,
    get_config,
)
from traject.exceptions import TrajectError

_log = structlog.get_logger(__name__)

_PROXY_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class _ChatMessage(BaseModel):
    """A single message in an OpenAI-compatible chat request.

    Attributes:
        role: Message role (e.g. ``"system"``, ``"user"``, ``"assistant"``).
        content: Message content — a plain string or a multimodal list.
    """

    role: str
    content: str | list[Any]  # Any: multimodal content lists are heterogeneous


class _ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request body.

    Captures all standard fields and preserves extra fields so they can
    be forwarded unchanged to the upstream provider.

    Attributes:
        model: Model identifier to use for completion.
        messages: Ordered list of chat messages.
        stream: Whether to stream the response.
        temperature: Optional sampling temperature.
        max_tokens: Optional maximum number of tokens to generate.
    """

    model: str
    messages: list[_ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    backend_url: str = "https://api.openai.com",
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
    shadow_mode: bool = True,
    api_key_env: str = "OPENAI_API_KEY",
) -> FastAPI:
    """Create and configure the Traject proxy FastAPI application.

    Args:
        backend_url: Base URL of the upstream OpenAI-compatible provider.
            Must not include a trailing slash.
        strategy: Compression strategy to apply to incoming messages.
        shadow_mode: When ``True`` (default), compresses and logs but
            forwards original uncompressed messages. Set to ``False`` for
            live compression.
        api_key_env: Name of the environment variable that holds the
            upstream provider API key. The value is read at request time
            and forwarded in the ``Authorization`` header.

    Returns:
        Configured :class:`~fastapi.FastAPI` application instance ready
        to be served with uvicorn.
    """
    _backend_url = backend_url.rstrip("/")

    app = FastAPI(
        title="Traject Compression Proxy",
        version=_PROXY_VERSION,
        description=(
            "Transparent OpenAI-compatible proxy that compresses context "
            "before forwarding to any upstream provider."
        ),
    )

    # Shared httpx async client — one per app instance.
    _http_client = httpx.AsyncClient(timeout=120.0)

    # Build the compression config once per app instance.
    base_config: CompressionConfig = get_config(strategy)
    _config = CompressionConfig(
        strategy=base_config.strategy,
        target_reduction_pct=base_config.target_reduction_pct,
        min_turns_protected=base_config.min_turns_protected,
        protect_system_prompt=base_config.protect_system_prompt,
        shadow_mode=shadow_mode,
        score_ceiling=base_config.score_ceiling,
    )

    # ------------------------------------------------------------------
    # GET /health
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Return proxy health status.

        Returns:
            JSON dict with ``status``, ``version``, ``shadow_mode``, and
            ``strategy``.
        """
        return {
            "status": "ok",
            "version": _PROXY_VERSION,
            "shadow_mode": shadow_mode,
            "strategy": strategy.value,
        }

    # ------------------------------------------------------------------
    # GET /v1/models  (passthrough)
    # ------------------------------------------------------------------

    @app.get("/v1/models")
    async def list_models(request: Request) -> JSONResponse:
        """Forward the models list request to the upstream provider.

        Args:
            request: The incoming FastAPI request.

        Returns:
            JSON response forwarded verbatim from the upstream provider.

        Raises:
            HTTPException: If the upstream request fails.
        """
        api_key = os.environ.get(api_key_env, "")
        headers: dict[str, str] = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"host", "content-length"}
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            upstream_resp = await _http_client.get(
                f"{_backend_url}/v1/models",
                headers=headers,
            )
        except httpx.RequestError as exc:
            _log.error("traject.proxy.models_upstream_error", error=str(exc))
            raise HTTPException(
                status_code=502,
                detail="Upstream request failed",
            ) from exc

        return JSONResponse(
            content=upstream_resp.json(),
            status_code=upstream_resp.status_code,
        )

    # ------------------------------------------------------------------
    # POST /v1/chat/completions
    # ------------------------------------------------------------------

    @app.post("/v1/chat/completions", response_model=None)
    async def chat_completions(request: Request) -> StreamingResponse | JSONResponse:
        """Compress messages and forward to the upstream provider.

        1. Parses the request body as :class:`_ChatCompletionRequest`.
        2. Converts messages to a plain ``list[dict]`` for the compression
           engine.
        3. Runs :func:`~traject.compression.engine.compress` (catches
           :class:`~traject.exceptions.TrajectError` and falls back to
           original messages).
        4. Forwards the (possibly compressed) request to the upstream
           provider with the original headers plus ``Authorization``.
        5. Returns the upstream response verbatim with two extra headers:
           ``X-Traject-Tokens-Saved`` and ``X-Traject-Shadow-Mode``.

        Args:
            request: The incoming FastAPI request.

        Returns:
            Either a :class:`~fastapi.responses.StreamingResponse` (when
            the upstream streams) or a :class:`~fastapi.responses.JSONResponse`.

        Raises:
            HTTPException: When the request body cannot be parsed or the
                upstream request fails at the transport layer.
        """
        # 1. Parse body.
        try:
            raw_body = await request.json()
            chat_req = _ChatCompletionRequest.model_validate(raw_body)
        except Exception as exc:
            _log.warning("traject.proxy.bad_request", error=str(exc))
            raise HTTPException(
                status_code=422,
                detail=f"Invalid request body: {exc}",
            ) from exc

        # 2. Convert to plain dicts for the compression engine.
        messages_plain: list[dict[str, Any]] = [
            {"role": msg.role, "content": msg.content} for msg in chat_req.messages
        ]

        # 3. Compress (fall back on error).
        tokens_saved = 0
        messages_to_forward = messages_plain
        try:
            result = compress(messages_plain, _config)
            tokens_saved = result.tokens_saved
            _log.info(
                "traject.proxy.compressed",
                original_tokens=result.original_tokens,
                compressed_tokens=result.compressed_tokens,
                tokens_saved=tokens_saved,
                compression_ratio=result.compression_ratio,
                shadow_mode=shadow_mode,
            )
            if not shadow_mode:
                messages_to_forward = [
                    m
                    if isinstance(m, dict)
                    else {
                        "role": m.get("role", "user"),
                        "content": m.get("content", ""),
                    }
                    for m in result.messages
                ]
        except TrajectError as exc:
            _log.warning(
                "traject.proxy.compression_error",
                error=str(exc),
            )

        # 4. Build forwarding request body.
        forward_body: dict[str, Any] = {**raw_body, "messages": messages_to_forward}

        # Build headers — strip hop-by-hop and Host; inject Authorization.
        api_key = os.environ.get(api_key_env, "")
        forward_headers: dict[str, str] = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"host", "content-length", "transfer-encoding"}
        }
        forward_headers["Content-Type"] = "application/json"
        if api_key:
            forward_headers["Authorization"] = f"Bearer {api_key}"

        extra_headers = {
            "X-Traject-Tokens-Saved": str(tokens_saved),
            "X-Traject-Shadow-Mode": str(shadow_mode).lower(),
        }

        # 5. Forward and return.
        try:
            if chat_req.stream:
                return await _forward_streaming(
                    _http_client,
                    _backend_url,
                    forward_body,
                    forward_headers,
                    extra_headers,
                )
            else:
                upstream_resp = await _http_client.post(
                    f"{_backend_url}/v1/chat/completions",
                    json=forward_body,
                    headers=forward_headers,
                )
                response_headers = dict(extra_headers)
                return JSONResponse(
                    content=upstream_resp.json(),
                    status_code=upstream_resp.status_code,
                    headers=response_headers,
                )
        except httpx.RequestError as exc:
            _log.error("traject.proxy.upstream_error", error=str(exc))
            raise HTTPException(
                status_code=502,
                detail="Upstream request failed",
            ) from exc

    return app


async def _forward_streaming(
    client: httpx.AsyncClient,
    backend_url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    extra_headers: dict[str, str],
) -> StreamingResponse:
    """Forward a streaming completion request and return a StreamingResponse.

    Args:
        client: Shared :class:`~httpx.AsyncClient` instance.
        backend_url: Base URL of the upstream provider (no trailing slash).
        body: JSON-serialisable request body to forward.
        headers: HTTP headers to send upstream.
        extra_headers: Additional response headers to inject
            (e.g. ``X-Traject-*``).

    Returns:
        :class:`~fastapi.responses.StreamingResponse` that proxies the
        upstream SSE stream to the caller.
    """

    async def _stream_generator() -> AsyncGenerator[bytes, None]:
        """Yield raw bytes from the upstream streaming response.

        Yields:
            Raw byte chunks from the upstream SSE stream.
        """
        async with client.stream(
            "POST",
            f"{backend_url}/v1/chat/completions",
            json=body,
            headers=headers,
        ) as upstream:
            async for chunk in upstream.aiter_bytes():
                yield chunk

    return StreamingResponse(
        _stream_generator(),
        media_type="text/event-stream",
        headers=extra_headers,
    )


# ---------------------------------------------------------------------------
# run() convenience wrapper
# ---------------------------------------------------------------------------


def run(host: str = "localhost", port: int = 8080, **kwargs: Any) -> None:
    """Start the Traject proxy server with uvicorn.

    Args:
        host: Host interface to bind.
        port: TCP port to listen on.
        **kwargs: Additional keyword arguments forwarded to
            :func:`create_app` (e.g. ``backend_url``, ``strategy``,
            ``shadow_mode``).
    """
    import uvicorn

    proxy_app = create_app(**kwargs)
    uvicorn.run(proxy_app, host=host, port=port)
