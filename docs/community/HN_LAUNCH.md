Do not post until production validation data is collected

---

# Show HN: Axon — open-source LLM cost optimization middleware

---

## Draft Post

**Title:** Show HN: Axon – open-source middleware that compresses LLM context, routes requests, and attributes cost in production

**Body:**

Hi HN,

We built Axon to solve a problem we kept running into in production agent systems: every LLM call re-pays for the entire accumulated context — tool outputs, reasoning traces, past messages. For a 10-step agent, that means you pay for the same tokens up to 10 times over.

Axon is a drop-in Python middleware layer that:

- **Compresses context trajectories** before they reach the provider (three strategies: conservative, moderate, aggressive). No prompt content is stored or logged.
- **Routes requests** to the cheapest qualifying model based on task type, with optional ML-learned routing and conformal prediction quality guarantees.
- **Attributes cost** at the feature level so you can see exactly which part of your system is spending what.
- **Enforces budgets** with webhook alerting before you hit unexpected charges.
- **Instruments with OpenTelemetry** — works with DataDog, Grafana, Honeycomb, anything OTEL-compatible.

It wraps your existing `openai.OpenAI()` or `anthropic.Anthropic()` client — no refactoring required.

```python
import openai, axon

axon.configure()
client = openai.OpenAI()
axon.patch(client, feature_tag="my_agent", shadow_mode=True)
# shadow_mode=True: compression runs, but original context is returned
# until you validate savings and flip the flag
```

**Links:**
- GitHub: https://github.com/aarohimathur/axon
- Docs: https://github.com/aarohimathur/axon/tree/main/docs
- Benchmark registry: https://github.com/aarohimathur/axon/blob/main/docs/research-paper.md

**What's different from other LLM cost tools:**
Most tools focus on prompt engineering or model selection. Axon operates at the infrastructure layer — it's middleware, not advice. It works with whatever model you're already using.

**Production benchmark results:**

[PLACEHOLDER: insert production data]

_(This section will be populated with real-world validation numbers before this post goes live. We are actively collecting production data from opted-in deployments via the community benchmark registry at `/v1/benchmarks`.)_

**What we're looking for:**
- Early adopters who want to validate compression ratios on their own agent workloads
- Feedback on the plugin system API (for custom compression strategies)
- Contributors interested in the ML router or Bedrock/Vertex adapters

Happy to answer any questions about the architecture or design decisions.

---

## Checklist Before Posting

- [ ] Production validation data collected and inserted above
- [ ] Benchmark registry has at least 10 real submissions
- [ ] All links verified and resolving
- [ ] README benchmark numbers updated with production data
- [ ] Research paper evaluation section filled in (no `[TBD]` remaining)
- [ ] PyPI package published and installable (`pip install axon-sdk`)
- [ ] Docker Compose one-command startup verified on a clean machine
