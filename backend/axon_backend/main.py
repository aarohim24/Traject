"""Axon Backend — FastAPI application entry point.

Defines the FastAPI application instance. The full lifespan, middleware stack,
and route registration are wired up in task 15.
"""

from fastapi import FastAPI

app = FastAPI(
    title="Axon Backend",
    version="0.2.0",
)
