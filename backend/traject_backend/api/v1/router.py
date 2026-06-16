"""Aggregator router for all v1 API endpoints.

Includes the spans, attribution, budgets, cache, predictions, and benchmarks
sub-routers so that ``main.py`` can mount the entire v1 API with a single
``include_router`` call.
"""

from __future__ import annotations

from fastapi import APIRouter

from axon_backend.api.v1 import attribution, budgets, cache, spans
from axon_backend.api.v1.benchmarks import benchmarks_router
from axon_backend.api.v1.predictions import predictions_router

router = APIRouter()

router.include_router(spans.router)
router.include_router(attribution.router)
router.include_router(budgets.router)
router.include_router(cache.router)
router.include_router(predictions_router, prefix="/predictions", tags=["predictions"])
router.include_router(benchmarks_router, prefix="/benchmarks")
