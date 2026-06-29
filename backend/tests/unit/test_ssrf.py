"""Unit tests for the SSRF validation module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from traject_backend.core.ssrf import SSRFValidationError, validate_external_url

# A public, non-reserved IP (example.com's address) for mocking DNS resolution
# so tests do not depend on live network access in CI.
_PUBLIC_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 443))]


class TestValidateExternalUrl:
    def test_valid_https_url(self) -> None:
        # Should not raise when the host resolves to a public address.
        with patch(
            "traject_backend.core.ssrf.socket.getaddrinfo",
            return_value=_PUBLIC_ADDRINFO,
        ):
            validate_external_url("https://hooks.example.com/webhook/abc123")

    def test_valid_https_url_non_default_port(self) -> None:
        # Explicit port path resolves to a public address and is allowed.
        with patch(
            "traject_backend.core.ssrf.socket.getaddrinfo",
            return_value=_PUBLIC_ADDRINFO,
        ):
            validate_external_url("https://hooks.example.com:8443/webhook")

    def test_rejects_http_when_https_required(self) -> None:
        with pytest.raises(SSRFValidationError, match="https"):
            validate_external_url("http://hooks.example.com/webhook")

    def test_allows_http_when_not_required(self) -> None:
        with patch(
            "traject_backend.core.ssrf.socket.getaddrinfo",
            return_value=_PUBLIC_ADDRINFO,
        ):
            validate_external_url("http://hooks.example.com/webhook", require_https=False)

    def test_rejects_non_http_scheme(self) -> None:
        with pytest.raises(SSRFValidationError, match="scheme"):
            validate_external_url("ftp://hooks.example.com/file", require_https=False)

    def test_rejects_loopback(self) -> None:
        with pytest.raises(SSRFValidationError, match="disallowed address"):
            validate_external_url("https://127.0.0.1/webhook")

    def test_rejects_localhost(self) -> None:
        with pytest.raises(SSRFValidationError, match="disallowed address"):
            validate_external_url("https://localhost/webhook")

    def test_rejects_private_ipv4(self) -> None:
        with pytest.raises(SSRFValidationError, match="disallowed address"):
            validate_external_url("https://192.168.1.1/webhook")

    def test_rejects_aws_metadata(self) -> None:
        with pytest.raises(SSRFValidationError, match="metadata"):
            validate_external_url("https://169.254.169.254/latest/meta-data/")

    def test_rejects_gcp_metadata_hostname(self) -> None:
        with pytest.raises(SSRFValidationError, match="metadata"):
            validate_external_url("https://metadata.google.internal/")

    def test_rejects_unresolvable_host(self) -> None:
        with pytest.raises(SSRFValidationError, match="resolve"):
            validate_external_url("https://this-host-does-not-exist.invalid/hook")

    def test_rejects_missing_host(self) -> None:
        with pytest.raises(SSRFValidationError, match="no host"):
            validate_external_url("https:///no-host")
