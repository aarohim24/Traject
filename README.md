# Axon

[![PyPI](https://img.shields.io/pypi/v/axon-sdk)](https://pypi.org/project/axon-sdk/)
[![CI](https://github.com/aarohimathur/axon/actions/workflows/ci.yml/badge.svg)](https://github.com/aarohimathur/axon/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Axon is a Python SDK and self-hosted platform that makes AI inference
observable, controllable, and economically efficient. It instruments LLM
calls in real time, compresses agentic context trajectories, and emits
structured OpenTelemetry spans for cost attribution.

---

## Docker Compose Quickstart

Get the full Axon platform running locally in under five minutes.

**Prerequisites:** Docker Desktop (or Docker Engine + Compose plugin)

### Step 1 — Start all services

```bash
docker compose -f deploy/docker-compose.yml up -d
```

This starts four services:
- **postgres** — PostgreSQL 16 with pgvector at `localhost:5432`
- **redis** — Redis 7 at `localhost:6379`
- **axon-backend** — FastAPI backend at `http://localhost:8000`
- **grafana** — Grafana 10.4 dashboards at `http://localhost:3000`

### Step 2 — Verify the backend is healthy

```bash
curl http://localhost:8000/health
# → {"status":"ok","version":"0.2.0"}

curl http://localhost:8000/health/db
# → {"status":"ok"}

curl http://localhost:8000/health/redis
# → {"status":"ok"}
```

All three checks should return `{"status":"ok"}` within 60 seconds of startup.

### Step 3 — Open Grafana

Navigate to **http://localhost:3000** in your browser.

Default credentials: `admin` / `admin` (configurable via `GRAFANA_PASSWORD` in `deploy/.env.example`).

You will find three pre-provisioned dashboards under the **Axon** folder:
- **Cost Overview** — total spend by feature tag, model, and provider
- **Compression ROI** — tokens saved and cost reduction from trajectory compression
- **Budget Burn Rate** — budget utilisation gauges and burn-rate time series

### Step 4 — Send a test span

```bash
curl -s -X POST http://localhost:8000/v1/spans \
  -H "Content-Type: application/json" \
  -H "X-Axon-API-Key: dev-key-change-in-production" \
  -d '{"spans": [{"timestamp": "2025-01-01T00:00:00Z", "provider": "openai",
       "model": "gpt-4o", "input_tokens": 100, "output_tokens": 50,
       "feature_tag": "demo", "prompt_hash": "'"$(python3 -c 'import hashlib; print(hashlib.sha256(b"demo").hexdigest())')"'",
       "duration_ms": 150, "token_count_method": "exact", "environment": "dev"}]}'
# → {"accepted":1,"rejected":0}
```

### Step 5 — Clean up

```bash
docker compose -f deploy/docker-compose.yml down -v
```

The `-v` flag removes the named volumes (postgres_data, redis_data, grafana_data).
Omit it to keep your data across restarts.

---

## SDK Quick Start (Phase 1)

```python
import axon

# Instrument any LLM-calling function
@axon.instrument(feature_tag="support-bot", shadow_mode=True)
def call_llm(messages):
    return openai_client.chat.completions.create(
        model="gpt-4o", messages=messages
    )

# Or patch an existing client in-place
axon.patch(openai_client, feature_tag="support-bot")

# Connect to the backend (Phase 2)
axon.configure(
    backend_url="http://localhost:8000",
    backend_api_key="dev-key-change-in-production",
)
```

See [`docs/quickstart.md`](docs/quickstart.md) for the full SDK guide.

---

## Configuration

All backend settings are controlled by environment variables.
Copy `deploy/.env.example` to `deploy/.env` and adjust as needed.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://axon:axon@localhost:5432/axon` | PostgreSQL connection URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `API_KEY` | `dev-key-change-in-production` | **Change this in production** |
| `CACHE_SIMILARITY_THRESHOLD` | `0.92` | Minimum cosine similarity for a cache hit |
| `GRAFANA_PASSWORD` | `admin` | Grafana admin password |

---

## Development

```bash
# Phase 1 SDK
cd sdk/python
pip install -e ".[dev]"
pytest --cov=axon --cov-fail-under=80

# Phase 2 Backend
cd backend
pip install -e ".[dev]"
pytest tests/ --cov=axon_backend --cov-fail-under=75
```

## License

MIT — see [LICENSE](LICENSE).
