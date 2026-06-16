# Security Policy

## Scope

This policy covers security vulnerabilities in:

- **Traject Python SDK** (`sdk/python/`) — instrumentation, compression engine, artifact classifier, CLI
- **Traject Backend** (`backend/`) — FastAPI service, span ingestion, cost attribution, semantic cache, budget controls

Out of scope: third-party dependencies (report those directly to the upstream project), deployment infrastructure owned by the user, or issues in example scripts that do not affect library code.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Email **security@traject.dev** with the subject line: `[SECURITY] <brief description>`.

Your report will be handled privately until a fix is released and coordinated disclosure is complete.

### What to Include

A useful report contains:

1. **Description** — what the vulnerability is and what an attacker could achieve
2. **Affected component** — SDK, backend, or both; include the version or commit hash
3. **Reproduction steps** — a minimal, self-contained example that demonstrates the issue
4. **Environment** — Python version, OS, relevant dependency versions
5. **Suggested fix** (optional) — if you have a patch or mitigation in mind

The more detail you provide, the faster we can triage and fix the issue.

## Response Commitment

| Milestone | Target |
|---|---|
| Acknowledgement | Within 48 hours of receipt |
| Initial triage | Within 5 business days |
| Fix or mitigation | Depends on severity; critical issues are prioritised |
| Coordinated disclosure | We will notify you before any public release |

We follow responsible disclosure. We ask that you give us reasonable time to release a fix before making any details public.

## Preferred Languages

We accept reports in English.
