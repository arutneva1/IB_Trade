
## What & Why
<!-- Briefly describe the change and the problem it solves. Link to SRS section and/or issue. -->

## Changes
- [ ] Summary of key changes

## How to Test
1. Install deps: `pip install -r requirements.txt && pip install ruff black mypy`
2. Lint/type/tests: `ruff check . && black --check . && mypy . && pytest -q`

## Checklist
- [ ] Tests added/updated and cover new code (≥90% diff coverage)
- [ ] CI is green (lint, type, tests)
- [ ] SRS/README updated if behavior changed
- [ ] No secrets/creds committed (env vars only)
- [ ] Default safety rails intact (paper_only, LMT, RTH)

## Out of Scope
<!-- Note anything intentionally deferred (e.g., TODO(phase-X)). -->
