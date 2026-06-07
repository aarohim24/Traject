# Quickstart

Get Axon running in under 5 minutes.

## Install

```bash
# OpenAI
pip install axon-sdk[openai]

# Anthropic
pip install axon-sdk[anthropic]

# LangChain
pip install axon-sdk[openai,langchain]
```

## Example 1: Raw OpenAI with @axon.instrument()

```python
import axon
import openai

@axon.instrument(feature_tag="support-bot", shadow_mode=True)
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
- `axon.cost_usd` — exact USD cost using Decimal arithmetic
- `axon.compression.shadow_mode = true` — compression ran but messages were not modified

## Example 2: LangChain with axon.patch()

```python
import axon
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

model = ChatOpenAI(model="gpt-4o-mini")
axon.patch(model, feature_tag="langchain-agent", shadow_mode=True)

response = model.invoke([
    SystemMessage(content="You are a helpful assistant."),
    HumanMessage(content="What is 2+2?"),
])
print(response.content)
```

## Example 3: Async OpenAI with @axon.instrument()

```python
import asyncio
import axon
import openai

@axon.instrument(feature_tag="async-bot", shadow_mode=True)
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

## Configure OTLP Export

To export spans to a collector (DataDog, Grafana, Jaeger):

```bash
export AXON_OTLP_ENDPOINT=http://localhost:4317
```

Or configure programmatically:

```python
axon.configure(otlp_endpoint="http://localhost:4317", export_to_stdout=False)
```

## CLI

```bash
axon doctor          # check dependencies
axon version         # print version
axon analyze --input spans.jsonl  # analyze span log
```
