# Phase 0 PR Review Checklist

Copy/paste into your PR or keep this file in `.github/` to guide reviews for **Phase 0** (bootstrap & guardrails).

---

## Quick gates
- [ ] No API credentials or other secrets committed (see SRS §11)
- [ ] Scope is Phase 0 only (repo scaffolding; no app logic yet)
- [ ] Only expected scaffolding files touched (`requirements*.txt`, `pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/*`, `Makefile`, placeholders)
- [ ] No external network or broker dependencies introduced
- [ ] PR description references relevant SRS acceptance criteria (AC#)
- [ ] CHANGELOG.md updated under the latest release heading

## Repo scaffolding
- [ ] `requirements.txt` and `pyproject.toml` exist with core tooling deps
- [ ] `.pre-commit-config.yaml` configured for `ruff` and `black`
- [ ] GitHub Actions workflow runs lint, type-check, and tests
- [ ] `Makefile` exposes `lint`, `type`, `test`, and `run` targets
- [ ] Empty modules include docstrings/TODOs matching **SRS §7 Data Structures**

## CI & local checks
- [ ] CI is green (`ruff`, `black --check`, `mypy`, `pytest`) on an empty test suite (keep one smoke test)
- [ ] Local sanity: `ruff check . && black --check . && mypy . && pytest -q` all pass

## Alignment with SRS
- [ ] Dataclass templates follow **SRS §7 Data Structures** for config, holdings, and plan placeholders
