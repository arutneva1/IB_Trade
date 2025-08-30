## What & Why
<!-- Briefly describe the change and the problem it solves. Cite relevant SRS acceptance criteria numbers (e.g., AC1, AC3) and link to sections/issues. -->

## SRS Acceptance Criteria
<!-- List the SRS AC numbers addressed by this PR. -->
- AC#

## Changes
- [ ] Summary of key changes

## How to Test
1. Install deps: `pip install -r requirements.txt && pip install ruff black mypy`
2. Lint/type/tests: `ruff check . && black --check . && mypy . && pytest -q`

## Checklist
- [ ] Tests added/updated and cover new code (≥90% diff coverage)
- [ ] CI is green (lint, type, tests)
- [ ] SRS/README updated if behavior changed
- [ ] PR description includes applicable SRS AC numbers
- [ ] No secrets/creds committed (env vars only)
- [ ] Default safety rails intact (paper_only, LMT, RTH)

## Out of Scope
<!-- Note anything intentionally deferred (e.g., TODO(phase-X)). -->
