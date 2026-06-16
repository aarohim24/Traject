"""Unit tests for axon.core.telemetry_reporter.

Covers:
- No network calls when reporter is disabled (enabled=False).
- Correct POST URL and body when reporter is enabled.
- TelemetryPayload model never includes PII fields.
- Silent failure (returns False, no exception) on network errors.
- AXON_TELEMETRY_ENABLED=false env var overrides constructor enabled=True.

**Validates: Requirements 24.1, 24.2, 24.3**
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from traject.core.telemetry_reporter import TelemetryPayload, TelemetryReporter

# ---------------------------------------------------------------------------
# Helper: build a valid TelemetryPayload for testing
# ---------------------------------------------------------------------------


def _make_payload(**overrides: Any) -> TelemetryPayload:
    """Build a TelemetryPayload with sensible defaults.

    Args:
        **overrides: Any field values to override.

    Returns:
        A valid :class:`TelemetryPayload` instance.
    """
    defaults: dict[str, Any] = {
        "sdk_version": "0.1.0",
        "python_version": "3.11.9",
        "sample_count": 42,
        "p50_cost_usd": "0.00125000",
        "p95_cost_usd": "0.00310000",
        "p50_compression_ratio": 0.78,
        "p95_compression_ratio": 0.91,
        "avg_routing_accuracy": 0.95,
        "submitted_at": datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return TelemetryPayload(**defaults)


# ---------------------------------------------------------------------------
# Task 24.4 — Unit tests
# ---------------------------------------------------------------------------


class TestTelemetryReporterDisabled:
    """Tests for reporter behaviour when disabled."""

    def test_zero_network_calls_when_disabled(self) -> None:
        """No httpx calls are made and submit() returns False when disabled.

        ``TelemetryReporter(enabled=False).submit(payload)`` must return
        ``False`` without ever instantiating an ``httpx.Client``.

        **Validates: Requirements 24.2, 24.3**
        """
        reporter = TelemetryReporter(enabled=False)
        payload = _make_payload()

        with patch("httpx.Client") as mock_client_cls:
            result = reporter.submit(payload)

        assert result is False, "Expected submit() to return False when disabled"
        mock_client_cls.assert_not_called()


class TestTelemetryReporterEnabled:
    """Tests for reporter behaviour when enabled."""

    def test_enabled_true_submits_correct_fields(self) -> None:
        """POST is called with correct URL and body containing all payload fields.

        When ``enabled=True`` the reporter must POST to
        ``{base_url}/v1/benchmarks/submit`` with a JSON body that matches the
        ``TelemetryPayload`` field set exactly.

        **Validates: Requirements 24.2, 24.3**
        """
        payload = _make_payload()
        expected_url = "http://localhost:8000/v1/benchmarks/submit"

        # Build a mock httpx response: status 200
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client_instance = MagicMock()
        mock_client_instance.post.return_value = mock_response
        # Support context-manager protocol (with httpx.Client() as client)
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client_instance):
            reporter = TelemetryReporter(enabled=True)
            result = reporter.submit(payload)

        assert result is True, "Expected submit() to return True on HTTP 200"

        mock_client_instance.post.assert_called_once()
        call_args = mock_client_instance.post.call_args
        actual_url: str = call_args[0][0] if call_args[0] else call_args.kwargs["url"]
        actual_body: dict[str, Any] = (
            call_args.kwargs.get("json") or call_args[1].get("json", {})
        )

        assert actual_url == expected_url, (
            f"Expected POST to {expected_url!r}, got {actual_url!r}"
        )

        # All payload fields must appear in the body
        expected_body = payload.model_dump(mode="json")
        for field, value in expected_body.items():
            assert field in actual_body, f"Field {field!r} missing from POST body"
            assert actual_body[field] == value, (
                f"Field {field!r}: expected {value!r}, got {actual_body[field]!r}"
            )


class TestTelemetryPayloadNoPII:
    """Tests that TelemetryPayload never exposes PII fields."""

    def test_payload_never_includes_pii(self) -> None:
        """TelemetryPayload model fields must not include any PII field names.

        Specifically, the model must NOT have fields named ``feature_tag``,
        ``prompt``, ``api_key``, or ``user_id``.

        **Validates: Requirements 24.1**
        """
        pii_fields = {"feature_tag", "prompt", "api_key", "user_id"}
        model_fields = set(TelemetryPayload.model_fields.keys())

        found_pii = pii_fields & model_fields
        assert not found_pii, (
            f"TelemetryPayload must not contain PII fields, but found: {found_pii}"
        )


class TestTelemetryReporterNetworkErrors:
    """Tests for graceful handling of network failures."""

    def test_fails_silently_on_network_error(self) -> None:
        """submit() returns False and never raises on httpx.ConnectError.

        The reporter must catch ``httpx.ConnectError`` (and any other
        exception) without propagating it to the caller.

        **Validates: Requirements 24.3**
        """
        import httpx

        mock_client_instance = MagicMock()
        mock_client_instance.post.side_effect = httpx.ConnectError("timeout")
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client_instance):
            reporter = TelemetryReporter(enabled=True)
            # Must not raise
            result = reporter.submit(_make_payload())

        assert result is False, (
            "Expected submit() to return False on ConnectError, not raise"
        )


class TestTelemetryReporterEnvVar:
    """Tests for environment-variable override behaviour."""

    def test_env_var_false_keeps_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AXON_TELEMETRY_ENABLED=false overrides constructor enabled=True.

        When the env var is set to ``"false"`` (case-insensitive), the
        reporter must be disabled even if the constructor was called with
        ``enabled=True``.

        **Validates: Requirements 24.2**
        """
        monkeypatch.setenv("AXON_TELEMETRY_ENABLED", "false")
        reporter = TelemetryReporter(enabled=True)
        assert reporter._enabled is False, (
            "Expected _enabled=False when AXON_TELEMETRY_ENABLED=false, "
            f"got _enabled={reporter._enabled}"
        )

    def test_env_var_true_enables_reporter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AXON_TELEMETRY_ENABLED=true enables reporter even when enabled=False.

        **Validates: Requirements 24.2**
        """
        monkeypatch.setenv("AXON_TELEMETRY_ENABLED", "true")
        reporter = TelemetryReporter(enabled=False)
        assert reporter._enabled is True, (
            "Expected _enabled=True when AXON_TELEMETRY_ENABLED=true, "
            f"got _enabled={reporter._enabled}"
        )

    def test_env_var_not_set_uses_constructor_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When AXON_TELEMETRY_ENABLED is unset, constructor value is used.

        **Validates: Requirements 24.2**
        """
        monkeypatch.delenv("AXON_TELEMETRY_ENABLED", raising=False)
        reporter_on = TelemetryReporter(enabled=True)
        reporter_off = TelemetryReporter(enabled=False)
        assert reporter_on._enabled is True
        assert reporter_off._enabled is False
