"""Async HTTP client for sending spans to the Axon backend service.

Provides :class:`BackendClient` which wraps ``httpx.AsyncClient`` with a
fire-and-forget span-send method and a fail-open budget-check method.
All methods catch every exception and log via structlog — they never raise
to the caller.

The backend integration is opt-in: a client is only created when
:func:`~axon.core.instrumentor.configure` is called with ``backend_url``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from axon.models import InferenceSpan

_log = structlog.get_logger(__name__)


class BudgetStatus(StrEnum):
    """Backend budget enforcement status returned by :meth:`BackendClient.check_budget`.

    Attributes:
        OK: Spend is below the alert threshold.
        WARNING: Spend is between the threshold and the budget limit.
        EXHAUSTED: Spend has reached or exceeded the budget limit.
    """

    OK = "ok"
    WARNING = "warning"
    EXHAUSTED = "exhausted"


class BackendClient:
    """Async HTTP client for communicating with the Axon backend service.

    All public methods are fire-and-forget: they never raise exceptions.
    Errors are logged via structlog at warning level.  A 2-second timeout
    ensures that backend latency cannot block the inference path.

    Args:
        base_url: Base URL of the Axon backend (e.g. ``"http://localhost:8000"``).
        api_key: API key sent in the ``X-Axon-API-Key`` header.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Axon-API-Key": api_key},
            timeout=2.0,
        )

    async def send_span(self, span: InferenceSpan) -> None:
        """POST a single inference span to ``/v1/spans``.

        Fire-and-forget: the method returns immediately after dispatching
        the request.  Any HTTP or network error is caught and logged.

        Args:
            span: A fully populated :class:`~axon.models.InferenceSpan`
                instance produced by the instrumentation layer.
        """
        try:
            payload = {"spans": [span.model_dump(mode="json")]}
            response = await self._client.post("/v1/spans", json=payload)
            if not response.is_success:
                _log.warning(
                    "axon.backend_client.send_span.http_error",
                    status_code=response.status_code,
                )
        except Exception as exc:
            _log.warning("axon.backend_client.send_span.error", error=str(exc))

    async def check_budget(self, feature_tag: str) -> BudgetStatus:
        """GET the current budget status for a feature tag.

        Fail open: returns :attr:`BudgetStatus.OK` on any error so that
        network or backend outages never block LLM calls.

        Args:
            feature_tag: The feature tag whose budget status to check.

        Returns:
            :class:`BudgetStatus` — ``OK``, ``WARNING``, or ``EXHAUSTED``.
        """
        try:
            response = await self._client.get(f"/v1/budgets/{feature_tag}")
            if response.is_success:
                data = response.json()
                status_str = data.get("status", "ok")
                return BudgetStatus(status_str)
            return BudgetStatus.OK
        except Exception as exc:
            _log.warning(
                "axon.backend_client.check_budget.error",
                feature_tag=feature_tag,
                error=str(exc),
            )
            return BudgetStatus.OK

    async def close(self) -> None:
        """Close the underlying ``httpx.AsyncClient`` and release connections.

        Should be called when the application shuts down.
        """
        await self._client.aclose()
