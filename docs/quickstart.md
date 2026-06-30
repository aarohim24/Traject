# Quickstart

Get Traject running in under 5 minutes.

## Install

```bash
# OpenAI
pip install traject-sdk[openai]

# Anthropic
pip install traject-sdk[anthropic]

# LangChain
pip install traject-sdk[openai,langchain]
```

## Example 1: Raw OpenAI with @traject.instrument()

```python
import traject
import openai

@traject.instrument(feature_tag="support-bot", shadow_mode=True)
def call_llm(messages):
    client = openai.OpenAI()
    return client.chat.completions.create(model="gpt-4o", messages=messages)

response = call_llm([
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"},
])
print(response.choices[0].message.content)
```

The OTEL span printed to stdout will show:
- `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- `traject.cost_usd` — exact USD cost using Decimal arithmetic
- `traject.compression.shadow_mode = true` — compression ran but messages were not modified

## Example 2: LangChain with traject.patch()

```python
import traject
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

model = ChatOpenAI(model="gpt-4o-mini")
traject.patch(model, feature_tag="langchain-agent", shadow_mode=True)

response = model.invoke([
    SystemMessage(content="You are a helpful assistant."),
    HumanMessage(content="What is 2+2?"),
])
print(response.content)
```

## Example 3: Async OpenAI with @traject.instrument()

```python
import asyncio
import traject
import openai

@traject.instrument(feature_tag="async-bot", shadow_mode=True)
async def call_llm_async(messages):
    client = openai.AsyncOpenAI()
    return await client.chat.completions.create(model="gpt-4o-mini", messages=messages)

async def main():
    response = await call_llm_async([
        {"role": "user", "content": "Tell me a one-line joke."},
    ])
    print(response.choices[0].message.content)

asyncio.run(main())
```

## Self-hosted backend (optional)

The self-hosted backend adds cost attribution by feature tag, budget controls,
anomaly detection, semantic caching, and Grafana dashboards. The SDK works
standalone without it.

### 1. Bootstrap secrets (one command)

```bash
bash scripts/setup.sh
```

This generates `deploy/.env` with strong random passwords and API keys, prints
your API key, and tells you exactly what to set. Never run docker compose before
this step — the backend refuses to start with the placeholder key.

### 2. Start the stack

```bash
docker compose -f deploy/docker-compose.yml up -d
```

Services: PostgreSQL 16 + pgvector, Redis 7, Traject backend (`:8000`),
Grafana dashboards (`:3000`), React dashboard (`:5173`).

### 3. Point the SDK at the backend

```python
import traject

traject.configure(
    backend_url="http://localhost:8000",
    backend_api_key="<key printed by setup.sh>",
)
```

### Local development without the backend

To develop against the backend directly (without docker), set:

```bash
ALLOW_INSECURE_API_KEY=true   # skip the "change your key" startup guard
DATABASE_URL=postgresql+asyncpg://traject:traject@localhost:5432/traject
REDIS_URL=redis://localhost:6379/0
```

Or in Python:

```python
import os
os.environ["ALLOW_INSECURE_API_KEY"] = "true"
```

## Configure OTLP Export

To export spans to a collector (DataDog, Grafana, Jaeger):

```bash
export AXON_OTLP_ENDPOINT=http://localhost:4317
```

Or configure programmatically:

```python
traject.configure(otlp_endpoint="http://localhost:4317", export_to_stdout=False)
```

## CLI

```bash
traject doctor          # check dependencies
traject version         # print version
traject analyze --input spans.jsonl  # analyze span log
```
