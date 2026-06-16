# ML Router Guide

Traject's Phase 5 router adds a machine-learning layer on top of the existing
rule-based router.  The `MLRouter` trains a logistic regression model on
historical routing decisions and progressively improves routing accuracy as
more data accumulates.  When insufficient data exists, it falls back
transparently to the `RuleRouter`.

---

## How It Works

### MLRouter

`MLRouter` wraps `RuleRouter` and adds a scikit-learn logistic regression
classifier trained on historical `InferenceSpanRecord` rows.

**Fallback behaviour (< 500 examples):**
When fewer than 500 labeled routing examples exist in the database, `MLRouter`
delegates all decisions to the injected `RuleRouter` and logs an info event:

```
{"event": "ml_router.fallback", "reason": "insufficient_training_data", "sample_count": 42}
```

**ML mode (≥ 500 examples):**
Once 500 or more labeled examples are available, the trained logistic
regression model overrides the rule-based decision.  Routing decisions made
by the ML model have `routing_rule` prefixed with `"ml."` — e.g.
`"ml.tier_selection"`.

### ConformalRouter

`ConformalRouter` wraps any router (including `MLRouter`) and adds a
statistical quality guarantee calibrated via split conformal prediction.

For a configured miscoverage rate `alpha`, the guarantee is:

```
P(quality >= threshold) >= 1 - alpha
```

This holds in the marginal (average) sense over the calibration distribution.
The default `alpha` is `0.1` (90% coverage).

If the conformal predictor is not yet calibrated, `ConformalRouter` delegates
directly to the inner router and logs a warning.

---

## Quick Start

```python
from traject.router.ml_router import MLRouter
from traject.router.rule_router import RuleRouter
from traject.router.conformal import ConformalRouter

# Create ML router (falls back to rules until 500 examples exist)
rule_router = RuleRouter()
ml_router = MLRouter(
    fallback_router=rule_router,
    model_artifact_path=".traject/ml_model.pkl",  # optional pre-trained artifact
)

# Wrap with conformal prediction for quality guarantees
router = ConformalRouter(inner_router=ml_router, alpha=0.1)

# Use with Traject instrumentation
import traject
traject.configure(router=router)
```

---

## Training the ML Router

Training is handled automatically by a weekly scheduled job on the backend.
You can also trigger training manually:

```python
import asyncio
from traject_backend.services.ml_training import MLTrainingService
from traject_backend.core.database import get_db

async def train():
    async with get_db() as db:
        service = MLTrainingService()
        artifact = await service.train(db)
        print(f"Trained on {artifact.sample_count} examples")

asyncio.run(train())
```

The weekly job runs every Sunday at 01:00 UTC
(`trigger="cron", day_of_week="sun", hour=1, minute=0`).

---

## Calibrating the Conformal Predictor

Before the `ConformalRouter` can provide quality guarantees, you must calibrate
the `ConformalPredictor` with a held-out calibration set:

```python
from traject.router.conformal import ConformalPredictor
import numpy as np

predictor = ConformalPredictor(quality_threshold=0.85)

# calibration_data: list of (feature_vector, observed_quality_score) pairs
calibration_data = [
    (np.array([0.1, 0.9, 0.5]), 0.91),
    (np.array([0.8, 0.2, 0.3]), 0.72),
    # ... more examples
]

predictor.calibrate(calibration_data, alpha=0.1)
print(f"Calibrated q_hat: {predictor.q_hat:.4f}")
```

---

## Feature Engineering

`MLRouter` extracts the following features from each routing request:

| Feature | Description |
|---|---|
| `message_count` | Number of messages in the context |
| `total_tokens_estimate` | Estimated token count |
| `has_system_prompt` | Boolean flag |
| `last_role` | Role of the final message (`user` / `assistant` / `tool`) |
| `requested_tier` | Numeric encoding of the requested model tier |

Custom features can be injected via the plugin system — see
[plugin-development.md](plugin-development.md).

---

## Installing the ML Extra

The ML router requires scikit-learn, which is an optional dependency:

```bash
pip install "traject-sdk[ml]"
```

If scikit-learn is not installed and `MLRouter` is instantiated, you will
receive an `TrajectDependencyError` with installation instructions.

---

## Monitoring

The ML router emits structlog events and OTEL span attributes:

| Attribute | Value |
|---|---|
| `traject.router.type` | `"ml"` or `"rule"` (fallback) |
| `traject.router.routing_rule` | e.g. `"ml.tier_selection"` |
| `traject.conformal.covered` | `true` / `false` |
| `traject.conformal.q_hat` | Calibrated quantile threshold |
| `traject.conformal.predicted_quality_lb` | Lower bound on predicted quality |

---

## See Also

- [batch-routing.md](batch-routing.md) — batch API cost reduction
- [provider-expansion.md](provider-expansion.md) — Bedrock and Vertex adapters
- [plugin-development.md](plugin-development.md) — custom router plugins
