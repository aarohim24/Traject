"""Unit tests for traject.proxy.app — OpenAI-compatible compression proxy."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx

from traject.compression.strategies import CompressionStrategy
from traject.exceptions import TrajectError
from traject.proxy.app import create_app

# ---------------------------------------------------------------------------
# Shared fake upstream response
# ---------------------------------------------------------------------------

_FAKE_COMPLETION: dict[str, Any] = {
    "id": "chatcmpl-test123",
    "object": "chat.completion",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello from upstream!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}

_FAKE_MODELS: dict[str, Any] = {
    "object": "list",
    "data": [{"id": "gpt-4o", "object": "model"}],
}

_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
_MODELS_URL = "https://api.openai.com/v1/models"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    backend_url: str = "https://api.openai.com",
    shadow_mode: bool = True,
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
) -> httpx.AsyncClient:
    """Return an AsyncClient wired to a create_app() instance."""
    app = create_app(
        backend_url=backend_url,
        strategy=strategy,
        shadow_mode=shadow_mode,
    )
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    """GET /health returns 200 with status 'ok'."""
    async with _make_client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["shadow_mode"] is True
    assert "version" in body
    assert "strategy" in body


@pytest.mark.asyncio
@respx.mock
async def test_chat_completions_compresses_and_forwards() -> None:
    """Messages are forwarded to the upstream backend."""
    respx.post(_COMPLETIONS_URL).mock(
        return_value=httpx.Response(200, json=_FAKE_COMPLETION)
    )

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Say hello."}],
    }

    async with _make_client() as client:
        response = await client.post(
            "/v1/chat/completions",
            json=payload,
        )

    assert response.status_code == 200
    assert respx.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_chat_completions_shadow_mode_forwards_original() -> None:
    """In shadow mode, upstream receives messages identical to the original."""
    captured_body: dict[str, Any] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return httpx.Response(200, json=_FAKE_COMPLETION)

    respx.post(_COMPLETIONS_URL).mock(side_effect=_capture)

    original_content = "Original uncompressed message content."
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": original_content}],
    }

    async with _make_client(shadow_mode=True) as client:
        await client.post("/v1/chat/completions", json=payload)

    forwarded_messages = captured_body.get("messages", [])
    assert len(forwarded_messages) == 1
    assert forwarded_messages[0]["content"] == original_content


@pytest.mark.asyncio
@respx.mock
async def test_chat_completions_adds_traject_headers() -> None:
    """Response includes X-Traject-Tokens-Saved and X-Traject-Shadow-Mode headers."""
    respx.post(_COMPLETIONS_URL).mock(
        return_value=httpx.Response(200, json=_FAKE_COMPLETION)
    )

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Headers test."}],
    }

    async with _make_client() as client:
        response = await client.post("/v1/chat/completions", json=payload)

    assert "x-traject-tokens-saved" in response.headers
    assert "x-traject-shadow-mode" in response.headers


@pytest.mark.asyncio
@respx.mock
async def test_chat_completions_handles_compression_error() -> None:
    """When compress() raises TrajectError, the request still completes."""
    respx.post(_COMPLETIONS_URL).mock(
        return_value=httpx.Response(200, json=_FAKE_COMPLETION)
    )

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Compression error test."}],
    }

    with patch(
        "traject.proxy.app.compress",
        side_effect=TrajectError("simulated engine failure"),
    ):
        async with _make_client() as client:
            response = await client.post("/v1/chat/completions", json=payload)

    # The proxy must fall back and still forward the request successfully.
    assert response.status_code == 200
    assert respx.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_models_endpoint_passes_through() -> None:
    """GET /v1/models forwards to the backend and returns its response."""
    respx.get(_MODELS_URL).mock(
        return_value=httpx.Response(200, json=_FAKE_MODELS)
    )

    async with _make_client() as client:
        response = await client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert respx.calls.call_count == 1
