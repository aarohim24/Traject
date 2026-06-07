FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY axon_backend/ axon_backend/
COPY migrations/ migrations/
COPY alembic.ini .

# Install CPU-only torch first to avoid pulling CUDA/NVIDIA packages (2 GB+).
# sentence-transformers only needs CPU inference for embedding generation.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install the backend package (non-editable — -e is for development only).
RUN pip install --no-cache-dir .

CMD ["sh", "-c", "alembic upgrade head && uvicorn axon_backend.main:app --host 0.0.0.0 --port 8000 --workers 2"]
