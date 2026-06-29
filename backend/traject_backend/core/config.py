"""Application configuration for the Traject backend service.

Reads all settings from environment variables with sensible local defaults.
Override any value by setting the corresponding environment variable or by
providing a ``.env`` file in the working directory.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised runtime configuration for traject-backend.

    All fields map directly to environment variables of the same name
    (case-insensitive). A ``.env`` file is loaded automatically when
    present; unknown variables in that file are silently ignored.

    Attributes:
        database_url: Async SQLAlchemy connection URL for PostgreSQL.
        database_pool_size: Number of persistent connections in the pool.
        database_max_overflow: Extra connections allowed above pool_size.
        redis_url: Redis connection URL (redis://host:port/db).
        redis_cache_ttl_seconds: Default TTL for Redis-cached values.
        api_host: Host address the Uvicorn server binds to.
        api_port: Port the Uvicorn server listens on.
        api_workers: Number of Uvicorn worker processes.
        cors_origins: List of origins allowed by the CORS middleware.
        api_key_header: HTTP header name used to pass the API key.
        api_key: Secret value required in the API key header.
        cache_similarity_threshold: Minimum cosine similarity for a cache hit.
        cache_max_entries: Maximum number of entries kept in the cache table.
        budget_alert_webhook_timeout_seconds: HTTP timeout for webhook POSTs.
    """

    # Database
    database_url: str = "postgresql+asyncpg://traject:traject@localhost:5432/traject"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl_seconds: int = 86400  # 24 hours

    # API server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 2
    cors_origins: list[str] = ["http://localhost:3000"]

    # Security
    api_key_header: str = "X-Traject-API-Key"
    api_key: str = "dev-key-change-in-production"
    # When False (default), the backend refuses to start if api_key is still the
    # well-known default. Set ALLOW_INSECURE_API_KEY=true for local dev / tests.
    allow_insecure_api_key: bool = False

    # Semantic cache
    cache_similarity_threshold: float = 0.92
    cache_max_entries: int = 100_000

    # Budget alerts
    budget_alert_webhook_timeout_seconds: int = 10

    # Background scheduler. Set RUN_SCHEDULER=false on web workers and run a
    # single dedicated scheduler process to avoid every Uvicorn worker firing
    # every job (audit H11). Jobs additionally take a Redis lock as a backstop.
    run_scheduler: bool = True
    # Retention: inference_spans older than this are pruned by the retention job
    # (audit H10). History is preserved in the cost_attribution rollup.
    span_retention_days: int = 90

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings: Settings = Settings()