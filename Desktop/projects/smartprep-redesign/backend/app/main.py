"""
SmartPrep AI - Main FastAPI Application
"""
import logging
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.api import resume, questions, evaluation, session, agent, community, admin, code
from app.services.session_store import session_store
from app.utils.config import settings
from app.utils.logger import setup_logger
from app.utils.telemetry import telemetry

# Configure the root logger level from settings once at startup.
# Child loggers created via setup_logger() inherit this level.
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

logger = setup_logger(__name__)

_startup_time = time.time()

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    if not settings.GROQ_API_KEY or settings.GROQ_API_KEY == "your-groq-api-key-here":
        logger.error("FATAL: GROQ_API_KEY is not configured. Get a free key at console.groq.com")
        sys.exit(1)

    # Pre-load the embedding model so the first request isn't slow
    try:
        from app.services.rag_service import rag_service as _rag
        _rag.preload()
    except Exception as e:
        logger.error(f"Failed to load embedding model: {e}")
        sys.exit(1)

    # Apply Alembic migrations (ensures schema stays in sync with code)
    try:
        import subprocess, os as _os
        _alembic_cfg = _os.path.join(_os.path.dirname(__file__), "..", "alembic.ini")
        result = subprocess.run(
            ["python", "-m", "alembic", "upgrade", "head"],
            capture_output=True, text=True,
            cwd=_os.path.dirname(_alembic_cfg),
        )
        if result.returncode == 0:
            logger.info("Database migrations applied successfully")
        else:
            raise RuntimeError(result.stderr[:300])
    except Exception as e:
        logger.warning(f"Alembic failed ({e}), falling back to create_all")
        try:
            from app.db.database import init_db
            await init_db()
        except Exception as e2:
            logger.warning(f"DB init also failed (non-fatal for stateless mode): {e2}")


    session_store.start_cleanup_task()
    logger.info(f"SmartPrep AI started — model: {settings.GROQ_MODEL} (free via Groq)")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    session_store.stop_cleanup_task()
    logger.info("SmartPrep AI shut down cleanly")


app = FastAPI(
    title="SmartPrep AI v2",
    description="AI-powered interview preparation system with hybrid RAG, agentic evaluation, learner memory, and community question pool (powered by Groq)",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(resume.router, prefix="/api/v1", tags=["Resume"])
app.include_router(questions.router, prefix="/api/v1", tags=["Questions"])
app.include_router(evaluation.router, prefix="/api/v1", tags=["Evaluation"])
app.include_router(session.router, prefix="/api/v1", tags=["Session"])
app.include_router(agent.router, prefix="/api/v1", tags=["Agent"])
app.include_router(community.router, prefix="/api/v1", tags=["Community"])
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])
app.include_router(code.router, prefix="/api/v1", tags=["Code Execution"])


@app.get("/health", tags=["Health"])
async def health_check():
    """Root health check used by Render and external monitors."""
    from app.services.rag_service import rag_service
    return {
        "status": "healthy",
        "service": "SmartPrep AI",
        "version": "2.0.0",
        "uptime_seconds": round(time.time() - _startup_time),
        "embedding_model_loaded": rag_service._embedder is not None,
        "active_sessions": len(session_store._store),
        "hybrid_retrieval": True,
        "rubric_decomposition": True,
        "agentic_followups": True,
        "learner_memory": True,
        "community_questions": True,
        "telemetry": telemetry.get_summary(),
    }


@app.get("/api/v1/health", tags=["Health"])
async def api_health_check():
    """Versioned health check for API-level monitoring."""
    return {"status": "ok"}
