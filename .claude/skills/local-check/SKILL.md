---
name: local-check
description: Run Traject's exact CI gate locally — pytest, mypy --strict, ruff check, ruff format --check — on the Python SDK (and backend if touched), and report pass/fail per tool. Use before saying a change is done, or before suggesting a commit/PR.
---

# Local check

Run the same checks CI and the pre-commit config enforce
(`.github/workflows/ci.yml`, `.pre-commit-config.yaml`), scoped to
whatever part of the repo was actually changed.

1. Determine scope from the diff: `sdk/python/` and/or `backend/`.
2. For `sdk/python/`:
   ```bash
   mypy sdk/python/traject --strict --config-file sdk/python/pyproject.toml
   ruff check sdk/python/
   ruff format --check sdk/python/
   pytest sdk/python/tests/ --cov=traject --cov-report=term-missing
   ```
3. For `backend/`:
   ```bash
   pytest backend/tests/
   ```
4. Report each tool's result separately (pass/fail), and for any failure
   show the actual error output — don't summarize it away. If coverage
   drops below 80% overall or 90% on `traject/compression/`, say so
   explicitly (per `.kiro/steering/standards.md`).
5. Don't claim the change is "done" if any of these fail. If a failure is
   pre-existing (unrelated to the current diff), say that explicitly and
   show evidence (e.g. it also fails on `git stash`), rather than quietly
   excusing it.
