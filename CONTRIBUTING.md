# Contributing to Traject

Thank you for taking the time to contribute. This document covers everything you need to get a working development environment, understand the code standards, and submit a pull request.

---

## Table of Contents

- [Development Setup](#development-setup)
- [Code Standards](#code-standards)
- [Commit Convention](#commit-convention)
- [Pull Request Checklist](#pull-request-checklist)
- [Good First Issues](#good-first-issues)
- [Architecture Overview](#architecture-overview)

---

## Development Setup

### 1. Clone the repository

```bash
git clone https://github.com/aarohim24/Traject.git
cd Traject
```

### 2. Create and activate a virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Python 3.11 is the minimum supported version.

### 3. Install the SDK in editable mode with dev extras

```bash
pip install -e "sdk/python[dev,openai,anthropic,langchain]"
```

This installs the SDK itself plus all tooling: `pytest`, `mypy`, `ruff`, `pytest-cov`, `pytest-httpx`, `hypothesis`, and the framework extras.

### 4. Run the test suite

```bash
pytest sdk/python/tests/
```

To run with coverage:

```bash
pytest sdk/python/tests/ --cov=traject --cov-report=term-missing
```

### 5. Run type checking and linting

```bash
mypy --strict sdk/python/traject/
ruff check sdk/python/
ruff format --check sdk/python/
```

All three must pass clean before submitting a PR.

---

## Code Standards

These are enforced in CI and are non-negotiable.

### Type safety

- Full type annotations on every function, method, and class attribute.
- `mypy --strict` must pass with zero errors.
- No use of `Any` except where unavoidable, and only with an inline comment explaining why.

### Code quality

- `ruff check` and `ruff format --check` must pass clean.
- No `print()` statements in library code — use `structlog.get_logger(__name__)`.
- No bare `except` clauses. Catch specific exception types.
- No mutable default arguments, star imports, or circular imports.

### Data modeling

- `decimal.Decimal` for all monetary values. Never `float` for currency.
- Pydantic v2 models or `@dataclass` for all structured data that crosses module boundaries.
- Enums for all categorical values (provider names, artifact types, strategies).

### Documentation

- Module-level docstring on every `.py` file.
- Google-style docstrings on every public class and method (Args, Returns, Raises).
- Private helpers (`_` prefix) require at minimum a one-line docstring.

### Coverage

- 80% overall minimum.
- 90% minimum on the compression engine.

---

## Commit Convention

Traject uses [Conventional Commits](https://www.conventionalcommits.org/).

```
type(scope): short imperative description
```

**Types:** `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`, `ci`

**Examples:**

```
feat(compression): implement conservative segment pruning
fix(telemetry): handle missing usage block in streaming response
chore(pricing): update gpt-4o input cost to $2.50/1M tokens
test(classifier): add parametrized edge cases for SYSTEM_PROMPT type
docs(readme): add quickstart example for AutoGen integration
```

**Rules:**

- Each commit is atomic: one logical change, all tests pass.
- No "WIP", "fix stuff", "update", or "misc" messages.
- Do not mix refactoring with feature work in a single commit.

---

## Pull Request Checklist

Before marking a PR ready for review, confirm all of the following:

- [ ] `pytest` passes with no failures
- [ ] Coverage is at or above the minimums (80% overall, 90% compression engine)
- [ ] `mypy --strict` reports zero errors
- [ ] `ruff check` and `ruff format --check` pass clean
- [ ] New public functions and classes have Google-style docstrings
- [ ] `CHANGELOG.md` updated if the change is user-visible
- [ ] PR title follows conventional commit format
- [ ] No new runtime dependencies added without justification in the PR description

---

## Good First Issues

Looking for a place to start? Browse issues labelled
[`good-first-issue`](https://github.com/aarohim24/Traject/issues?q=is%3Aopen+is%3Aissue+label%3Agood-first-issue)
on GitHub.

These are scoped to be self-contained and well-defined, with enough context to get started without deep knowledge of the whole codebase.

---

## Architecture Overview

The SDK is organised into five layers with a strict one-way dependency chain. A module may only import from layers listed to its right.

```
cli  →  telemetry  →  core  →  compression  →  classifier
```

| Module | Responsibility | May import from |
|---|---|---|
| `classifier` | Artifact type classification (9 types) | No internal dependencies |
| `compression` | Trajectory compression engine (3 strategies), framework adapters | `classifier` |
| `core` | Instrumentation decorators, pricing, cost calculation, exceptions | `classifier`, `compression` |
| `telemetry` | OpenTelemetry span emission and exporters | `core` |
| `cli` | `traject analyze`, `traject version`, `traject doctor` commands | `core`, `telemetry` |

**Key constraints:**

- `classifier` has no internal imports — it is the base layer.
- `compression` never imports from `core` or `telemetry`.
- `core` never imports from `telemetry` or `cli`.
- Framework adapters live in `compression/adapters/` and guard framework imports with `try/except ImportError`.
- The backend (`backend/traject_backend/`) is a separate package and does not import from the SDK at runtime.

Circular imports are a hard failure in CI (`ruff` import cycle checks are enabled).
