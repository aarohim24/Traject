"""Batch routing for the Traject SDK.

Routes batch-eligible :class:`~traject.models.InferenceSpan` objects to
provider batch APIs — OpenAI Batch API (``POST /v1/batches``) and Anthropic
Message Batches (``POST /v1/messages/batches``).  Non-eligible spans are
filtered out before submission.  All public methods are non-raising: errors
are logged via structlog and expressed as a :class:`BatchJobRecord` with
``status=FAILED``.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

from traject.models import InferenceSpan

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# BatchJobStatus
# ---------------------------------------------------------------------------


class BatchJobStatus(StrEnum):
    """Lifecycle states for a provider batch API job.

    Values mirror the status strings returned by both the OpenAI Batch API
    and the Anthropic Message Batches API, with ``EXPIRED`` added to cover
    jobs that exceeded the provider's 24-hour processing window.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# BatchJobRecord
# ---------------------------------------------------------------------------


@dataclass
class BatchJobRecord:
    """Record of a submitted batch API job.

    Attributes:
        job_id: Provider-assigned batch job identifier.
        provider: ``"openai"`` or ``"anthropic"``.
        status: Current :class:`BatchJobStatus` value stored as a string.
        submitted_at: UTC timestamp of submission.
        span_count: Number of spans included in this batch.
        estimated_completion_at: Provider's estimated completion time, or
            ``None`` when the provider does not supply an estimate.
    """

    job_id: str
    provider: str
    status: str
    submitted_at: datetime
    span_count: int
    estimated_completion_at: datetime | None


# ---------------------------------------------------------------------------
# BatchRouter
# ---------------------------------------------------------------------------


