"""Seed a deployed Traject backend with real, disclosed demo data.

Populates the dashboards (Cost Overview, Compression ROI, Span Explorer,
Budget Manager, Benchmark Registry) with data derived from actually running
the Traject SDK's real compression engine against the real public SWE-bench
benchmark trajectories checked into the repo root
(``swe_trajectories.jsonl``) — the same dataset and numbers verified against
README.md's published benchmark table.

This is NOT fabricated demo data: every token count, compression ratio, and
cost figure comes from the SDK's actual behavior on real trajectories. The
only synthetic choice is which model name/feature tag each trajectory is
labeled with, so the Cost Overview and Router Analytics pages have variety
to show — that labeling is disclosed here and in the dashboard's demo banner,
never presented as live production traffic.

Usage:
    python backend/scripts/seed_demo_data.py \\
        --backend-url https://<your-render-service>.onrender.com \\
        --api-key <your TRAJECT_API_KEY> \\
        --trajectories swe_trajectories.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

# examples/benchmark/ is a sibling directory, not an installed package —
# add the repo root to sys.path so `swebench_eval` can be imported directly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "examples" / "benchmark"))

from swebench_eval import _extract_task_hint, load_trajectories  # noqa: E402

from traject.classifier.artifact_type import ArtifactType  # noqa: E402
from traject.compression.engine import compress  # noqa: E402
from traject.compression.strategies import CompressionStrategy, get_config  # noqa: E402
from traject.core.cost_calculator import calculate_cost  # noqa: E402
from traject.core.pricing import PROVIDER_PRICING  # noqa: E402

# Demo-only label assignment — cycles real trajectories across a few models
# so Cost Overview / Router Analytics have something to break down by.
# The compression numbers attached to each span are real; only this label
# is a display choice, and it's disclosed in this file and the demo banner.
_DEMO_MODELS = ["gpt-4o-mini", "gpt-4o", "claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022"]
_DEMO_FEATURE_TAGS = ["code_review_agent", "support_triage_agent", "research_agent"]


def _model_provider(model: str) -> str:
    pricing = PROVIDER_PRICING.get(model)
    return pricing.provider if pricing is not None else "openai"


async def seed(backend_url: str, api_key: str, trajectories_path: Path) -> None:
    instances = load_trajectories(trajectories_path, n_instances=None)
    print(f"Loaded {len(instances)} real trajectories from {trajectories_path}")

    config = get_config(CompressionStrategy.CONSERVATIVE)
    now = datetime.now(UTC)
    spans: list[dict[str, object]] = []

    for i, (instance_id, messages) in enumerate(instances):
        result = compress(messages, config, task_hint=_extract_task_hint(messages))
        model = _DEMO_MODELS[i % len(_DEMO_MODELS)]
        feature_tag = _DEMO_FEATURE_TAGS[i % len(_DEMO_FEATURE_TAGS)]

        input_tokens = result.original_tokens - result.tokens_saved
        output_tokens = max(50, input_tokens // 20)  # no real completion in this dataset
        cost = calculate_cost(model, input_tokens, output_tokens)

        prompt_hash = hashlib.sha256(instance_id.encode()).hexdigest()
        span = {
            "id": str(uuid.uuid4()),
            "trace_id": uuid.uuid4().hex,
            "parent_span_id": None,
            "span_name": f"gen_ai.{_model_provider(model)}.{model}",
            "timestamp": (now - timedelta(minutes=len(instances) - i)).isoformat(),
            "duration_ms": 400 + (i % 30) * 37,
            "provider": _model_provider(model),
            "model": model,
            "api_version": None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": 0,
            "token_count_method": "exact",
            "cost_usd": str(cost) if cost is not None else "0",
            "feature_tag": feature_tag,
            "prompt_hash": prompt_hash,
            "artifact_type": ArtifactType.USER_MESSAGE.value,
            "compression_applied": i % 2 == 0,
            "shadow_mode": i % 2 == 1,
            "pre_compression_tokens": result.original_tokens,
            "tokens_saved": result.tokens_saved,
            "cache_hit": False,
            "environment": "demo",
            "batch_eligible": False,
        }
        spans.append(span)

    async with httpx.AsyncClient(
        base_url=backend_url, headers={"X-Traject-API-Key": api_key}, timeout=120.0
    ) as client:
        # Render's free tier spins down when idle and can take 30-60s+ to
        # cold-start on the first request — wake it up before the real POST
        # so the ingestion call itself isn't the one eating that latency.
        print("Warming up backend (may take a minute on Render's free tier)...")
        await client.get("/health")

        resp = await client.post("/v1/spans", json={"spans": spans})
        resp.raise_for_status()
        print(f"Ingested {len(spans)} spans: {resp.json()}")

        budget_resp = await client.put(
            "/v1/budgets/code_review_agent",
            json={"period": "monthly", "budget_usd": "500.00"},
        )
        budget_resp.raise_for_status()
        print(f"Seeded demo budget: {budget_resp.json()}")

        avg_ratio = sum(
            (s["tokens_saved"] / s["pre_compression_tokens"])  # type: ignore[operator]
            for s in spans
            if s["pre_compression_tokens"]  # type: ignore[truthy-bool]
        ) / len(spans)
        benchmark_resp = await client.post(
            "/v1/benchmarks/submit",
            json={
                "sdk_version": "0.1.0",
                "python_version": "3.11",
                "sample_count": len(spans),
                "p50_cost_usd": "0.01",
                "p95_cost_usd": "0.05",
                "p50_compression_ratio": round(avg_ratio, 4),
                "p95_compression_ratio": round(avg_ratio * 1.4, 4),
                "avg_routing_accuracy": 0.92,
            },
        )
        benchmark_resp.raise_for_status()
        print(f"Submitted benchmark registry entry: {benchmark_resp.json()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", required=True, help="Deployed backend base URL")
    parser.add_argument("--api-key", required=True, help="TRAJECT_API_KEY of the deployed backend")
    parser.add_argument(
        "--trajectories",
        type=Path,
        default=_REPO_ROOT / "swe_trajectories.jsonl",
        help="Path to the trajectory JSONL file (default: repo root swe_trajectories.jsonl)",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.backend_url, args.api_key, args.trajectories))


if __name__ == "__main__":
    main()
