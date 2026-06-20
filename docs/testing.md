# Testing

This document covers how to run, extend, and interpret all tests across the Traject
monorepo: Python SDK, backend service, TypeScript SDK, and SWE-bench benchmarks.

---

## Contents

- [Prerequisites](#prerequisites)
- [Python SDK tests](#python-sdk-tests)
- [Backend tests](#backend-tests)
- [TypeScript SDK tests](#typescript-sdk-tests)
- [SWE-bench benchmarks](#swe-bench-benchmarks)
- [Performance benchmarks](#performance-benchmarks)
- [CI pipeline](#ci-pipeline)
- [Coverage targets](#coverage-targets)

---

## Prerequisites

```bash
# Python 3.11+
python --version

# Node 20+
node --version

# Clone and enter repo
git clone https://github.com/aarohim24/Traject
cd Traject
```

---

## Python SDK tests

### Setup

```bash
cd sdk/python
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev,openai,anthropic,langchain,ml]"
```

### Run all tests

```bash
pytest tests/
```

This runs unit + integration tests with coverage enforcement (80% minimum).

### Run unit tests only

```bash
pytest tests/unit/ --no-cov
```

### Run a specific test file

```bash
pytest tests/unit/test_compression_engine.py -v --no-cov
```

### Run with coverage report

```bash
pytest tests/ --cov=traject --cov-report=html
open htmlcov/index.html
```

### Run integration tests only

```bash
pytest tests/integration/ -v --no-cov
```

### Run property-based tests (Hypothesis)

Property-based tests are included in the unit suite and run automatically. To run
Hypothesis tests in verbose mode:

```bash
pytest tests/unit/ -v -k "hypothesis or property" --hypothesis-show-statistics
```

Key properties tested:
- `MLRouter.route()` never raises for any valid input
- `ConformalPredictor` empirical coverage ≥ `1 - alpha` on calibration set
- `CostPredictor` maintains `lower_bound ≤ point_estimate ≤ upper_bound`
- `extract_trace_context()` never raises on arbitrary string input
- `estimate_complexity()` always returns a value in `[0.0, 1.0]`

### Lint and type checks

```bash
# Lint
ruff check traject tests

# Format check
ruff format --check traject tests

# Type check (strict)
mypy traject --strict
```

### Test file conventions

Each source file has a corresponding test file:

| Source | Test |
|---|---|
| `traject/compression/engine.py` | `tests/unit/test_compression_engine.py` |
| `traject/router/rule_router.py` | `tests/unit/test_rule_router.py` |
| `traject/advisor/prompt_cache_advisor.py` | `tests/unit/test_prompt_cache_advisor.py` |
| `traject/core/instrumentor.py` | `tests/unit/test_instrumentor.py` |

All HTTP calls to OpenAI and Anthropic are mocked at the transport layer using `respx`.
No live API calls are made during testing.

---

## Backend tests

The backend tests require PostgreSQL 16 (with pgvector) and Redis 7. The easiest
path is Docker Compose.

### Setup

```bash
# Start PostgreSQL + Redis
docker compose -f deploy/docker-compose.yml up postgres redis -d

# Install SDK first (backend depends on it)
pip install -e "sdk/python[dev,ml]" -q

# Install backend
cd backend
pip install -e ".[dev]"

# Run migrations
DATABASE_URL=postgresql+asyncpg://traject:traject@localhost:5432/traject \
  alembic upgrade head
```

### Run all backend tests

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://traject:traject@localhost:5432/traject \
REDIS_URL=redis://localhost:6379/0 \
  pytest tests/ -v
```

### Run unit tests only (no DB/Redis required)

Unit tests mock the database session using `AsyncMock` and fakeredis:

```bash
cd backend
pytest tests/unit/ -v
```

### Run integration tests

Integration tests require live PostgreSQL and Redis:

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://traject:traject@localhost:5432/traject \
REDIS_URL=redis://localhost:6379/0 \
  pytest tests/integration/ -v --no-cov
```

---

## TypeScript SDK tests

### Setup

```bash
cd sdk/typescript
npm install
```

### Run all tests

```bash
npm test
```

### Run with coverage

```bash
npm test -- --coverage
```

### Type check

```bash
npm run typecheck
```

### Lint

```bash
npm run lint
```

Test files use Jest with mocked `fetch` for backend HTTP calls. No live network
calls are made.

---

## SWE-bench benchmarks

These scripts measure compression quality on real agent trajectories from
[SWE-Gym/OpenHands-SFT-Trajectories](https://huggingface.co/datasets/SWE-Gym/SWE-Gym)
(HuggingFace, public). They are not part of the CI test suite — run them locally.

### Setup

```bash
cd sdk/python
source .venv/bin/activate
pip install -e ".[dev]"

# Download trajectory data (requires HuggingFace account for higher rate limits)
# export HF_TOKEN=hf_...   # optional but recommended
python -c "
from datasets import load_dataset
ds = load_dataset('SWE-Gym/SWE-Gym', split='train', streaming=True)
import json
with open('swebench_trajectories.jsonl', 'w') as f:
    for i, row in enumerate(ds):
        if i >= 49: break
        f.write(json.dumps(row) + '\n')
"
```

### Token reduction measurement

```bash
python examples/benchmark/swebench_eval.py \
  --input swebench_trajectories.jsonl \
  --n-instances 49 \
  --strategy conservative \
  --output-json swebench_results.json
```

### Information retention measurement

```bash
python examples/benchmark/quality_eval.py \
  --input swebench_trajectories.jsonl \
  --output-json quality_results.json
```

### Published v2 results (CONSERVATIVE strategy, 49 instances)

| Metric | Result |
|---|---|
| Aggregate token reduction | 24.0% |
| Mean reduction | 25.3% |
| p50 reduction | 25.0% |
| Information retention | 94.7% |
| p10 retention (worst 10%) | 96.0% |

Results are written to JSON for further analysis. The trajectory files are gitignored
(large dataset files) — each run regenerates them locally.

---

## Performance benchmarks

These assert SDK overhead and compression latency stay within acceptable bounds.
They run automatically in CI.

### SDK overhead

Measures end-to-end instrumentation overhead on a mock LLM call:

```bash
cd sdk/python
python tests/benchmarks/bench_sdk_overhead.py --assert-median-ms 10
```

Target: p50 overhead ≤ 10ms.

### Compression latency

Measures the compression pipeline on a 20-segment trajectory:

```bash
cd sdk/python
python tests/benchmarks/bench_compression_latency.py --assert-median-ms 50
```

Target: p50 latency ≤ 50ms on CPU (no GPU required).

---

## CI pipeline

Every push and pull request runs five jobs in parallel:

| Job | What it checks |
|---|---|
| `lint` | `ruff check` + `ruff format --check` on SDK source and tests |
| `type-check` | `mypy --strict` on `traject/` |
| `test` | Full pytest suite, 80% coverage minimum, coverage uploaded to Codecov |
| `benchmark` | SDK overhead ≤ 5ms p50, compression latency ≤ 50ms p50 |
| `backend-test` | Backend pytest suite against live PostgreSQL + Redis, 75% coverage minimum |
| `typescript-test` | `tsc --noEmit`, `eslint`, Jest with coverage |

All jobs must pass before a PR can be merged. See
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) for the full configuration.

---

## Coverage targets

| Component | Minimum | Enforced by |
|---|---|---|
| Python SDK (`traject/`) | 80% | `pytest --cov-fail-under=80` |
| Compression engine (`engine.py`) | 90% | Manual review + CI |
| Backend (`traject_backend/`) | 75% | `pytest --cov-fail-under=75` |
| TypeScript SDK | 80% | Jest `--coverage` |
