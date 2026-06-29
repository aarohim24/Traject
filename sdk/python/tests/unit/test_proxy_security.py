"""Unit tests for proxy security hardening (FIX C6).

Covers:
- ``validate_backend_url`` SSRF / scheme guards.
- ``_filtered_forward_headers`` allowlist + credential stripping.
"""

from __future__ import annotations

import pytest

from traject.proxy.app import _filtered_forward_headers, validate_backend_url


class TestValidateBackendUrl:
    """SSRF and scheme validation for the configured backend URL."""

    def test_accepts_https_public_host(self) -> None:
        # Must not raise.
        validate_backend_url("https://api.openai.com")

    def test_accepts_http_localhost_ollama(self) -> None:
        # Documented local dev case (Ollama / LM Studio).
        validate_backend_url("http://localhost:11434")

    def test_rejects_cloud_metadata_ip(self) -> None:
        with pytest.raises(ValueError):
            validate_backend_url("http://169.254.169.254/")

    def test_rejects_private_10_range(self) -> None:
        with pytest.raises(ValueError):
            validate_backend_url("http://10.0.0.1/")

    def test_rejects_private_192_168_range(self) -> None:
        with pytest.raises(ValueError):
            validate_backend_url("http://192.168.1.1/")

    def test_rejects_plain_http_non_loopback(self) -> None:
        with pytest.raises(ValueError):
            validate_backend_url("http://evil.com")


class TestFilteredForwardHeaders:
    """Allowlist-based header forwarding strips inbound credentials."""

    def test_strips_authorization_and_cookie(self) -> None:
        inbound = {
            "Authorization": "Bearer client-secret",
            "Cookie": "session=abc",
            "x-api-key": "client-key",
            "api-key": "client-key2",
            "Content-Type": "application/json",
        }
        out = _filtered_forward_headers(inbound)
        lowered = {k.lower() for k in out}
        assert "authorization" not in lowered
        assert "cookie" not in lowered
        assert "x-api-key" not in lowered
        assert "api-key" not in lowered
        # Allowlisted header survives.
        assert any(k.lower() == "content-type" for k in out)

    def test_drops_non_allowlisted_headers(self) -> None:
        inbound = {"X-Random-Header": "leak", "Accept": "application/json"}
        out = _filtered_forward_headers(inbound)
        lowered = {k.lower() for k in out}
        assert "x-random-header" not in lowered
        assert "accept" in lowered

    def test_forwards_provider_specific_headers(self) -> None:
        inbound = {
            "anthropic-version": "2023-06-01",
            "openai-beta": "assistants=v2",
        }
        out = _filtered_forward_headers(inbound)
        lowered = {k.lower() for k in out}
        assert "anthropic-version" in lowered
        assert "openai-beta" in lowered
