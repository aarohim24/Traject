# @traject-sdk/typescript

TypeScript SDK for [Traject](https://github.com/aarohim24/Traject) — LLM inference observability, cost attribution, and span emission for Node.js applications.

## What it does

- Instruments OpenAI and Anthropic clients with a single `patch()` call
- Emits structured `InferenceSpan` records for every LLM call
- Calculates inference cost using the same pricing table as the Python SDK
- Exports spans to stdout (console) or to the Traject backend service
- Zero changes to your existing code required

## Install

```bash
npm install @traject-sdk/typescript
```

Peer dependencies (install the ones you use):

```bash
npm install openai               # if using OpenAI
npm install @anthropic-ai/sdk    # if using Anthropic
```

## Quickstart

### Instrument OpenAI

```typescript
import OpenAI from "openai";
import { patch, configure } from "@traject-sdk/typescript";

// Optional: configure export settings
configure({
  exportToConsole: true,
  featureTag: "my-feature",
});

const client = new OpenAI();
patch(client); // wraps client.chat.completions.create in place

// Use your client exactly as before — spans are emitted automatically
const response = await client.chat.completions.create({
  model: "gpt-4o-mini",
  messages: [{ role: "user", content: "Hello!" }],
});
```

### Instrument Anthropic

```typescript
import Anthropic from "@anthropic-ai/sdk";
import { patch, configure } from "@traject-sdk/typescript";

configure({
  backendUrl: "http://localhost:8000",
  apiKey: "your-traject-api-key",
  featureTag: "my-feature",
});

const client = new Anthropic();
patch(client); // wraps client.messages.create in place

const response = await client.messages.create({
  model: "claude-3-5-haiku-20241022",
  max_tokens: 256,
  messages: [{ role: "user", content: "Hello!" }],
});
```

### Calculate cost manually

```typescript
import { calculateCost } from "@traject-sdk/typescript";

const cost = calculateCost("gpt-4o-mini", 1000, 500);
// => "0.00022500"  (string with 8 decimal places)

const unknown = calculateCost("unknown-model", 1000, 500);
// => null
```

### Use the `instrument` decorator

```typescript
import { instrument } from "@traject-sdk/typescript";

class MyAgent {
  @instrument({ featureTag: "agent-run" })
  async run(prompt: string): Promise<string> {
    // ... your LLM call here
    return "result";
  }
}
```

## Configuration

| Option | Type | Default | Description |
|---|---|---|---|
| `apiKey` | `string` | — | Traject backend API key |
| `backendUrl` | `string` | — | Traject backend base URL |
| `exportToConsole` | `boolean` | `false` | Log spans as JSON to stdout |
| `featureTag` | `string` | — | Label for cost attribution grouping |

## Types

See [`src/types.ts`](./src/types.ts) for the full TypeScript type definitions including `InferenceSpan`, `UsageData`, `ArtifactType`, and `TrajectConfig`.

## Development

```bash
npm install
npm run typecheck   # tsc --noEmit
npm run lint        # eslint src
npm test            # jest
npm run build       # tsc (outputs to dist/)
```

## License

MIT
