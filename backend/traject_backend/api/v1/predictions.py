"""Cost prediction API endpoint.

Provides ``POST /v1/predictions/cost`` for computing point estimates and
90% prediction intervals for planned LLM API calls.  Requires ``engineer``
role authentication (``require_role("engineer")``).
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.core.auth import CurrentTenant
from traject_backend.core.database import get_db
from traject_backend.services.cost_predictor import CostPredictor

_log = structlog.get_logger(__name__)

predictions_router = APIRouter(tags=["predictions"])


class CostPredictionRequest(BaseModel):
    """Request body for ``POST /v1/predictions/cost``.

    Attributes:
        feature_tag: Cost-attribution label for the planned call.
        model: Model identifier string (e.g. ``"gpt-4o"``).
        estimated_input_tokens: Estimated number of input/prompt tokens.
        estimated_output_tokens: Estimated number of output/completion tokens.
    """

    feature_tag: str
    model: str
    estimated_input_tokens: int
    estimated_output_tokens: int


class CostPredictionResponse(BaseModel):
    """Response from ``POST /v1/predictions/cost``.

    All ``Decimal`` monetary values are serialized as strings to preserve
    precision (ADR-006).

    Attributes:
        point_estimate_usd: Point estimate in USD, serialized as a string.
        lower_bound_usd: Lower bound of the prediction interval, as a string.
        upper_bound_usd: Upper bound of the prediction interval, as a string.
        prediction_interval_pct: Coverage percentage of the interval (90).
        model: Model identifier echoed from the request.
        feature_tag: Feature tag echoed from the request.
        sample_count: Number of historical rows used to compute the interval.
    """

    point_estimate_usd: str
    lower_bound_usd: str
    upper_bound_usd: str
    prediction_interval_pct: int = 90
    model: str
    feature_tag: str
    sample_count: int


@predictions_router.post(
    "/cost",
    response_model=CostPredictionResponse,
)
async def predict_cost(
    request: CostPredictionRequest,
    tenant_id: CurrentTenant,
    db: AsyncSession = Depends(get_db),
) -> CostPredictionResponse:
    """Compute a point estimate and 90% prediction interval for a planned LLM call.

    Args:
        request: Prediction request with model, token estimates, and feature tag.
        db: Injected async database session.

    Returns:
        ``CostPredictionResponse`` with point estimate and interval bounds.

    Raises:
        HTTPException: 422 when ``estimated_input_tokens`` or
            ``estimated_output_tokens`` is negative.
        HTTPException: 404 when the requested model is not in the pricing table.
    """
    if request.estimated_input_tokens < 0 or request.estimated_output_tokens < 0:
        raise HTTPException(
            status_code=422,
            detail=(
                "estimated_input_tokens and estimated_output_tokens "
                "must be non-negative integers"
            ),
        )

    predictor = CostPredictor()

    try:
        point_estimate: Decimal = predictor.compute_point_estimate(
            model=request.model,
            estimated_input_tokens=request.estimated_input_tokens,
            estimated_output_tokens=request.estimated_output_tokens,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{request.model}' not found in pricing table",
        ) from exc

    lower_bound, upper_bound, sample_count = await predictor.predict_interval(
        db=db,
        model=request.model,
        point_estimate=point_estimate,
        estimated_input_tokens=request.estimated_input_tokens,
        estimated_output_tokens=request.estimated_output_tokens,
        tenant_id=tenant_id,
    )

    _log.info(
        "traject.predictions.cost",
        model=request.model,
        feature_tag=request.feature_tag,
        point_estimate=str(point_estimate),
        sample_count=sample_count,
    )

    return CostPredictionResponse(
        point_estimate_usd=str(point_estimate),
        lower_bound_usd=str(lower_bound),
        upper_bound_usd=str(upper_bound),
        prediction_interval_pct=90,
        model=request.model,
        feature_tag=request.feature_tag,
        sample_count=sample_count,
    )
