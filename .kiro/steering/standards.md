# Axon — Coding Standards (Non-Negotiable)

These rules apply to every file in this repository without
exception. They are not preferences. They are constraints.

## Type safety

- Full type annotations on every function, method, and class attribute.
- `mypy --strict` must pass with zero errors on every commit.
- `py.typed` marker file present in the package root.
- No use of `Any` except where provably unavoidable,
  and only with an inline comment explaining why.
- TypeVar and Generic used correctly for generic utilities.

## Code quality

- `ruff check` and `ruff format --check` must pass clean.
- No `print()` statements anywhere in library code.
  Use `structlog.get_logger(__name__)` exclusively.
- No bare `except` clauses. Catch specific exception types only.
- No mutable default arguments.
- No star imports (`from x import *`).
- No circular imports. Module dependency direction is strictly:
    classifier  →  (no internal dependencies)
    compression →  classifier
    core        →  classifier, compression
    telemetry   →  core
    cli         →  core, telemetry

## Data modeling

- `Decimal` for all monetary values. Never `float` for currency.
- Pydantic v2 models or `@dataclass` for all structured data.
  Raw `dict` objects must not cross module boundaries.
- Enums for all categorical values (provider names, artifact types,
  strategies, environments). No magic strings.

## Documentation

- Module-level docstring on every `.py` file.
  Format: one-sentence summary, blank line, extended description.
- Google-style docstrings on every public class and method.
  Args, Returns, Raises sections required where applicable.
- Private helpers (prefixed `_`) require at minimum
  a one-line docstring.

## Error handling

- Define custom exception classes in `axon/exceptions.py`.
  Never raise bare `RuntimeError` or `ValueError` from library code
  without a descriptive message.
- Errors must be actionable. The message must tell the caller
  what went wrong and what they can do about it.

## Security defaults

- Prompt content is never stored or logged in plaintext.
  Always hash with SHA-256 before any persistence or telemetry.
- Provider API keys are never read, stored, or logged by Axon.
  Axon wraps the user's existing client; it never holds credentials.
- PII scrubbing is opt-in, never opt-out.

## Commits

- Conventional commit format: type(scope): description
  Types: feat, fix, chore, docs, test, refactor, perf, ci
  Example: `feat(compression): implement conservative segment pruning`
- Each commit is atomic: one logical change, all tests pass.
- No "WIP", "fix stuff", "update", or "misc" commit messages.
- No commits that mix refactoring with feature work.

## Testing

- Every public function has at least one test.
- Edge cases tested explicitly: empty inputs, boundary values,
  unknown/unsupported providers, malformed inputs.
- No mocking of the module under test.
  External API calls (OpenAI, Anthropic) are mocked at the
  HTTP transport layer using `pytest-httpx` or `respx`.
- Parametrize tests that share structure but differ in inputs.
- Test file mirrors source file: `axon/core/foo.py` →
  `tests/unit/test_foo.py`
- Coverage minimum: 80% overall, 90% on compression engine.

## Dependencies

- No new dependencies added without explicit justification in
  the PR description.
- All dependencies pinned to minimum compatible version
  (not exact version) in pyproject.toml.
- Dev dependencies kept strictly separate from runtime dependencies.
- The local embedding model (sentence-transformers) is a runtime
  dependency. It must never make external API calls.