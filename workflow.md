
# Codex Development Workflow — Quick Guide

This guide summarizes how to use `srs.md` and `plan.md` with Codex to build the IBKR ETF Rebalancer safely and incrementally.

## 1) Branch & PR Flow
- Protected `main`.
- Feature branches per phase (e.g., `feat/phase-1-portfolio-loader`).
- One module per PR + its tests.
- Conventional commits (e.g., `feat(loader): add CASH row validation`).

## 2) CI & Guardrails
- CI runs on every push/PR: `ruff`, `black --check`, `mypy`, `pytest`.
- DoD per PR:
  - Tests ≥90% diff coverage
  - CI green; verify GitHub Actions shows a green check before merging
  - SRS/README updated if behavior changes
  - No secrets committed
  - Safety rails intact (paper_only, LMT default, RTH, require_confirm, kill_switch_file, prefer_rth)

## 3) Task Card Template (paste into Codex prompt)
**Task:** Implement `<module>` per SRS (paste relevant subsection only).  
**Inputs/Outputs:** List signatures & dataclasses.  
**Constraints:** Python 3.11, `ib_async`, no network in unit tests, spread‑aware limits by default.  
**DoD:** tests pass; lint/type okay; docs updated; no unrelated files changed.  
**Deliver:** Code + tests + short notes.

## 4) Red–Green–Refactor Loop (Tell Codex to follow this)
1. Write tests first (do not implement yet).
2. Implement code to make tests pass.
3. Refactor with types/cleanup; keep tests green.

## 5) Phase Order (from `plan.md`)
- Phase 0: Bootstrap (CI, pre‑commit, skeleton files)
- Phase 1: Pure core (CSV loader, config with optional `[symbol_overrides]`, blending, rebalance math, reporting)
- Phase 2: Spread‑aware limit pricing + FakeQuoteProvider
- Phase 3: Account snapshot model (per‑currency cash)
- Phase 4: FX funding (math/plan only)
- Phase 5: Broker adapter (`ib_async`) with FakeIB
- Phase 6: Order builder & executor (dry‑run first)
- Phase 7: E2E offline scenarios
- Phase 8: CLI, logging, polish

## 6) Example Prompt (module)
> Implement `limit_pricer.py` per SRS `[limits]`: NBBO caps, mid ± offset*spread, tick rounding, `max_offset_bps`, stale/wide escalation. Write exhaustive pytest for spreads (1–100 bps), minTick grid, NBBO caps, stale quotes, escalation (`cross|market|keep`). Then implement the module. Keep tests green and code typed.

## 7) Example Prompt (PR boundaries)
> You may only change: `limit_pricer.py`, `tests/test_limit_pricer.py`. Do not modify other files.

## 8) Example Commands
```bash
ruff check . && black --check . && mypy . && pytest -q
python app.py --csv portfolios.csv --ini settings.ini --dry-run
```

## 9) Files Added by This Update
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`
- `.github/workflows/ci.yml`

Keep `srs.md` and `plan.md` at repo root; Codex will reference them in each task.
