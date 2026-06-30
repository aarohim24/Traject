# Traject — Documentation Index

This is the single entry point for all Traject documentation. Start here.

---

## Getting started

| Doc | What it covers |
|---|---|
| [Quickstart](quickstart.md) | Install, first call, shadow mode, self-hosted backend setup |
| [Compression Guide](compression-guide.md) | How the compression pipeline works; strategies; tuning |
| [Router Guide](router-guide.md) | Rule-based and ML model routing; A/B testing |
| [Testing](testing.md) | How to run the test suite; benchmark reproduction |

## Architecture

| Doc | What it covers |
|---|---|
| [Architecture](architecture.md) | System design, module boundaries, data flow |
| [Batch Routing](batch-routing.md) | Async batch submission to OpenAI / Anthropic batch APIs |
| [Cascade Tracing](cascade-tracing.md) | Multi-hop agent tracing and parent span propagation |
| [ML Router Guide](ml-router-guide.md) | Conformal prediction router; training and calibration |
| [Prompt Cache Advisor](prompt-cache-advisor.md) | Anthropic prompt cache optimization hints |
| [Plugin Development](plugin-development.md) | Writing custom compression and routing plugins |
| [Provider Expansion](provider-expansion.md) | Adding new LLM providers to the SDK |

## Operations

| Doc | What it covers |
|---|---|
| [Dashboard Guide](dashboard-guide.md) | React dashboard: cost overview, budgets, compression ROI |
| [Enterprise Auth](enterprise-auth.md) | Multi-tenant API keys, RBAC, SSO integration |
| [Kubernetes Deployment](kubernetes-deployment.md) | Helm chart; values reference; production hardening |
| [Production Validation](production-validation.md) | Pre-launch checklist; smoke tests; alerting setup |

## Community

| Doc | What it covers |
|---|---|
| [Governance](community/GOVERNANCE.md) | Project governance, decision-making, roles |
| [RFC Template](community/RFC_TEMPLATE.md) | Proposing significant changes |
| [Contributing](../CONTRIBUTING.md) | Development setup, PR process, coding standards |
| [Code of Conduct](../CODE_OF_CONDUCT.md) | Community standards |
| [Security](../SECURITY.md) | Vulnerability disclosure policy |

---

## SDK READMEs

- [Python SDK](../sdk/python/README.md) — `traject-sdk` pip package
- [TypeScript SDK](../sdk/typescript/README.md) — `@traject-sdk/typescript` npm package

## Deployment READMEs

- [Kubernetes / Helm](../deploy/kubernetes/README.md)

## Examples

- [OpenAI basic](../examples/openai-basic/README.md)
- [LangChain agent](../examples/langchain-agent/README.md)
- [Quickstart demo](../examples/quickstart/README.md)
- [Benchmark scripts](../examples/benchmark/)
