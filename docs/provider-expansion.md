# Provider Expansion Guide

Axon Phase 5 adds native adapters for **AWS Bedrock** and **Google Vertex AI**,
extending the existing OpenAI and Anthropic support.

---

## AWS Bedrock (`BedrockAdapter`)

`BedrockAdapter` calls the AWS Bedrock `InvokeModel` API via `boto3` and
translates between Axon's message format and the model-family-specific request
body formats.

### Supported model families

| Family | Example model IDs |
|---|---|
| Amazon Titan | `amazon.titan-text-express-v1`, `amazon.titan-text-lite-v1` |
| Anthropic Claude (via Bedrock) | `anthropic.claude-3-5-sonnet-20241022-v2:0`, `anthropic.claude-3-haiku-20240307-v1:0` |
| Meta Llama (via Bedrock) | `meta.llama3-8b-instruct-v1:0`, `meta.llama3-70b-instruct-v1:0` |

### Installation

```bash
pip install "axon-sdk[bedrock]"
```

This installs `boto3`.  If `boto3` is not installed and you attempt to
instantiate `BedrockAdapter`, you will receive an `AxonDependencyError` with
installation instructions.

### AWS credentials

`BedrockAdapter` uses your existing boto3 credentials.  Configure them using
any standard boto3 credential provider:

```bash
# Environment variables
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1

# Or use ~/.aws/credentials / IAM roles
```

Axon never reads, stores, or logs AWS credentials.  It calls boto3 which
manages credentials entirely outside of Axon.

### Usage

```python
from axon.providers.bedrock import BedrockAdapter

adapter = BedrockAdapter(region_name="us-east-1")

response = adapter.complete(
    messages=[{"role": "user", "content": "Hello, world!"}],
    model="anthropic.claude-3-haiku-20240307-v1:0",
)

print(response.content)
print(f"Tokens: {response.input_tokens} in / {response.output_tokens} out")
print(f"Provider: {response.provider}")  # always "bedrock"
```

### ProviderResponse

```python
@dataclass
class ProviderResponse:
    content: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str          # "bedrock" for BedrockAdapter
    raw_response: dict     # The raw Bedrock response dict
```

---

## Google Vertex AI (`VertexAdapter`)

`VertexAdapter` calls the Google Vertex AI `generateContent` API via the
`google-cloud-aiplatform` SDK.

### Supported models

| Model ID |
|---|
| `gemini-1.5-pro` |
| `gemini-1.5-flash` |
| `gemini-1.0-pro` |

### Installation

```bash
pip install "axon-sdk[vertex]"
```

This installs `google-cloud-aiplatform`.  If not installed and you attempt to
instantiate `VertexAdapter`, you will receive an `AxonDependencyError`.

### Google Cloud credentials

`VertexAdapter` uses Application Default Credentials (ADC):

```bash
gcloud auth application-default login
# Or set GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### Usage

```python
from axon.providers.vertex import VertexAdapter

adapter = VertexAdapter(project="my-gcp-project", location="us-central1")

response = adapter.complete(
    messages=[{"role": "user", "content": "Explain conformal prediction."}],
    model="gemini-1.5-flash",
)

print(response.content)
print(f"Tokens: {response.input_tokens} in / {response.output_tokens} out")
```

---

## Importing Adapters

Both adapters are importable from `axon.providers` without installing optional
dependencies — lazy import guards ensure that the import only fails when you
actually instantiate the adapter:

```python
# Always safe — no boto3 or google-cloud required
from axon.providers import BedrockAdapter, VertexAdapter, ProviderResponse

# Instantiation raises AxonDependencyError if dependency not installed
adapter = BedrockAdapter()  # fails cleanly if boto3 missing
```

---

## Using Adapters with the Router

Provider adapters integrate with Axon's routing layer.  When the `MLRouter`
or `RuleRouter` selects a model on Bedrock or Vertex, Axon automatically
routes the request to the appropriate adapter:

```python
import axon

axon.configure(
    providers={
        "bedrock": BedrockAdapter(region_name="us-east-1"),
        "vertex": VertexAdapter(project="my-project", location="us-central1"),
    }
)
```

---

## See Also

- [ml-router-guide.md](ml-router-guide.md) — routing configuration
- [batch-routing.md](batch-routing.md) — batch API cost reduction
- [plugin-development.md](plugin-development.md) — custom provider plugins
