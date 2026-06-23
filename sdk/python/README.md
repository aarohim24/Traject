# Axon

[![PyPI](https://img.shields.io/pypi/v/axon-sdk)](https://pypi.org/project/axon-sdk/)
[![CI](https://github.com/aarohimathur/axon/actions/workflows/ci.yml/badge.svg)](https://github.com/aarohimathur/axon/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**AI inference observability and trajectory optimization middleware.**

Axon is a Python SDK that instruments LLM API calls to emit structured OpenTelemetry spans with exact cost attribution, artifact classification, and trajectory compression analysis. It wraps your existing OpenAI or Anthropic client with a single decorator — no behavioral changes required.

The mental model is DataDog APM applied to AI inference, not a browser plugin or prompt coaching tool.

---

## What Axon Is

- Infrastructure middleware for LLM observability
- Exact token counts and USD cost per call (Decimal precision, no float drift)
- OpenTelemetry span emission — compatible with DataDog, Grafana, Honeycomb, Jaeger
- Trajectory compression analysis in shadow mode: see what *would* be compressed without touching live context
- Artifact classification: SYSTEM_PROMPT, TOOL_RESULT, RAG_CHUNK, REASONING_BLOCK, and more

## What Axon Is Not

- Not a prompt coaching tool
- Not a VS Code extension
- Not a chatbot or LLM wrapper
- Not a cloud service (Phase 1 is self-contained library + CLI)

---

## Quickstart

```bash
pip install axon-sdk[openai]
```

```python
import axon
import openai

@axon.instrument(feature_tag="support-bot")
def call_llm(messages):
    client = openai.OpenAI()
    return client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
    )

response = call_llm([
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"},
])
```

On the first call you'll see an OTEL span printed to stdout showing token counts, cost in USD, and compression analysis.

### Patch an existing client

```python
import axon
import openai

client = openai.OpenAI()
axon.patch(client, feature_tag="my-agent")

# All subsequent calls are automatically instrumented
response = client.chat.completions.create(model="gpt-4o", messages=[...])
```

---

## Architecture

```
axon/
├── core/          # Instrumentor, provider adapters, cost calculator
├── compression/   # Compression engine, segment parser, relevance scorer
├── classifier/    # Heuristic artifact type classification
├── telemetry/     # OpenTelemetry span exporter
└── cli/           # axon analyze / version / doctor
```

Dependency direction is strictly enforced (no circular imports):
`classifier → compression → core → telemetry → cli`

---

## CLI

```bash
# Check dependencies
axon doctor

# Print version
axon version

# Analyze a local span log
axon analyze --input spans.jsonl
```

---

## Integration paths

### Decision tree — which integration is right for you?

```
Are you writing new Python code?
  └─ Yes → Use the Python SDK directly (pip install traject-sdk)
  └─ No — I want zero code changes
       ├─ Using an MCP-compatible client (Copilot, Claude Desktop, Cursor)?
       │    └─ Use the MCP server  →  traject mcp
       └─ Running an existing agent or service with an OpenAI-compatible client?
            └─ Use the proxy  →  traject proxy --port 8080 --backend https://api.openai.com
                                  # Then: OPENAI_BASE_URL=http://localhost:8080
```

### MCP server

Exposes Traject's compression pipeline as three MCP tools that any MCP-compatible
client can call without code changes or API keys.

```bash
pip install "traject-sdk[mcp]"

# Add to your MCP client config (stdio transport, works with Copilot, Claude Desktop, Cursor):
# command: traject
# args: ["mcp"]

traject mcp
```

**Tools registered:**
- `traject_compress(text, strategy, shadow_mode)` — compress a text blob, returns delta metrics
- `traject_stats()` — session-level aggregate reduction statistics
- `traject_budget(limit_tokens)` — check token spend vs a configurable budget threshold

**Shadow mode (default):** compression runs but the original text is returned alongside metrics.
Set `shadow_mode=False` to apply live compression.

### OpenAI-compatible transparent proxy

Drop-in replacement for any OpenAI-compatible endpoint. Point your agent at the proxy
instead of the provider — no other changes needed.

```bash
pip install "traject-sdk[proxy]"

traject proxy --port 8080 --backend https://api.openai.com
# Strategy options: conservative (default), moderate, aggressive
# Add --live to enable actual compression (default is shadow mode)

# Then in your agent or environment:
export OPENAI_BASE_URL=http://localhost:8080
```

Response headers injected by the proxy:
- `X-Traject-Tokens-Saved` — tokens eliminated this request (0 in shadow mode)
- `X-Traject-Shadow-Mode` — `true` or `false`

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions.

---

## License

MIT — see [LICENSE](LICENSE).
