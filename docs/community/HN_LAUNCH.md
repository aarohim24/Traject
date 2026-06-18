---

# Show HN: Traject — open-source LLM cost optimization middleware

---

## Draft Post

**Title:** Show HN: Traject – open-source middleware that compresses LLM context, routes requests, and attributes cost in production

**Body:**

Hi HN,

We built Traject to solve a problem we kept running into in production agent systems: every LLM call re-pays for the entire accumulated context — tool outputs, reasoning traces, past messages. For a 10-step agent, that means you pay for the same tokens up to 10 times over.

Traject is a drop-in Python middleware layer that:

- **Compresses context trajectories** before they reach the provider (three strategies: conservative, moderate, aggressive). No prompt content is stored or logged.
- **Routes requests** to the cheapest qualifying model based on task type, with optional ML-learned routing and conformal prediction quality guarantees.
- **Attributes cost** at the feature level so you can see exactly which part of your system is spending what.
- **Enforces budgets** with webhook alerting before you hit unexpected charges.
- **Instruments with OpenTelemetry** — works with DataDog, Grafana, Honeycomb, anything OTEL-compatible.

It wraps your existing `openai.OpenAI()` or `anthropic.Anthropic()` client — no refactoring required.

```python
import openai, traject

traject.configure()
client = openai.OpenAI()
traject.patch(client, feature_tag="my_agent", shadow_mode=True)
# shadow_mode=True: compression runs, but original context is returned
# until you validate savings and flip the flag
```

**Links:**
- GitHub: https://github.com/aarohimathur/traject
- Docs: https://github.com/aarohimathur/traject/tree/main/docs

**What's different from other LLM cost tools:**
Most tools focus on prompt engineering or model selection. Traject operates at the infrastructure layer — it's middleware, not advice. It works with whatever model you're already using.

**Production benchmark results:**

Evaluated on 42 real SWE-bench agent trajectories from [SWE-Gym/OpenHands-SFT-Trajectories](https://huggingface.co/datasets/SWE-Gym/SWE-Gym) (HuggingFace). Strategy: CONSERVATIVE. Avg 29 turns/trajectory.

| Metric | Result |
|---|---|
| Aggregate token reduction | **29.1%** |
| Median (p50) reduction | 24.3% |
| p95 reduction | 57.5% |
| Total tokens saved | 196,000 |
| Instances evaluated | 42 |

Reproduce: `python examples/benchmark/swebench_eval.py --input trajectories.jsonl`

**What we're looking for:**
- Early adopters who want to validate compression ratios on their own agent workloads
- Feedback on the plugin system API (for custom compression strategies)
- Contributors interested in the ML router or Bedrock/Vertex adapters

Happy to answer any questions about the architecture or design decisions.

---

## Checklist Before Posting

- [x] Production validation data collected and inserted above (SWE-bench, 29.1% reduction)
- [ ] Benchmark registry has at least 10 real submissions
- [x] README benchmark numbers updated with production data
- [ ] PyPI package published and installable (`pip install traject-sdk`)
- [ ] Docker Compose one-command startup verified on a clean machine
