"""Opt-in production telemetry reporter for the Axon SDK.

Collects aggregate, anonymised performance metrics (no PII, no prompt content)
and submits them to the Axon benchmark registry endpoint.  The reporter is
**disabled by default** and must be explicitly enabled by the caller or via the
``AXON_TELEMETRY_ENABLED`` environment variable.

Data collected when enabled: SDK version, Python version, sample count, p50/p95
cost in USD (as strings), p50/p95 compression ratio, average routing accuracy,
and the submission timestamp.  No feature tags, prompt text, API keys, or user
identifiers are ever collected.
"""

from __future__ import annotations

import os
from datetime import datetime

import structlog
from pydantic import BaseModel

_log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class TelemetryPayload(BaseModel):
    """Aggregate SDK telemetry payload.

    All fields are anonymised aggregate statistics.  No personally-identifiable
    information, prompt content, feature tags, or API keys are included.

    Attributes:
        sdk_version: Axon SDK version string (e.g. ``"0.1.0"``).
        python_version: Python interpreter version string (e.g. ``"3.11.9"``).
        sample_count: Number of inference spans included in the aggregation.
        p50_cost_usd: Median cost in USD, serialised as a decimal string.
        p95_cost_usd: 95th-percentile cost in USD, serialised as a decimal
            string.
        p50_compression_ratio: Median compression ratio (output/input tokens).
        p95_compression_ratio: 95th-percentile compression ratio.
        avg_routing_accuracy: Mean routing accuracy across the sample window.
        submitted_at: UTC datetime of when this payload was submitted.
    """

    sdk_version: str
    python_version: str
    sample_count: int
    p50_cost_usd: str
    p95_cost_usd: str
    p50_compression_ratio: float
    p95_compression_ratio: float
    avg_routing_accuracy: float
    submitted_at: datetime


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


class TelemetryReporter:
    """Opt-in reporter that submits aggregate telemetry to the benchmark registry.

    Telemetry is **disabled by default**.  It can be enabled in two ways:

    1. Pass ``enabled=True`` to the constructor.
    2. Set the ``AXON_TELEMETRY_ENABLED`` environment variable to ``"true"``
       (case-insensitive).  Setting it to ``"false"`` overrides a
       constructor-level ``enabled=True``.

    When disabled (the default) this class is a no-op: ``submit()`` returns
    ``False`` immediately without making any network calls.

    Args:
        enabled: Whether telemetry is enabled.  May be overridden by the
            ``AXON_TELEMETRY_ENABLED`` environment variable.
        base_url: Base URL of the Axon backend service.  Defaults to
            ``"http://localhost:8000"``.
    """

    _SUBMIT_PATH: str = "/v1/benchmarks/submit"

    def __init__(
        self,
        enabled: bool = False,
        base_url: str = "http://localhost:8000",
    ) -> None:
        self._base_url: str = base_url
        self._enabled: bool = enabled

        # Environment variable takes precedence over constructor argument
        env_val: str = os.environ.get("AXON_TELEMETRY_ENABLED", "").strip().lower()
        if env_val == "true":
            self._enabled = True
        elif env_val == "false":
            self._enabled = False
        # If env var not set, keep the constructor value

        if self._enabled:
            _log.info(
                "axon.telemetry_reporter.enabled",
                collected_fields=[
                    "sdk_version",
                    "python_version",
                    "sample_count",
                    "p50_cost_usd",
                    "p95_cost_usd",
                    "p50_compression_ratio",
                    "p95_compression_ratio",
                    "avg_routing_accuracy",
                    "submitted_at",
                ],
                note="No PII, prompt content, feature tags, or API keys are collected.",
            )

    def submit(self, payload: TelemetryPayload) -> bool:
        """Submit a telemetry payload to the benchmark registry.

        If telemetry is disabled, returns ``False`` immediately without making
        any network call.  Otherwise, POSTs the payload as JSON to
        ``{base_url}/v1/benchmarks/submit`` using a synchronous ``httpx``
        client with a 5-second timeout.

        Args:
            payload: The :class:`TelemetryPayload` to submit.

        Returns:
            ``True`` if the server responded with HTTP 2xx, ``False`` in all
            other cases (disabled, network error, non-2xx response, etc.).

        Note:
            This method never raises.  All exceptions are caught, logged at
            ``WARNING`` level via structlog, and cause ``False`` to be returned.
        """
        if not self._enabled:
            return False

        import httpx  # local import to keep startup cost near-zero when disabled

        url = f"{self._base_url}{self._SUBMIT_PATH}"
        body = payload.model_dump(mode="json")

        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.post(url, json=body)
            if 200 <= response.status_code < 300:
                _log.info(
                    "axon.telemetry_reporter.submit_ok",
                    status_code=response.status_code,
                )
                return True
            _log.warning(
                "axon.telemetry_reporter.submit_non_2xx",
                status_code=response.status_code,
            )
            return False
        except Exception as exc:
            _log.warning(
                "axon.telemetry_reporter.submit_error",
                error=str(exc),
            )
            return False