class BatchRouter:
    """Routes batch-eligible spans to provider batch APIs.

    Dispatches filtered spans to the appropriate provider batch endpoint:

    - ``provider == "openai"`` → ``POST /v1/batches``
    - ``provider == "anthropic"`` → ``POST /v1/messages/batches``

    This class **never raises**.  Any exception during submission is caught,
    logged via structlog, and expressed as a :class:`BatchJobRecord` with
    ``status=FAILED``.

    Args:
        openai_client: Optional pre-configured ``openai.AsyncOpenAI``
            instance.  When ``None``, OpenAI batch submission will fail
            gracefully with a ``FAILED`` record.
        anthropic_client: Optional pre-configured
            ``anthropic.AsyncAnthropic`` instance.  When ``None``, Anthropic
            batch submission will fail gracefully with a ``FAILED`` record.
    """

    def __init__(
        self,
        openai_client: Any = None,  # Any: openai.AsyncOpenAI — optional dep
        anthropic_client: Any = None,  # Any: anthropic.AsyncAnthropic — optional dep
    ) -> None:
        """Initialise the BatchRouter with optional provider clients.

        Args:
            openai_client: Pre-configured ``openai.AsyncOpenAI`` instance,
                or ``None`` to disable OpenAI batch submission.
            anthropic_client: Pre-configured ``anthropic.AsyncAnthropic``
                instance, or ``None`` to disable Anthropic batch submission.
        """
        self._openai_client = openai_client
        self._anthropic_client = anthropic_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit_batch(
        self,
        spans: list[InferenceSpan],
        provider: str,
    ) -> BatchJobRecord:
        """Submit batch-eligible spans to the named provider batch API.

        Spans with ``batch_eligible=False`` are filtered out silently before
        the API call.  If the resulting eligible set is empty, a ``FAILED``
        record is returned without making any network request.

        On any API exception the error is logged at ``error`` level via
        structlog and a :class:`BatchJobRecord` with ``status=FAILED`` is
        returned.  This method **never raises**.

        Args:
            spans: Candidate spans to include in the batch.  Non-eligible
                spans (``batch_eligible=False``) are filtered out.
            provider: Target provider — ``"openai"`` or ``"anthropic"``.

        Returns:
            A :class:`BatchJobRecord` representing the submitted (or failed)
            batch job.
        """
        try:
            eligible = [s for s in spans if s.batch_eligible]
            if not eligible:
                _log.warning(
                    "traject.batch.submit_skipped",
                    reason="no_eligible_spans",
                    provider=provider,
                    total_spans=len(spans),
                )
                return self._failed_record(provider=provider, span_count=0)

            if provider == "openai":
                return await self._submit_openai(eligible)
            if provider == "anthropic":
                return await self._submit_anthropic(eligible)

            _log.error(
                "traject.batch.unknown_provider",
                provider=provider,
            )
            return self._failed_record(provider=provider, span_count=len(eligible))

        except Exception as exc:
            _log.error(
                "traject.batch.submit_failed",
                provider=provider,
                error=str(exc),
                exc_info=exc,
            )
            return self._failed_record(provider=provider, span_count=len(spans))

    async def poll_and_collect(
        self,
        db: AsyncSession,
        provider_client: Any,  # Any: provider-specific client type
    ) -> int:
        """Poll all PENDING/IN_PROGRESS jobs and update their status.

        This is a stub implementation.  The full implementation is provided
        after :mod:`traject.batch.job_tracker` is available (task 19).

        Args:
            db: An async SQLAlchemy session used by the
                :class:`~traject.batch.job_tracker.JobTracker` to query and
                update job records.
            provider_client: Provider-specific client used to poll job status
                (e.g. ``openai.AsyncOpenAI`` or
                ``anthropic.AsyncAnthropic``).

        Returns:
            Count of newly :attr:`BatchJobStatus.COMPLETED` jobs (always
            ``0`` in this stub).
        """
        try:
            return 0
        except Exception as exc:
            _log.error(
                "traject.batch.poll_failed",
                error=str(exc),
                exc_info=exc,
            )
            return 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _submit_openai(
        self,
        spans: list[InferenceSpan],
    ) -> BatchJobRecord:
        """Submit eligible spans to the OpenAI Batch API.

        Builds a JSONL payload where each line is a chat completion request
        derived from a single span, then calls ``POST /v1/batches`` via the
        injected client.

        Args:
            spans: Pre-filtered list of batch-eligible spans.

        Returns:
            A :class:`BatchJobRecord` with the provider-assigned ``job_id``
            and initial status from the API response.

        Raises:
            Exception: Any exception from the provider client; callers
                should handle via the outer ``submit_batch`` try/except.
        """
        if self._openai_client is None:
            raise RuntimeError(
                "openai_client is required for OpenAI batch submission. "
                "Pass an openai.AsyncOpenAI instance to BatchRouter.__init__."
            )

        # Build JSONL content — one completion request per span.
        lines: list[str] = []
        for span in spans:
            request: dict[str, Any] = {  # Any: OpenAI request body values vary
                "custom_id": str(span.id),
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": span.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"[batch span {span.id}]",
                        }
                    ],
                },
            }
            lines.append(json.dumps(request))

        jsonl_content = "\n".join(lines)

        # Upload the JSONL file, then create the batch.
        file_obj: Any = (  # Any: openai.FileObject
            await self._openai_client.files.create(
                file=(
                    "batch_input.jsonl",
                    jsonl_content.encode(),
                    "application/jsonl",
                ),
                purpose="batch",
            )
        )

        batch_obj: Any = await self._openai_client.batches.create(  # Any: openai.Batch
            input_file_id=file_obj.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )

        estimated: datetime | None = None
        if hasattr(batch_obj, "expires_at") and batch_obj.expires_at is not None:
            estimated = datetime.fromtimestamp(float(batch_obj.expires_at), tz=UTC)

        return BatchJobRecord(
            job_id=batch_obj.id,
            provider="openai",
            status=BatchJobStatus.PENDING,
            submitted_at=datetime.now(tz=UTC),
            span_count=len(spans),
            estimated_completion_at=estimated,
        )

    async def _submit_anthropic(
        self,
        spans: list[InferenceSpan],
    ) -> BatchJobRecord:
        """Submit eligible spans to the Anthropic Message Batches API.

        Builds a list of ``MessageBatchRequest`` objects (one per span) and
        calls ``POST /v1/messages/batches`` via the injected client.

        Args:
            spans: Pre-filtered list of batch-eligible spans.

        Returns:
            A :class:`BatchJobRecord` with the provider-assigned ``job_id``
            and initial status from the API response.

        Raises:
            Exception: Any exception from the provider client; callers
                should handle via the outer ``submit_batch`` try/except.
        """
        if self._anthropic_client is None:
            raise RuntimeError(
                "anthropic_client is required for Anthropic batch submission. "
                "Pass an anthropic.AsyncAnthropic instance to BatchRouter.__init__."
            )

        requests: list[dict[str, Any]] = [  # Any: Anthropic request body values vary
            {
                "custom_id": str(span.id),
                "params": {
                    "model": span.model,
                    "max_tokens": 1024,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"[batch span {span.id}]",
                        }
                    ],
                },
            }
            for span in spans
        ]

        batch_obj: Any = (  # Any: anthropic.MessageBatch
            await self._anthropic_client.messages.batches.create(
                requests=requests,
            )
        )

        estimated: datetime | None = None
        if (
            hasattr(batch_obj, "request_counts")
            and hasattr(batch_obj, "ends_at")
            and batch_obj.ends_at is not None
        ):
            with contextlib.suppress(ValueError, TypeError):
                estimated = datetime.fromisoformat(str(batch_obj.ends_at))

        return BatchJobRecord(
            job_id=batch_obj.id,
            provider="anthropic",
            status=BatchJobStatus.PENDING,
            submitted_at=datetime.now(tz=UTC),
            span_count=len(spans),
            estimated_completion_at=estimated,
        )

    @staticmethod
    def _failed_record(
        provider: str,
        span_count: int,
    ) -> BatchJobRecord:
        """Construct a :class:`BatchJobRecord` representing a failed submission.

        Args:
            provider: Provider name for the record.
            span_count: Number of spans that were intended for submission.

        Returns:
            A :class:`BatchJobRecord` with ``status=FAILED`` and a
            synthetic ``job_id``.
        """
        return BatchJobRecord(
            job_id=f"failed-{uuid.uuid4()}",
            provider=provider,
            status=BatchJobStatus.FAILED,
            submitted_at=datetime.now(tz=UTC),
            span_count=span_count,
            estimated_completion_at=None,
        )
